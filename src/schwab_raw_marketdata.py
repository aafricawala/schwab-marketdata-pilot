# src/schwab_raw_marketdata.py
from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
from schwab_client import SchwabClient

logger = logging.getLogger("schwab_raw_marketdata")
logger.addHandler(logging.NullHandler())

REASON_DTE_BELOW_MINIMUM_4 = "DTE_BELOW_MINIMUM_4"
REASON_MARGINS_IDENTICAL = "vendor_net_and_operating_margins_identical"
STATE_AS_REPORTED_POSITIVE_MARGIN = "AS_REPORTED_ZERO_WITH_POSITIVE_MARGIN"
STATE_ZERO_NET_MARGIN_MISSING = "VENDOR_ZERO_UNCORROBORATED_NET_MARGIN_MISSING"

ALLOWED_DIV_FREQS: Set[float] = {1.0, 2.0, 4.0, 12.0}
LIQUIDITY_SUSPECT_VOLUME_THRESHOLD = 1_000_000.0

KNOWN_DIRECT_FOREIGN_ISSUERS: Set[str] = {"ZIM", "SE", "GRAB", "CPNG", "BABA", "PDD"}
KNOWN_ETN_OR_FUND_SYMBOLS: Set[str] = {"USOI", "SPCX"}


def _clean_numeric_val(val: Any) -> Optional[float]:
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        return None if (math.isnan(val) or math.isinf(val)) else float(val)
    if isinstance(val, str):
        cleaned = re.sub(r"[$,% ]", "", val.strip())
        if not cleaned or cleaned.lower() in ("nan", "none", "null"):
            return None
        try:
            parsed = float(cleaned)
            return None if (math.isnan(parsed) or math.isinf(parsed)) else parsed
        except (ValueError, TypeError):
            return None
    return None


def _resolve_field(container: Dict[str, Any], *aliases: str) -> Any:
    for alias in aliases:
        if alias in container and container[alias] is not None:
            return container[alias]
    return None


def extract_market_open_status(client: SchwabClient, *args: Any, **kwargs: Any) -> Optional[bool]:
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
                    return bool(raw_hours.get("isOpen", False))
                eq_market = raw_hours.get("equity", {}).get("EQ", {})
                if "isOpen" in eq_market:
                    return bool(eq_market.get("isOpen", False))
    except Exception as exc:
        logger.warning("MarketHours retrieval skipped: %s", exc)
    return None


def extract_in_memory_price_history(
    client: SchwabClient,
    symbol: str,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    cfg = config or {}
    clean_sym = symbol.strip().upper()
    try:
        raw = client.get_price_history(
            symbol=clean_sym,
            period_type=cfg.get("HISTORICAL_PERIOD_TYPE", cfg.get("periodType", "year")),
            period=cfg.get("HISTORICAL_PERIOD", cfg.get("period", 1)),
            frequency_type=cfg.get("HISTORICAL_FREQUENCY_TYPE", cfg.get("frequencyType", "daily")),
            frequency=cfg.get("HISTORICAL_FREQUENCY", cfg.get("frequency", 1)),
            need_extended_hours=cfg.get("HISTORICAL_NEED_EXTENDED_HOURS", cfg.get("need_extended_hours", False)),
        )
        candles = raw.get("candles", []) if isinstance(raw, dict) else []
        if not candles:
            return []

        df = pd.DataFrame(candles)
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                if df[col].dtype == object:
                    df[col] = (
                        df[col]
                        .astype(str)
                        .str.replace(r"[$,% ]", "", regex=True)
                        .str.strip()
                    )
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "datetime" in df.columns:
            df["datetime"] = pd.to_numeric(df["datetime"], errors="coerce")
            df = df.sort_values(by="datetime", ascending=True).drop_duplicates(subset=["datetime"])

        cols = ["datetime", "open", "high", "low", "close", "volume"]
        existing = [c for c in cols if c in df.columns]
        df_clean = df[existing].dropna(subset=["open", "high", "low", "close"])
        df_clean = df_clean[
            (df_clean["open"] > 0)
            & (df_clean["high"] > 0)
            & (df_clean["low"] > 0)
            & (df_clean["close"] > 0)
        ]
        return df_clean.to_dict(orient="records")
    except Exception as exc:
        logger.error("PriceHistory fetch failed for %s: %s", clean_sym, exc)
        return []


def extract_in_memory_option_expirations(client: SchwabClient, symbol: str) -> List[Dict[str, Any]]:
    clean_sym = symbol.strip().upper()
    try:
        payload = client.get_option_expirations(clean_sym)
        exp_list = payload.get("expirationList", [])
        if not exp_list:
            return []
        df = pd.DataFrame(exp_list)
        cols = ["expirationDate", "daysToExpiration"]
        existing = [c for c in cols if c in df.columns]
        return df[existing].sort_values("daysToExpiration").to_dict(orient="records")
    except Exception as exc:
        logger.error("OptionExpirations query failed for %s: %s", clean_sym, exc)
        return []


def resolve_optimal_expirations(expirations: List[Dict[str, Any]]) -> List[str]:
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
    clean_sym = symbol.strip().upper()
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
                symbol=clean_sym,
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
            logger.error("OptionChains extraction failed for %s on %s: %s", clean_sym, exp_date, exc)
            continue

    return vol_30d, underlying_price, records, telemetry


def evaluate_5_state_return_metric(
    raw_val: Optional[float],
    m_net: Optional[float],
    m_op: Optional[float],
    denominator_valid: bool = True,
    denominator_err_state: str = "VENDOR_UNAVAILABLE_MISSING_DENOMINATOR",
) -> Tuple[Optional[float], str]:
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
    clean_sym = symbol.strip().upper()
    raw_payload = client.get_quote(symbol=clean_sym, fields="quote,fundamental,reference")

    candidate = None
    if isinstance(raw_payload, dict):
        for key in (clean_sym, symbol, symbol.lower()):
            v = raw_payload.get(key)
            if isinstance(v, dict) and v:
                candidate = v
                break
        if candidate is None:
            candidate = raw_payload

        if isinstance(candidate, dict):
            if clean_sym in candidate and isinstance(candidate[clean_sym], dict) and candidate[clean_sym]:
                candidate = candidate[clean_sym]
            elif symbol in candidate and isinstance(candidate[symbol], dict) and candidate[symbol]:
                candidate = candidate[symbol]

    payload = candidate if isinstance(candidate, dict) else {}

    raw_quote = payload.get("quote", {})
    raw_fund = payload.get("fundamental", {})
    raw_ref = payload.get("reference", {})

    net_margin = _clean_numeric_val(_resolve_field(raw_fund, "netProfitMarginTTM", "netProfitMargin", "netMargin"))
    op_margin = _clean_numeric_val(_resolve_field(raw_fund, "operatingMarginTTM", "operatingMargin", "opMargin"))
    gross_margin = _clean_numeric_val(_resolve_field(raw_fund, "grossMarginTTM", "grossMargin"))
    total_assets = _clean_numeric_val(_resolve_field(raw_fund, "totalAssets"))
    total_equity = _clean_numeric_val(_resolve_field(raw_fund, "totalStockholdersEquity", "stockholdersEquity"))

    asset_type = str(raw_ref.get("assetType", "")).upper()
    description = str(raw_ref.get("description", "")).upper()

    is_etn_or_fund = (
        clean_sym in KNOWN_ETN_OR_FUND_SYMBOLS
        or asset_type in ("ETF", "ETN", "MUTUAL_FUND", "COLLECTIVE_INVESTMENT")
        or "ETN" in description
        or "COMMODITY INDEX" in description
    )

    is_foreign_country = str(raw_ref.get("country", "")).upper() not in ("", "US", "USA")
    is_adr = "ADR" in description or is_foreign_country
    is_direct_foreign = clean_sym in KNOWN_DIRECT_FOREIGN_ISSUERS

    last_price = _clean_numeric_val(_resolve_field(raw_quote, "lastPrice", "closePrice"))
    close_price = _clean_numeric_val(_resolve_field(raw_quote, "closePrice", "lastPrice"))
    spot_ref = last_price or close_price

    margin_suspect = False
    margin_suspect_reason = None
    if net_margin is not None and op_margin is not None:
        if net_margin == op_margin:
            margin_suspect = True
            margin_suspect_reason = REASON_MARGINS_IDENTICAL

    equity_valid = total_equity is None or total_equity > 0.0
    assets_valid = total_assets is None or total_assets > 0.0

    roe_val, roe_state = evaluate_5_state_return_metric(
        _clean_numeric_val(_resolve_field(raw_fund, "returnOnEquity", "roe")),
        net_margin,
        op_margin,
        denominator_valid=equity_valid,
        denominator_err_state="VENDOR_UNAVAILABLE_NEGATIVE_OR_MISSING_EQUITY",
    )

    roa_val, roa_state = evaluate_5_state_return_metric(
        _clean_numeric_val(_resolve_field(raw_fund, "returnOnAssets", "roa")),
        net_margin,
        op_margin,
        denominator_valid=assets_valid,
        denominator_err_state="VENDOR_UNAVAILABLE_MISSING_ASSET_BASE",
    )

    beta_raw = _clean_numeric_val(_resolve_field(raw_fund, "beta"))
    beta_val, beta_state = (None, "VENDOR_UNAVAILABLE") if (beta_raw is None or beta_raw == 0.0) else (beta_raw, "AS_REPORTED")

    peg_raw = _clean_numeric_val(_resolve_field(raw_fund, "pegRatio"))
    peg_val, peg_state = (None, "VENDOR_UNAVAILABLE") if (peg_raw is None or peg_raw == 0.0) else (peg_raw, "AS_REPORTED")

    pcf_raw = _clean_numeric_val(_resolve_field(raw_fund, "pcfRatio", "priceToCashFlow"))
    pcf_val, pcf_state = (None, "VENDOR_UNAVAILABLE") if (pcf_raw is None or pcf_raw == 0.0) else (pcf_raw, "AS_REPORTED")

    pb_ratio = _clean_numeric_val(_resolve_field(raw_fund, "pbRatio", "priceToBook"))
    total_dte = _clean_numeric_val(_resolve_field(raw_fund, "totalDebtToEquity", "totalDebtToCapital"))

    rev_raw = _clean_numeric_val(_resolve_field(raw_fund, "revChangeYear", "revenueChangeYear"))
    rev_val, rev_state = (0.0, "VENDOR_ZERO_UNVERIFIED") if rev_raw == 0.0 else (rev_raw, "AS_REPORTED")

    div_yield_raw = _clean_numeric_val(_resolve_field(raw_fund, "dividendYield", "divYield"))
    div_amount = _clean_numeric_val(_resolve_field(raw_fund, "dividendAmount", "divAmount", "dividendPayAmount"))
    div_freq_val = _clean_numeric_val(_resolve_field(raw_fund, "dividendFreq", "divFreq"))
    div_freq = div_freq_val if (div_freq_val is not None and div_freq_val in ALLOWED_DIV_FREQS) else 4.0

    normalized_div_yield = div_yield_raw
    div_yield_basis = "AS_REPORTED"

    if div_yield_raw is None or div_yield_raw == 0.0:
        if div_amount is None or div_amount == 0.0:
            normalized_div_yield = 0.0
            div_yield_basis = "AS_REPORTED_ZERO_NON_PAYER"
    elif spot_ref is not None and spot_ref > 0.0 and div_amount is not None:
        direct_amount_yield = (div_amount / spot_ref) * 100.0
        tol_abs = max(0.05 * div_yield_raw, (0.01 / spot_ref) * 100.0)

        if abs(direct_amount_yield - div_yield_raw) <= tol_abs:
            normalized_div_yield = round(div_yield_raw, 4)
            div_yield_basis = "ANNUAL_VENDOR_CONFIRMED"
        else:
            expected_annual_yield = (div_amount * div_freq / spot_ref) * 100.0
            if abs(expected_annual_yield - (div_yield_raw * div_freq)) <= (tol_abs * div_freq):
                normalized_div_yield = round(div_yield_raw * div_freq, 4)
                div_yield_basis = "ANNUALIZED_FROM_VENDOR_QUARTERLY"

    shares_raw = _clean_numeric_val(_resolve_field(raw_fund, "sharesOutstanding"))
    if is_etn_or_fund:
        shares_val = None
        shares_state = "UNAVAILABLE_FOR_ETN_OR_FUND"
    elif is_direct_foreign or is_adr:
        if shares_raw is not None and shares_raw > 0.0:
            shares_val = shares_raw
            shares_state = "VENDOR_PROVIDED_FOREIGN_ISSUER_UNVERIFIED"
        else:
            shares_val = None
            shares_state = "UNAVAILABLE_FOR_FOREIGN_ADR"
    elif shares_raw is not None and shares_raw > 0.0:
        shares_val = shares_raw
        shares_state = "CONFIRMED"
    else:
        shares_val = None
        shares_state = "VENDOR_UNAVAILABLE"

    eps_raw = _clean_numeric_val(_resolve_field(raw_fund, "eps", "epsTTM"))
    eps_val = eps_raw
    eps_state = "AS_REPORTED"

    if is_etn_or_fund:
        eps_val = None
        eps_state = "VENDOR_UNAVAILABLE_ETF_OR_ETN_NO_EPS"
    elif eps_raw == 0.0 or (eps_raw is not None and eps_raw < 0.01):
        if net_margin is not None and net_margin > 0.0:
            eps_val = None
            eps_state = "VENDOR_UNAVAILABLE_EPS_ZERO_WITH_POSITIVE_MARGIN"
        elif net_margin is not None and net_margin < 0.0:
            eps_val = None
            eps_state = "VENDOR_UNAVAILABLE_NEGATIVE_EARNINGS"
        elif is_adr or is_direct_foreign:
            eps_val = None
            eps_state = "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED"
    elif eps_raw is None:
        eps_state = "VENDOR_UNAVAILABLE"

    raw_mcap = _clean_numeric_val(
        _resolve_field(raw_fund, "marketCap", "marketCapitalization")
        or _resolve_field(payload, "marketCap")
        or _resolve_field(raw_quote, "marketCap")
    )

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
        if is_htb and (htb_rate == 0.0 or htb_rate is None):
            short_locate_dict["htb_rate_status"] = "HTB_FLAG_ACTIVE_RATE_PENDING_BROKER_LOCATE"

        if not is_full:
            missing_keys = [k for k, v in [("isShortable", is_shortable), ("isHardToBorrow", is_htb), ("htbRate", htb_rate)] if v is None]
            short_locate_dict["short_locate_partial_reason"] = f"missing_{'_'.join(missing_keys)}"

    bid_raw = _clean_numeric_val(raw_quote.get("bidPrice"))
    ask_raw = _clean_numeric_val(raw_quote.get("askPrice"))
    bid_size = _clean_numeric_val(raw_quote.get("bidSize"))
    ask_size = _clean_numeric_val(raw_quote.get("askSize"))
    tot_vol = _clean_numeric_val(raw_quote.get("totalVolume"))

    liq_present = sum(1 for v in [bid_raw, ask_raw, bid_size, ask_size, tot_vol] if v is not None)
    liq_state = "FULL_PASSTHROUGH" if liq_present == 5 else ("PARTIAL_PASSTHROUGH" if liq_present > 0 else "UNKNOWN")

    vol10 = _clean_numeric_val(raw_fund.get("avg10DaysVolume") or raw_fund.get("vol10DayAvg"))
    vol3m = _clean_numeric_val(raw_fund.get("vol3MonthAvg"))
    vol1y = _clean_numeric_val(raw_fund.get("avg1YearVolume") or raw_fund.get("vol1YearAvg"))

    vol10_state = (
        "VENDOR_SUSPECT_ZERO" if (vol10 is not None and vol10 <= 0 and tot_vol and tot_vol > LIQUIDITY_SUSPECT_VOLUME_THRESHOLD)
        else ("AS_REPORTED" if vol10 is not None else "VENDOR_UNAVAILABLE")
    )
    vol3m_state = "VENDOR_FIELD_NOT_PROVIDED" if vol3m is None else "AS_REPORTED"
    vol1y_state = "AS_REPORTED" if vol1y is not None else "VENDOR_UNAVAILABLE"

    liquidity_dict = {
        "state": liq_state,
        "bidPrice": f"${bid_raw:,.2f}" if bid_raw is not None else None,
        "askPrice": f"${ask_raw:,.2f}" if ask_raw is not None else None,
        "bidSize": bid_size,
        "askSize": ask_size,
        "totalVolume": tot_vol,
        "vol10DayAvg": vol10,
        "vol10DayAvg_state": vol10_state,
        "vol3MonthAvg": vol3m,
        "vol3MonthAvg_state": vol3m_state,
        "vol1YearAvg": vol1y,
        "vol1YearAvg_state": vol1y_state,
    }

    quote_epoch = raw_quote.get("quoteTime")
    quote_iso = None
    if quote_epoch and not pd.isna(quote_epoch) and quote_epoch > 0:
        zone = tz or ZoneInfo("America/New_York")
        quote_iso = datetime.fromtimestamp(quote_epoch / 1000.0, tz=timezone.utc).astimezone(zone).isoformat()

    return {
        "metadata": {
            "symbol": clean_sym,
            "extraction_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        },
        "phase_0_grounding": {
            "symbol": clean_sym,
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
            "margin_fields_suspect_state": (
                "VENDOR_UNAVAILABLE_INPUTS_ABSENT"
                if (net_margin is None and op_margin is None)
                else "AS_EVALUATED"
            ),
            "returnOnEquity": roe_val,
            "returnOnEquity_state": roe_state,
            "returnOnAssets": roa_val,
            "returnOnAssets_state": roa_state,
            "eps": eps_val,
            "eps_state": eps_state,
            "revChangeYear": rev_val,
            "revChangeYear_state": rev_state,
            "divYield": normalized_div_yield,
            "divYield_basis": div_yield_basis,
            "divYield_raw": div_yield_raw,
            "divAmount": f"${div_amount:,.2f}" if div_amount is not None else "$0.00",
            "div_amount_basis": "ANNUAL",
            "divFreq": div_freq_val if (div_freq_val in ALLOWED_DIV_FREQS) else 0.0,
            "sharesOutstanding": shares_val,
            "shares_outstanding_state": shares_state,
            "marketCap": raw_mcap,
            "marketCap_unit": "VENDOR_RAW_UNVERIFIED",
        },
        "short_locate_status": short_locate_dict,
        "step_3_short_reference": short_locate_dict,
        "step_8_and_9_liquidity_and_sizing": liquidity_dict,
        "step_8_liquidity_sizing": liquidity_dict,
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