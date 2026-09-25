"""
schwab_raw_marketdata.py
========================================================================================
Institutional Charles Schwab Market Data Extraction & Upstream Normalization Layer
Protocol v16.21 Production Certified
========================================================================================
Changelog v16.21 (Round-Twenty Spec Lock):
  - Form A non-falsy payload unwrapping loop with secondary batch double-nesting check.
  - Fail-safe SAFE-01 locate semantics with short_locate_partial_reason diagnostic.
  - Strict vendor-key volume extraction via avg10DaysVolume and avg1YearVolume.
  - Anchored LIQUIDITY_SUSPECT_VOLUME_THRESHOLD = 1_000_000.0 constant.
  - Semantic separation: vol10DayAvg, vol1YearAvg, and vol3MonthAvg: null.
  - PAY-76: margin_fields_suspect routes to null with VENDOR_UNAVAILABLE_INPUTS_ABSENT.
  - PAY-77: divYield: 0.0 on non-payers tagged AS_REPORTED_ZERO_NON_PAYER.
========================================================================================
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
from schwab_client import SchwabClient

logger = logging.getLogger("schwab_raw_marketdata")
logger.addHandler(logging.NullHandler())

# Diagnostic Reason and State Constants
REASON_DTE_BELOW_MINIMUM_4 = "DTE_BELOW_MINIMUM_4"
STATE_AS_REPORTED_POSITIVE_MARGIN = "AS_REPORTED_ZERO_WITH_POSITIVE_MARGIN"
STATE_ZERO_NET_MARGIN_MISSING = "VENDOR_ZERO_UNCORROBORATED_NET_MARGIN_MISSING"
STATE_UNAVAILABLE_FOREIGN_ADR = "UNAVAILABLE_FOR_FOREIGN_ADR"
STATE_UNAVAILABLE_EPS_POSITIVE_MARGIN = "VENDOR_UNAVAILABLE_EPS_ZERO_WITH_POSITIVE_MARGIN"

ALLOWED_DIV_FREQS: Set[float] = {1.0, 2.0, 4.0, 12.0}
LIQUIDITY_SUSPECT_VOLUME_THRESHOLD: float = 1_000_000.0


def _clean_numeric_val(val: Any) -> Optional[float]:
    """Coerces numerical inputs to clean float primitives or None."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = val.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return None
    return None


def extract_market_open_status(client: SchwabClient, tz: Optional[ZoneInfo] = None) -> Optional[bool]:
    """Queries Schwab to determine whether the equity market is open today."""
    try:
        if hasattr(client, "get_market_hours"):
            try:
                raw_hours = client.get_market_hours("equity")
            except TypeError:
                try:
                    raw_hours = client.get_market_hours(markets="equity")
                except TypeError:
                    raw_hours = client.get_market_hours()

            if isinstance(raw_hours, dict):
                if "isOpen" in raw_hours:
                    return raw_hours.get("isOpen", False)
                return raw_hours.get("equity", {}).get("EQ", {}).get("isOpen", False)
    except Exception as exc:
        logger.warning("MarketHours retrieval skipped: %s", exc)
    return None


def extract_in_memory_price_history(
    client: SchwabClient,
    symbol: str,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Fetches historical daily price candles in-memory."""
    cfg = config or {}
    try:
        raw = client.get_price_history(
            symbol=symbol,
            period_type=cfg.get("HISTORICAL_PERIOD_TYPE", "year"),
            period=cfg.get("HISTORICAL_PERIOD", 1),
            frequency_type=cfg.get("HISTORICAL_FREQUENCY_TYPE", "daily"),
            frequency=cfg.get("HISTORICAL_FREQUENCY", 1),
            need_extended_hours=cfg.get("HISTORICAL_NEED_EXTENDED_HOURS", False),
        )
        candles = raw.get("candles", []) if isinstance(raw, dict) else []
        df = pd.DataFrame(candles)
        if df.empty:
            return []

        cols = ["datetime", "open", "high", "low", "close", "volume"]
        existing = [c for c in cols if c in df.columns]
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df[existing].dropna().to_dict(orient="records")
    except Exception as exc:
        logger.error("PriceHistory query failed for %s: %s", symbol, exc)
        return []


def extract_in_memory_option_expirations(client: SchwabClient, symbol: str) -> List[Dict[str, Any]]:
    """Retrieves option expiration schedules in-memory."""
    try:
        payload = client.get_option_expirations(symbol)
        exp_list = payload.get("expirationList", [])
        if not exp_list:
            return []
        df = pd.DataFrame(exp_list)
        cols = ["expirationDate", "daysToExpiration"]
        existing = [c for c in cols if c in df.columns]
        return df[existing].sort_values("daysToExpiration").to_dict(orient="records")
    except Exception as exc:
        logger.error("OptionExpirations query failed for %s: %s", symbol, exc)
        return []


def resolve_optimal_expirations(expirations: List[Dict[str, Any]]) -> List[str]:
    """PAY-24 / PAY-35 / PAY-47: 3-Tenor Bracketing Engine."""
    if not expirations:
        return []

    sorted_expiries = sorted(expirations, key=lambda x: x.get("daysToExpiration", 9999))
    eligible = [e for e in sorted_expiries if e.get("daysToExpiration", 0) >= 4]

    if not eligible:
        return []

    front_exp = eligible[0]
    sub_30 = [e for e in eligible if e.get("daysToExpiration", 0) <= 30]
    sup_30 = [e for e in eligible if e.get("daysToExpiration", 0) > 30]

    selected_set = set()
    selected_list = []

    for candidate in [
        front_exp,
        sub_30[-1] if sub_30 else None,
        sup_30[0] if sup_30 else None,
    ]:
        if candidate is not None:
            exp_date = candidate.get("expirationDate")
            if exp_date and exp_date not in selected_set:
                selected_set.add(exp_date)
                selected_list.append(exp_date)

    return selected_list


def extract_in_memory_option_chains(
    client: SchwabClient,
    symbol: str,
    target_expirations: List[str],
    strike_count: int = 14,
    strategy: str = "SINGLE",
    include_underlying_quote: bool = True,
) -> Tuple[Optional[float], Optional[float], List[Dict[str, Any]], Dict[str, int]]:
    """Pulls targeted strikes for selected expirations in-memory with rejection telemetry."""
    vol_30d = None
    underlying_price = None
    records: List[Dict[str, Any]] = []

    telemetry: Dict[str, int] = {
        "rejected_zero_strike_count": 0,
        "rejected_expired_contract_count": 0,
        "rejected_negative_mark_count": 0,
        "rejected_negative_price_count": 0,
    }

    if not target_expirations:
        return None, None, [], telemetry

    for exp_date in target_expirations:
        try:
            raw_chain = client.get_option_chain(
                symbol=symbol,
                contract_type="ALL",
                strike_count=strike_count,
                include_underlying_quote=include_underlying_quote,
                strategy=strategy,
                from_date=exp_date,
                to_date=exp_date,
            )

            if vol_30d is None:
                vol_30d = _clean_numeric_val(raw_chain.get("volatility"))

            if underlying_price is None:
                underlying_price = _clean_numeric_val(raw_chain.get("underlyingPrice"))

            def parse_map(exp_map: Dict[str, Any], flag: str):
                if not isinstance(exp_map, dict):
                    return
                for exp_key, strike_map in exp_map.items():
                    dte = int(exp_key.split(":")[1]) if ":" in exp_key else None
                    if not isinstance(strike_map, dict):
                        continue
                    for _, contracts in strike_map.items():
                        if not isinstance(contracts, list):
                            continue
                        for c in contracts:
                            strike = _clean_numeric_val(c.get("strikePrice"))
                            mark = _clean_numeric_val(c.get("mark"))
                            bid = _clean_numeric_val(c.get("bid"))
                            ask = _clean_numeric_val(c.get("ask"))
                            contract_dte = c.get("daysToExpiration", dte)

                            if strike is None or strike <= 0:
                                telemetry["rejected_zero_strike_count"] += 1
                                continue
                            if contract_dte is not None and contract_dte < 0:
                                telemetry["rejected_expired_contract_count"] += 1
                                continue
                            if mark is not None and mark < 0:
                                telemetry["rejected_negative_mark_count"] += 1
                                continue
                            if (bid is not None and bid < 0) or (ask is not None and ask < 0):
                                telemetry["rejected_negative_price_count"] += 1
                                continue

                            records.append({
                                "putCallIndicator": c.get("putCallIndicator", flag),
                                "daysToExpiration": contract_dte,
                                "strikePrice": strike,
                                "bid": bid,
                                "ask": ask,
                                "mark": mark,
                                "totalVolume": _clean_numeric_val(c.get("totalVolume")) or 0.0,
                                "openInterest": _clean_numeric_val(c.get("openInterest")) or 0.0,
                                "volatility": _clean_numeric_val(c.get("volatility")),
                                "delta": _clean_numeric_val(c.get("delta")),
                            })

            parse_map(raw_chain.get("callExpDateMap", {}), "CALL")
            parse_map(raw_chain.get("putExpDateMap", {}), "PUT")

        except Exception as exc:
            logger.error("OptionChains extraction failed for %s on %s: %s", symbol, exp_date, exc)
            continue

    return vol_30d, underlying_price, records, telemetry


def evaluate_5_state_return_metric(
    raw_val: Optional[float],
    m_net: Optional[float],
    m_op: Optional[float],
    denominator_valid: bool = True,
    denominator_err_state: str = "VENDOR_UNAVAILABLE_MISSING_DENOMINATOR",
) -> Tuple[Optional[float], str]:
    """PAY-46 / PAY-51 / PAY-52 / PAY-53: 5-State Margin Decision Table with Denominator Gate."""
    if not denominator_valid:
        return None, denominator_err_state

    if raw_val is None:
        return None, "VENDOR_UNAVAILABLE"

    if raw_val != 0.0:
        return raw_val, "AS_REPORTED"

    if m_net is not None and m_net < 0.0:
        return None, "VENDOR_UNAVAILABLE_NEGATIVE_EARNINGS"
    if m_net is not None and m_net > 0.0:
        return 0.0, STATE_AS_REPORTED_POSITIVE_MARGIN
    if m_net is None and m_op is not None and m_op < 0.0:
        return None, "VENDOR_UNAVAILABLE_NEGATIVE_OPERATING_INCOME"
    if m_net is None and m_op is not None and m_op >= 0.0:
        return None, STATE_ZERO_NET_MARGIN_MISSING
    return None, "VENDOR_UNAVAILABLE_MISSING_PROFITABILITY_DATA"


def extract_strict_underlying_data(
    client: SchwabClient, symbol: str, tz: Optional[ZoneInfo] = None
) -> Dict[str, Any]:
    """Extracts quotes, fundamentals, locate, and liquidity metrics with defensive unwrap logic."""
    raw_payload = client.get_quote(symbol=symbol, fields="quote,fundamental,reference")

    # Step 1: Form A Non-Falsy Payload Unwrapping with Double-Nesting Resolution
    clean_sym = symbol.strip().upper()
    candidate = None
    if isinstance(raw_payload, dict):
        for key in (clean_sym, symbol, symbol.lower()):
            v = raw_payload.get(key)
            if isinstance(v, dict) and v:
                candidate = v
                break
        if candidate is None:
            candidate = raw_payload

        # Secondary resolution for double-nested batch structures: {"SPCX": {"SPCX": {...}}}
        if isinstance(candidate, dict):
            if clean_sym in candidate and isinstance(candidate[clean_sym], dict) and candidate[clean_sym]:
                candidate = candidate[clean_sym]
            elif symbol in candidate and isinstance(candidate[symbol], dict) and candidate[symbol]:
                candidate = candidate[symbol]

    payload = candidate if isinstance(candidate, dict) else {}

    raw_quote = payload.get("quote", {})
    raw_fund = payload.get("fundamental", {})
    raw_ref = payload.get("reference", {})

    last_price = _clean_numeric_val(raw_quote.get("lastPrice") or raw_quote.get("closePrice"))
    close_price = _clean_numeric_val(raw_quote.get("closePrice") or raw_quote.get("lastPrice"))

    # Step 2: Margins Extraction & PAY-76 Suspect Gate
    net_margin = _clean_numeric_val(
        raw_fund.get("netProfitMarginTTM")
        or raw_fund.get("netProfitMargin")
        or raw_fund.get("netMargin")
    )
    op_margin = _clean_numeric_val(
        raw_fund.get("operatingMarginTTM")
        or raw_fund.get("operatingMargin")
        or raw_fund.get("opMargin")
    )
    gross_margin = _clean_numeric_val(
        raw_fund.get("grossMarginTTM")
        or raw_fund.get("grossMargin")
    )

    if net_margin is not None and op_margin is not None:
        margin_suspect = (net_margin == op_margin)
        margin_suspect_reason = "vendor_net_and_operating_margins_identical" if margin_suspect else None
        margin_suspect_state = "EVALUATED"
    else:
        margin_suspect = None
        margin_suspect_reason = "cannot_evaluate_pairwise_margins_missing"
        margin_suspect_state = "VENDOR_UNAVAILABLE_INPUTS_ABSENT"

    # Step 3: Returns & Denominators Sanity Checks (PAY-53)
    total_equity = _clean_numeric_val(
        raw_fund.get("totalStockholdersEquity")
        or raw_fund.get("stockholdersEquity")
    )
    total_assets = _clean_numeric_val(raw_fund.get("totalAssets"))
    equity_valid = total_equity is None or total_equity > 0.0
    assets_valid = total_assets is None or total_assets > 0.0

    roe_val, roe_state = evaluate_5_state_return_metric(
        _clean_numeric_val(raw_fund.get("returnOnEquity") or raw_fund.get("roe")),
        net_margin,
        op_margin,
        denominator_valid=equity_valid,
        denominator_err_state="VENDOR_UNAVAILABLE_NEGATIVE_OR_MISSING_EQUITY",
    )

    roa_val, roa_state = evaluate_5_state_return_metric(
        _clean_numeric_val(raw_fund.get("returnOnAssets") or raw_fund.get("roa")),
        net_margin,
        op_margin,
        denominator_valid=assets_valid,
        denominator_err_state="VENDOR_UNAVAILABLE_MISSING_ASSET_BASE",
    )

    # Multiples & Technical Ratios
    beta_raw = _clean_numeric_val(raw_fund.get("beta"))
    beta_val, beta_state = (None, "VENDOR_UNAVAILABLE") if (beta_raw is None or beta_raw == 0.0) else (beta_raw, "AS_REPORTED")

    peg_raw = _clean_numeric_val(raw_fund.get("pegRatio"))
    peg_val, peg_state = (None, "VENDOR_UNAVAILABLE") if (peg_raw is None or peg_raw == 0.0) else (peg_raw, "AS_REPORTED")

    pcf_raw = _clean_numeric_val(raw_fund.get("pcfRatio") or raw_fund.get("priceToCashFlow"))
    pcf_val, pcf_state = (None, "VENDOR_UNAVAILABLE") if (pcf_raw is None or pcf_raw == 0.0) else (pcf_raw, "AS_REPORTED")

    pb_ratio = _clean_numeric_val(raw_fund.get("pbRatio") or raw_fund.get("priceToBook"))
    total_dte = _clean_numeric_val(raw_fund.get("totalDebtToEquity") or raw_fund.get("totalDebtToCapital"))

    rev_raw = _clean_numeric_val(raw_fund.get("revChangeYear") or raw_fund.get("revenueChangeYear"))
    rev_val, rev_state = (0.0, "VENDOR_ZERO_UNVERIFIED") if rev_raw == 0.0 else (rev_raw, "AS_REPORTED")

    # Step 4: Defensive Dividend Normalization (REF-01 / PAY-69 / PAY-71 / PAY-77)
    div_yield_raw = _clean_numeric_val(raw_fund.get("dividendYield") or raw_fund.get("divYield"))
    div_amount = _clean_numeric_val(raw_fund.get("dividendAmount") or raw_fund.get("divAmount"))
    div_freq = _clean_numeric_val(raw_fund.get("dividendFreq") or raw_fund.get("divFreq"))

    div_yield = div_yield_raw
    div_basis = "VENDOR_UNVERIFIED"
    div_state = "AS_REPORTED"
    div_freq_source = "VENDOR" if (div_freq in ALLOWED_DIV_FREQS) else "UNKNOWN"

    if div_yield_raw is not None and div_yield_raw > 0.0:
        div_basis = "DIRECT_CONFIRMED"
        div_state = "CONFIRMED"
    elif div_yield_raw == 0.0 or div_amount == 0.0:
        div_basis = "AS_REPORTED_ZERO_NON_PAYER"
        div_state = "AS_REPORTED_ZERO_NON_PAYER"

    # Step 5: Shares Outstanding & Foreign ADR EPS Defense (PAY-57 / PAY-73)
    shares_raw = _clean_numeric_val(raw_fund.get("sharesOutstanding"))
    is_foreign_adr = shares_raw is None or shares_raw <= 0.0
    shares_val = None if is_foreign_adr else shares_raw
    shares_state = STATE_UNAVAILABLE_FOREIGN_ADR if is_foreign_adr else "CONFIRMED"

    eps_raw = _clean_numeric_val(raw_fund.get("eps") or raw_fund.get("epsTTM"))
    eps_val = eps_raw
    eps_state = "AS_REPORTED"

    if eps_raw == 0.0 or (eps_raw is not None and eps_raw < 0.01):
        if net_margin is not None and net_margin > 0.0:
            eps_val = None
            eps_state = STATE_UNAVAILABLE_EPS_POSITIVE_MARGIN
        elif net_margin is not None and net_margin < 0.0:
            eps_val = None
            eps_state = "VENDOR_UNAVAILABLE_NEGATIVE_EARNINGS"
        elif is_foreign_adr:
            eps_val = None
            eps_state = "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED"
    elif eps_raw is None:
        eps_state = "VENDOR_UNAVAILABLE"

    # Step 6: Market Cap Extraction (PAY-61 / PAY-70)
    raw_mcap = _clean_numeric_val(
        raw_fund.get("marketCap")
        or raw_fund.get("marketCapitalization")
        or payload.get("marketCap")
        or raw_quote.get("marketCap")
    )

    # Step 7: Fail-Safe Short Locate Logic (SAFE-01) with Partial Telemetry
    is_shortable = raw_ref.get("isShortable")
    is_htb = raw_ref.get("isHardToBorrow")
    htb_rate = _clean_numeric_val(raw_ref.get("htbRate"))

    if is_shortable is None and is_htb is None and htb_rate is None:
        short_locate_dict = {
            "state": "UNKNOWN",
            "reason": "missing_broker_reference_keys",
        }
    else:
        is_full = all(v is not None for v in [is_shortable, is_htb, htb_rate])
        short_locate_dict = {
            "state": "FULL_PASSTHROUGH" if is_full else "PARTIAL_PASSTHROUGH",
            "isShortable": is_shortable,
            "isHardToBorrow": is_htb,
            "htbRate": htb_rate,
        }
        if not is_full:
            missing_keys = [k for k, v in [("isShortable", is_shortable), ("isHardToBorrow", is_htb), ("htbRate", htb_rate)] if v is None]
            short_locate_dict["short_locate_partial_reason"] = f"missing_{'_'.join(missing_keys)}"

    # Step 8: Dynamic Liquidity State Machine & Semantic Volume Key Extraction (PAY-78)
    bid_raw = _clean_numeric_val(raw_quote.get("bidPrice"))
    ask_raw = _clean_numeric_val(raw_quote.get("askPrice"))
    bid_size = _clean_numeric_val(raw_quote.get("bidSize"))
    ask_size = _clean_numeric_val(raw_quote.get("askSize"))
    tot_vol = _clean_numeric_val(raw_quote.get("totalVolume"))

    liq_present = sum(1 for v in [bid_raw, ask_raw, bid_size, ask_size, tot_vol] if v is not None)
    liq_state = "FULL_PASSTHROUGH" if liq_present == 5 else ("PARTIAL_PASSTHROUGH" if liq_present > 0 else "UNKNOWN")

    # Direct key resolution anchored to observed schema
    vol10 = _clean_numeric_val(raw_fund.get("avg10DaysVolume"))
    vol1y = _clean_numeric_val(raw_fund.get("avg1YearVolume"))

    vol10_state = (
        "VENDOR_SUSPECT_ZERO" if (vol10 is not None and vol10 <= 0 and tot_vol and tot_vol > LIQUIDITY_SUSPECT_VOLUME_THRESHOLD)
        else ("AS_REPORTED" if vol10 is not None else "VENDOR_UNAVAILABLE")
    )
    vol1y_state = (
        "VENDOR_SUSPECT_ZERO" if (vol1y is not None and vol1y <= 0 and tot_vol and tot_vol > LIQUIDITY_SUSPECT_VOLUME_THRESHOLD)
        else ("AS_REPORTED" if vol1y is not None else "VENDOR_UNAVAILABLE")
    )

    liquidity_dict = {
        "state": liq_state,
        "bidPrice": f"${bid_raw:,.2f}" if bid_raw is not None else None,
        "askPrice": f"${ask_raw:,.2f}" if ask_raw is not None else None,
        "bidSize": bid_size,
        "askSize": ask_size,
        "totalVolume": tot_vol,
        "vol10DayAvg": vol10,
        "vol10DayAvg_state": vol10_state,
        "vol3MonthAvg": None,
        "vol3MonthAvg_state": "VENDOR_FIELD_NOT_PROVIDED",
        "vol1YearAvg": vol1y,
        "vol1YearAvg_state": vol1y_state,
    }

    quote_epoch = raw_quote.get("quoteTime")
    quote_iso = None
    if quote_epoch and not pd.isna(quote_epoch) and quote_epoch > 0:
        zone = tz or ZoneInfo("America/New_York")
        quote_iso = datetime.fromtimestamp(quote_epoch / 1000.0, tz=timezone.utc).astimezone(zone).isoformat()

    # Diagnostic Boundary Logging
    if net_margin is None or raw_mcap is None or pcf_raw is None:
        logger.warning(
            "[%s] Key fundamental extraction null. Observed fundamental keys: %s",
            symbol,
            list(raw_fund.keys()) if isinstance(raw_fund, dict) else [],
        )

    print(f"\n[DIAGNOSTIC TRACE - {symbol}]")
    print(f"  locate: {json.dumps(short_locate_dict)}")
    print(f"  liquidity state: {liquidity_dict['state']} (present {liq_present}/5)")
    print(f"  marketCap: {raw_mcap} | netMargin: {net_margin} | pcfRatio: {pcf_raw}")

    return {
        "phase_0_grounding": {
            "symbol": symbol,
            "lastPrice": f"${last_price:,.2f}" if last_price is not None else None,
            "closePrice": f"${close_price:,.2f}" if close_price is not None else None,
            "quoteTime_ISO_ET": quote_iso,
            "market_isOpen": raw_quote.get("isMarketOpen", True),
        },
        "step_1_fundamentals": {
            "beta": beta_val,
            "beta_state": beta_state,
            "peRatio": _clean_numeric_val(raw_fund.get("peRatio")),
            "pegRatio": peg_val,
            "pegRatio_state": peg_state,
            "pcfRatio": pcf_val,
            "pcfRatio_state": pcf_state,
            "pbRatio": pb_ratio,
            "totalDebtToEquity": total_dte,
            "totalDebtToEquity_basis": "VENDOR_RAW_UNVERIFIED",
            "grossMarginTTM": gross_margin,
            "netProfitMarginTTM": net_margin,
            "operatingMarginTTM": op_margin,
            "margin_fields_suspect": margin_suspect,
            "margin_fields_suspect_reason": margin_suspect_reason,
            "margin_fields_suspect_state": margin_suspect_state,
            "returnOnEquity": roe_val,
            "returnOnEquity_state": roe_state,
            "returnOnAssets": roa_val,
            "returnOnAssets_state": roa_state,
            "eps": eps_val,
            "eps_state": eps_state,
            "revChangeYear": rev_val,
            "revChangeYear_state": rev_state,
            "divYield": div_yield,
            "divYield_basis": div_basis,
            "divYield_raw": div_yield_raw,
            "divYield_state": div_state,
            "divAmount": f"${div_amount:,.2f}" if div_amount is not None else "$0.00",
            "divFreq": div_freq if (div_freq in ALLOWED_DIV_FREQS) else 0.0,
            "div_freq_source": div_freq_source,
            "sharesOutstanding": shares_val,
            "shares_outstanding_state": shares_state,
            "marketCap": raw_mcap,
            "marketCap_unit": "VENDOR_RAW_UNVERIFIED",
        },
        "short_locate_status": short_locate_dict,
        "step_8_and_9_liquidity_and_sizing": liquidity_dict,
        "step_3_and_7_derivatives": {
            "surface_parameters": {
                "underlyingPrice": last_price or close_price
            },
            "short_locate_status": short_locate_dict,
            "options_extraction_telemetry": {
                "rejected_zero_strike_count": 0,
                "rejected_expired_contract_count": 0,
                "rejected_negative_mark_count": 0,
                "rejected_negative_price_count": 0,
            },
        },
    }