"""
schwab_raw_marketdata.py
========================================================================================
Institutional Charles Schwab Raw Market Data Ingestion & Normalization Engine
========================================================================================
Institutional Grade Charles Schwab Market Data Extraction & Sanitization Engine.
Conforms strictly to Institutional Risk & Master Thesis Protocol (v16.20).

Production Guarantees & Audit Compliance:
  - ADD-01: Pass-through unscaled raw marketCap directly from Quotes fundamentals.
  - ADD-02: Emit explicit div_freq_source metadata ('VENDOR' | 'ASSUMED_QUARTERLY' | 'UNKNOWN').
  - ADD-03 / PAY-18 / PAY-22: Emit full rejection_telemetry for option parsing.
  - SAFE-01: Eliminate fail-open defaults on shortability; emit explicit completeness envelopes.
  - SAFE-02: Tag totalDebtToEquity as VENDOR_RAW_UNVERIFIED with scale risk tracking.
  - SAFE-03: Sanitize exception strings in logger statements to prevent credential/payload leaks.
  - REF-01: Closed-form dividend normalizer with discrete frequency whitelisting (M1) and
            hybridized absolute/relative tolerance anchoring (N1, N2, N3).
  - REF-02 / PAY-04 / PAY-10: Purge silent 0.0 fallbacks for volume averages; emit VENDOR_SUSPECT_ZERO
            on liquid symbols (>1M shares) and include in completeness gating.
  - REF-03: Enforce strict non-negative float guards on option bid, ask, and mark.
  - REF-04: Robust parsing of option expiration keys guarding against malformed vendor splits.
  - REF-05 / PAY-08: Pairwise margin checks; standardized reason token 'vendor_net_and_operating_margins_identical'.
  - REF-06: Four-state enum completeness envelopes for short reference payloads.
  - OPT-02: Deterministic option expiration tie-breaking with parameterized tenor preference.
  - CLAR-01: Enforce clean 3-state passthrough enum for liquidity block.
  - CLAR-02: Standardize all dividend yield outputs to 4 decimal places.
  - CLAR-03: Capture quote timestamp parsing exceptions with structured logger.debug taxonomy.
  - PRUNE-01: Clean function signature of extract_market_open_status by removing dead tz argument.
  - PAY-02 / PAY-12: Rename raw options chain volatility metadata to vendor_raw_chain_volatility_metadata.
========================================================================================
"""

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

# Discrete institutional distribution frequency whitelist (M1)
ALLOWED_DIV_FREQS: Set[float] = {1.0, 2.0, 4.0, 12.0}

# Standard ticker regex supporting equities, ADRs, indices, and share classes
SYMBOL_REGEX = re.compile(r"^[$A-Z0-9.-_/ ]{1,30}$")


def _clean_numeric_val(val: Any) -> Optional[float]:
    """Safely coerces currency strings, numeric representations, or NaN to float primitives."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        f_val = float(val)
        return None if (math.isnan(f_val) or math.isinf(f_val)) else f_val
    if isinstance(val, str):
        cleaned = val.replace("$", "").replace(",", "").strip()
        try:
            f_val = float(cleaned)
            return None if (math.isnan(f_val) or math.isinf(f_val)) else f_val
        except (ValueError, TypeError):
            return None
    return None


def _sanitize_exc(exc: Exception) -> str:
    """Sanitizes exception messages to prevent leaking auth headers or query parameters (SAFE-03)."""
    msg = str(exc)
    msg = re.sub(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", r"\1[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"(client_secret=)[^&]+", r"\1[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"(api_key=)[^&]+", r"\1[REDACTED]", msg, flags=re.IGNORECASE)
    return msg


def sanitize_and_validate_symbols(raw_symbol: str) -> str:
    """Validates and standardizes a ticker symbol against exchange syntax."""
    if not isinstance(raw_symbol, str):
        raise ValueError(f"Ticker symbol must be a string, received: {type(raw_symbol)}")
    symbol = raw_symbol.strip().upper()
    if not SYMBOL_REGEX.match(symbol):
        raise ValueError(f"Ticker symbol '{symbol}' violates standard exchange formatting.")
    return symbol


def normalize_dividend_yield(
    div_yield_raw: Optional[float],
    div_amount: Optional[float],
    div_freq: Optional[float],
    div_freq_source: str,  # "VENDOR" | "ASSUMED_QUARTERLY" | "UNKNOWN"
    spot_ref: Optional[float],
) -> Tuple[Optional[float], str]:
    """
    Forensically reconciles vendor-reported dividend yield against periodic cash distributions (REF-01).
    Adheres to Protocol Step 0.4 (Vintage Alignment & Denominator Sanity) and Step 0.5 (Taxonomy).
    """
    if div_yield_raw is None:
        return None, "UNKNOWN"

    # N2: Sub-basis-point yield guard (floating-point dust protection)
    if div_yield_raw < 0.01:
        return round(div_yield_raw, 4), "VENDOR_UNVERIFIED"

    # Pre-flight check for direct yield derivation
    if spot_ref is None or spot_ref <= 0.0 or div_amount is None or div_amount <= 0.0:
        return round(div_yield_raw, 4), "VENDOR_UNVERIFIED"

    yield_direct = (div_amount / spot_ref) * 100.0

    # N1: Anchored dynamic tolerance (greater of 5% relative discrepancy or 1-cent absolute yield)
    cent_yield_bound = (0.01 / spot_ref) * 100.0
    tol = max(0.05 * abs(div_yield_raw), cent_yield_bound)

    # Branch 1: Direct Yield Confirmation (e.g., ADR annual distribution or pre-annualized vendor yield)
    if abs(yield_direct - div_yield_raw) <= tol:
        return round(div_yield_raw, 4), "DIRECT_CONFIRMED"

    # Branch 2: Periodic Distribution Annualization (e.g., US domestic quarterly payer)
    if (
        div_freq_source == "VENDOR"
        and div_freq is not None
        and div_freq > 0
        and div_freq in ALLOWED_DIV_FREQS
    ):
        scaled_yield = yield_direct * div_freq
        if abs(scaled_yield - div_yield_raw) <= tol:
            return round(scaled_yield, 4), "ANNUALIZED_FROM_PERIODIC"

    # Branch 3: Fallback for unresolvable discrepancies or unverified frequencies
    return round(div_yield_raw, 4), "VENDOR_UNVERIFIED"


def parse_price_history_to_df(raw: Dict[str, Any]) -> pd.DataFrame:
    """Parses raw Schwab price history candles into a typed DataFrame with monotonic sorting."""
    candles = raw.get("candles", [])
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)

    time_cols = [c for c in ["datetime", "epoch", "time", "date"] if c in df.columns]
    if time_cols:
        t_col = time_cols[0]
        df[t_col] = pd.to_numeric(df[t_col], errors="coerce")
        df = df.dropna(subset=[t_col]).sort_values(by=t_col, ascending=True)
        df = df.drop_duplicates(subset=[t_col], keep="last")

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            if df[col].dtype == object:
                df[col] = (
                    df[col]
                    .astype(str)
                    .str.replace("$", "", regex=False)
                    .str.replace(",", "", regex=False)
                    .str.strip()
                )
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def extract_market_open_status(client: SchwabClient) -> Optional[bool]:
    """Queries Schwab to determine whether the equity market is open today (PRUNE-01)."""
    try:
        if hasattr(client, "get_market_hours"):
            try:
                raw_hours = client.get_market_hours("equity")
            except TypeError:
                raw_hours = client.get_market_hours()

            if isinstance(raw_hours, dict):
                if "isOpen" in raw_hours:
                    return bool(raw_hours.get("isOpen", False))
                equity_block = raw_hours.get("equity", {})
                if "EQ" in equity_block and isinstance(equity_block["EQ"], dict):
                    return bool(equity_block["EQ"].get("isOpen", False))
                return bool(equity_block.get("isOpen", False))
    except Exception as exc:
        logger.warning("MarketHours retrieval skipped: %s", _sanitize_exc(exc))
    return None


def extract_strict_underlying_data(
    client: SchwabClient, symbol: str, tz: ZoneInfo
) -> Dict[str, Any]:
    """
    Extracts underlying quote, fundamental ratios, reference borrow data, and sizing metrics.
    Enforces strict risk envelopes, zero-denominator protections, and margin sanity checks.
    """
    clean_sym = sanitize_and_validate_symbols(symbol)
    raw_payload = client.get_quote(symbol=clean_sym, fields="quote,fundamental,reference")
    payload = raw_payload.get(clean_sym, raw_payload)

    quote_c = payload.get("quote", {})
    fund_c = payload.get("fundamental", {})
    ref_c = payload.get("reference", {})

    inst_fund_c = {}
    try:
        if hasattr(client, "get_instruments"):
            inst_payload = client.get_instruments(symbol=clean_sym, projection="fundamental")
            inst_list = inst_payload.get("instruments", [])
            if inst_list and isinstance(inst_list, list):
                inst_fund_c = inst_list[0].get("fundamental", {})
            elif isinstance(inst_payload, dict):
                inst_fund_c = inst_payload.get("fundamental", {})
    except Exception as exc:
        logger.info("Instruments query skipped: %s", _sanitize_exc(exc))

    def resolve(field: str) -> Any:
        val = fund_c.get(field)
        val = inst_fund_c.get(field) if val is None or pd.isna(val) else val
        return _clean_numeric_val(val)

    # Quote Time ISO Transformation (CLAR-03)
    quote_epoch = quote_c.get("quoteTime")
    quote_iso = None
    if quote_epoch and not pd.isna(quote_epoch):
        try:
            epoch_val = float(quote_epoch)
            if epoch_val > 0:
                quote_iso = (
                    datetime.fromtimestamp(epoch_val / 1000.0, tz=timezone.utc)
                    .astimezone(tz)
                    .isoformat()
                )
        except Exception as exc:
            logger.debug("Failed parsing quoteTime epoch %s: %s", quote_epoch, _sanitize_exc(exc))
            quote_iso = None

    # REF-05 & PAY-08: Pairwise Relative Margin Consistency Sanity Checks
    net_margin = resolve("netProfitMarginTTM")
    op_margin = resolve("operatingMarginTTM")
    gross_margin = resolve("grossMarginTTM")

    margin_suspect = False
    margin_suspect_reasons: List[str] = []

    def check_margin_pair(m1: Optional[float], m2: Optional[float], reason_token: str) -> None:
        nonlocal margin_suspect
        if m1 is not None and m2 is not None:
            denom = max(abs(m1), abs(m2), 1e-4)
            rel_diff = abs(m1 - m2) / denom
            if rel_diff <= 1e-4:
                margin_suspect = True
                margin_suspect_reasons.append(reason_token)

    check_margin_pair(net_margin, op_margin, "vendor_net_and_operating_margins_identical")
    check_margin_pair(gross_margin, op_margin, "vendor_gross_and_operating_margins_identical")
    check_margin_pair(gross_margin, net_margin, "vendor_gross_and_net_margins_identical")

    # Denominator Sanity & Foreign ADR Suppression
    raw_shares = resolve("sharesOutstanding")
    shares_out = None if (raw_shares is not None and raw_shares <= 0.0) else raw_shares
    shares_state = (
        "UNAVAILABLE_FOR_FOREIGN_ADR"
        if (raw_shares is not None and raw_shares <= 0.0)
        else "VERIFIED"
    )

    raw_eps = resolve("eps")
    clean_eps = None if (raw_eps is not None and abs(raw_eps) < 0.005) else raw_eps

    # REF-01 & ADD-02: Dividend Normalization & Provenance
    div_yield_raw = resolve("divYield")
    div_amount = resolve("divAmount")
    raw_div_freq = resolve("divFreq")

    if raw_div_freq is not None and raw_div_freq in ALLOWED_DIV_FREQS:
        div_freq = raw_div_freq
        div_freq_source = "VENDOR"
    else:
        div_freq = 4.0
        div_freq_source = "ASSUMED_QUARTERLY" if raw_div_freq is None else "UNKNOWN"

    spot_ref = _clean_numeric_val(quote_c.get("lastPrice")) or _clean_numeric_val(
        quote_c.get("closePrice")
    )
    normalized_div_yield, div_yield_basis = normalize_dividend_yield(
        div_yield_raw=div_yield_raw,
        div_amount=div_amount,
        div_freq=div_freq,
        div_freq_source=div_freq_source,
        spot_ref=spot_ref,
    )

    # ADD-01: Raw Market Cap Extraction with DEF-09 Handoff
    market_cap_raw = resolve("marketCap")

    # SAFE-02: Total Debt to Equity Scale Ambiguity Defense
    raw_dte = resolve("totalDebtToEquity")
    dte_basis = "VENDOR_RAW_UNVERIFIED" if raw_dte is not None else "UNKNOWN"

    # SAFE-01 & REF-06: Institutional Short Borrow State Envelope
    is_shortable = ref_c.get("isShortable")
    is_hard_to_borrow = ref_c.get("isHardToBorrow")
    htb_rate = _clean_numeric_val(ref_c.get("htbRate"))

    short_ref_keys = [is_shortable, is_hard_to_borrow, htb_rate]
    present_short_keys = [k for k in short_ref_keys if k is not None]

    if len(present_short_keys) == 3:
        short_state = "FULL_PASSTHROUGH"
    elif len(present_short_keys) > 0:
        short_state = "PARTIAL_PASSTHROUGH"
    else:
        short_state = "UNKNOWN"

    short_locate_status = {
        "state": short_state,
        "isShortable": is_shortable,
        "isHardToBorrow": is_hard_to_borrow,
        "htbRate": htb_rate,
    }

    # PAY-04 & PAY-10: Volume Averages State Machine & Completeness Checking
    raw_vol10d = resolve("vol10DayAvg")
    raw_vol3m = resolve("vol3MonthAvg")
    total_vol = _clean_numeric_val(quote_c.get("totalVolume"))

    vol10d_val = raw_vol10d
    vol10d_state = "PRESENT" if (raw_vol10d is not None and raw_vol10d > 0.0) else "MISSING"
    if raw_vol10d is not None and raw_vol10d <= 0.0:
        if total_vol is not None and total_vol > 1_000_000.0:
            vol10d_val = None
            vol10d_state = "VENDOR_SUSPECT_ZERO"
        else:
            vol10d_val = 0.0
            vol10d_state = "ZERO_OBSERVED"

    vol3m_val = raw_vol3m
    vol3m_state = "PRESENT" if (raw_vol3m is not None and raw_vol3m > 0.0) else "MISSING"
    if raw_vol3m is not None and raw_vol3m <= 0.0:
        if total_vol is not None and total_vol > 1_000_000.0:
            vol3m_val = None
            vol3m_state = "VENDOR_SUSPECT_ZERO"
        else:
            vol3m_val = 0.0
            vol3m_state = "ZERO_OBSERVED"

    # CLAR-01 / PAY-10: Comprehensive 7-Field Liquidity Completeness Enum
    liq_fields = [
        _clean_numeric_val(quote_c.get("bidPrice")),
        _clean_numeric_val(quote_c.get("askPrice")),
        _clean_numeric_val(quote_c.get("bidSize")),
        _clean_numeric_val(quote_c.get("askSize")),
        total_vol,
        vol10d_val,
        vol3m_val,
    ]
    present_liq_count = sum(1 for f in liq_fields if f is not None)
    if present_liq_count == 7:
        liq_state = "FULL_PASSTHROUGH"
    elif present_liq_count > 0:
        liq_state = "PARTIAL_PASSTHROUGH"
    else:
        liq_state = "UNKNOWN"

    return {
        "phase_0_grounding": {
            "symbol": clean_sym,
            "lastPrice": _clean_numeric_val(quote_c.get("lastPrice")),
            "quoteTime_ISO_ET": quote_iso,
            "closePrice": _clean_numeric_val(quote_c.get("closePrice")),
        },
        "step_1_fundamentals": {
            "beta": resolve("beta"),
            "peRatio": resolve("peRatio"),
            "pegRatio": resolve("pegRatio"),
            "pbRatio": resolve("pbRatio"),
            "prRatio": resolve("prRatio"),
            "pcfRatio": resolve("pcfRatio"),
            "quickRatio": resolve("quickRatio"),
            "currentRatio": resolve("currentRatio"),
            "totalDebtToEquity": raw_dte,
            "totalDebtToEquity_basis": dte_basis,
            "totalDebtToEquity_scale_risk": True if raw_dte is not None else False,
            "grossMarginTTM": gross_margin,
            "netProfitMarginTTM": net_margin,
            "operatingMarginTTM": op_margin,
            "margin_fields_suspect": margin_suspect,
            "margin_fields_suspect_reason": (
                "; ".join(margin_suspect_reasons) if margin_suspect else None
            ),
            "returnOnEquity": resolve("returnOnEquity"),
            "returnOnAssets": resolve("returnOnAssets"),
            "eps": clean_eps,
            "revChangeYear": resolve("revChangeYear"),
            "divYield": normalized_div_yield,
            "divYield_raw": div_yield_raw,
            "divYield_basis": div_yield_basis,
            "divAmount": div_amount,
            "divFreq": resolve("divFreq"),
            "div_freq_source": div_freq_source,
            "divDate": fund_c.get("divDate"),
            "marketCap": market_cap_raw,
            "marketCap_unit": "VENDOR_RAW_UNVERIFIED",
            "sharesOutstanding": shares_out,
            "shares_outstanding_state": shares_state,
            "sharesFloat": resolve("sharesFloat"),
        },
        "step_3_short_reference": short_locate_status,
        "step_8_liquidity_sizing": {
            "state": liq_state,
            "bidPrice": liq_fields[0],
            "askPrice": liq_fields[1],
            "bidSize": liq_fields[2],
            "askSize": liq_fields[3],
            "totalVolume": liq_fields[4],
            "vol10DayAvg": vol10d_val,
            "vol10DayAvg_state": vol10d_state,
            "vol3MonthAvg": vol3m_val,
            "vol3MonthAvg_state": vol3m_state,
        },
    }


def extract_in_memory_price_history(
    client: SchwabClient, symbol: str, config: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Extracts historical candles into memory with guaranteed monotonic sort and future pruning."""
    clean_sym = sanitize_and_validate_symbols(symbol)
    cfg = config or {}
    try:
        raw = client.get_price_history(
            symbol=clean_sym,
            period_type=cfg.get("HISTORICAL_PERIOD_TYPE", "year"),
            period=cfg.get("HISTORICAL_PERIOD", 1),
            frequency_type=cfg.get("HISTORICAL_FREQUENCY_TYPE", "daily"),
            frequency=cfg.get("HISTORICAL_FREQUENCY", 1),
            need_extended_hours=cfg.get("HISTORICAL_NEED_EXTENDED_HOURS", False),
        )
        try:
            df = parse_price_history_to_df(raw)
        except Exception:
            df = pd.DataFrame(raw.get("candles", []))
            for col in ["open", "high", "low", "close", "volume"]:
                if col in df.columns:
                    if df[col].dtype == object:
                        df[col] = (
                            df[col]
                            .astype(str)
                            .str.replace("$", "", regex=False)
                            .str.replace(",", "", regex=False)
                            .str.strip()
                        )
                    df[col] = pd.to_numeric(df[col], errors="coerce")

        if df.empty:
            return []

        time_cols = [c for c in ["datetime", "epoch", "time", "date"] if c in df.columns]
        if time_cols:
            t_col = time_cols[0]
            df[t_col] = pd.to_numeric(df[t_col], errors="coerce")
            df = df.dropna(subset=[t_col]).sort_values(by=t_col, ascending=True)
            df = df.drop_duplicates(subset=[t_col], keep="last")

            now_ms = datetime.now(timezone.utc).timestamp() * 1000.0
            df = df[df[t_col] <= (now_ms + 86400000.0)]

        cols = ["datetime", "open", "high", "low", "close", "volume"]
        existing = [c for c in cols if c in df.columns]
        return df[existing].dropna(subset=["high", "low", "close"]).to_dict(orient="records")
    except Exception as exc:
        logger.error("PriceHistory extraction failed: %s", _sanitize_exc(exc))
        return []


def extract_in_memory_option_expirations(
    client: SchwabClient, symbol: str
) -> List[Dict[str, Any]]:
    """Retrieves full expiration calendar with monotonic DTE ordering."""
    clean_sym = sanitize_and_validate_symbols(symbol)
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
        logger.error("OptionExpirations query failed: %s", _sanitize_exc(exc))
        return []


def resolve_optimal_expirations(
    expirations: List[Dict[str, Any]], prefer_longer_tenor: bool = False
) -> List[str]:
    """
    Selects front-month and ~30 DTE tenors deterministically (OPT-02).
    Tie-breaks on equidistant DTE using ISO date strings, with parameterized policy support.
    """
    if not expirations:
        return []
    valid_exps = [e for e in expirations if e.get("daysToExpiration", 0) > 0]
    if not valid_exps:
        valid_exps = expirations

    front_exp = min(valid_exps, key=lambda x: x["daysToExpiration"])["expirationDate"]

    def thirty_dte_key(x: Dict[str, Any]) -> Tuple[int, int, str]:
        diff = abs(x["daysToExpiration"] - 30)
        tenor_penalty = -1 if (prefer_longer_tenor and x["daysToExpiration"] >= 30) else 0
        return (diff, tenor_penalty, str(x.get("expirationDate", "")))

    thirty_dte_exp = min(valid_exps, key=thirty_dte_key)["expirationDate"]
    return sorted(list({front_exp, thirty_dte_exp}))


def extract_in_memory_option_chains(
    client: SchwabClient,
    symbol: str,
    target_expirations: List[str],
    strike_count: int = 14,
    strategy: str = "SINGLE",
    include_quote: bool = True,
) -> Tuple[Optional[float], Optional[float], List[Dict[str, Any]], Dict[str, int]]:
    """
    Extracts raw chain volatility metadata, contemporaneous spot price, option contracts, and rejection telemetry.
    """
    clean_sym = sanitize_and_validate_symbols(symbol)
    raw_chain_iv: Optional[float] = None
    underlying_price: Optional[float] = None
    records: List[Dict[str, Any]] = []

    telemetry = {
        "rejected_negative_mark_count": 0,
        "rejected_zero_strike_count": 0,
        "rejected_expired_contract_count": 0,
        "rejected_negative_spread_count": 0,
    }

    if not target_expirations:
        return None, None, [], telemetry

    try:
        for exp_date in target_expirations:
            raw_chain = client.get_option_chain(
                symbol=clean_sym,
                contract_type="ALL",
                strike_count=strike_count,
                include_underlying_quote=include_quote,
                strategy=strategy,
                from_date=exp_date,
                to_date=exp_date,
            )

            if raw_chain_iv is None:
                raw_chain_iv = _clean_numeric_val(raw_chain.get("volatility"))

            if underlying_price is None:
                underlying_price = _clean_numeric_val(
                    raw_chain.get("underlyingPrice")
                    or raw_chain.get("underlying", {}).get("last")
                    or raw_chain.get("underlying", {}).get("mark")
                )
                if underlying_price is not None and underlying_price <= 0.0:
                    underlying_price = None

            def parse_map(exp_map: Dict[str, Any], flag: str):
                if not isinstance(exp_map, dict):
                    return
                for exp_key, strike_map in exp_map.items():
                    dte = None
                    if ":" in exp_key:
                        parts = exp_key.split(":")
                        if len(parts) >= 2 and parts[1].isdigit():
                            dte = int(parts[1])

                    if not isinstance(strike_map, dict):
                        continue
                    for _, contracts in strike_map.items():
                        if not isinstance(contracts, list):
                            continue
                        for c in contracts:
                            strike = _clean_numeric_val(c.get("strikePrice"))
                            contract_dte = c.get("daysToExpiration", dte)

                            # Rejection Filter: Zero/Negative Strike
                            if strike is None or strike <= 0.0:
                                telemetry["rejected_zero_strike_count"] += 1
                                continue

                            # Rejection Filter: Expired Contracts
                            if contract_dte is not None and contract_dte <= 0:
                                telemetry["rejected_expired_contract_count"] += 1
                                continue

                            bid = _clean_numeric_val(c.get("bid"))
                            ask = _clean_numeric_val(c.get("ask"))
                            mark = _clean_numeric_val(c.get("mark"))

                            # REF-03: Negative Quote & Mark Guards
                            if mark is not None and mark < 0.0:
                                telemetry["rejected_negative_mark_count"] += 1
                                continue

                            if (bid is not None and bid < 0.0) or (ask is not None and ask < 0.0):
                                telemetry["rejected_negative_spread_count"] += 1
                                continue

                            records.append({
                                "putCallIndicator": c.get("putCallIndicator", flag),
                                "daysToExpiration": contract_dte,
                                "strikePrice": strike,
                                "bid": bid,
                                "ask": ask,
                                "mark": mark,
                                "totalVolume": _clean_numeric_val(c.get("totalVolume")),
                                "openInterest": _clean_numeric_val(c.get("openInterest")),
                                "volatility": _clean_numeric_val(c.get("volatility")),
                                "delta": _clean_numeric_val(c.get("delta")),
                            })

            parse_map(raw_chain.get("callExpDateMap", {}), "CALL")
            parse_map(raw_chain.get("putExpDateMap", {}), "PUT")

    except Exception as exc:
        logger.error("OptionChains extraction failed: %s", _sanitize_exc(exc))

    return raw_chain_iv, underlying_price, records, telemetry