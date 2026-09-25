"""
schwab_raw_marketdata.py
========================================================================================
CHARLES SCHWAB IN-MEMORY RAW DATA INGESTION & NORMALIZATION ENGINE (v16.21)
========================================================================================
Implements:
  - ADD-01: Passthrough of raw marketCap directly from Quotes fundamentals.
  - SAFE-01 / REF-06: Strict 3-state envelope for borrow locate (FULL_PASSTHROUGH,
    PARTIAL_PASSTHROUGH, UNKNOWN) with zero fail-open defaults.
  - SAFE-02: totalDebtToEquity tagged VENDOR_RAW_UNVERIFIED without magnitude inference.
  - SAFE-03: Sanitized logger exceptions to prevent credential/vendor context leaks.
  - REF-01: Dynamic cent-anchored hybrid tolerance dividend yield normalizer with
    discrete frequency whitelist (ALLOWED_DIV_FREQS = {1.0, 2.0, 4.0, 12.0}).
  - ADD-02: Strict div_freq_source provenance tracking.
  - REF-02 / PAY-04 / PAY-10: Purged silent 0.0 volume averages; tagged VENDOR_SUSPECT_ZERO.
  - REF-03 / REF-04 / ADD-03: Non-negative option price guards, robust split parsing,
    and explicit contract rejection telemetry.
  - OPT-02: Deterministic secondary sort on resolve_optimal_expirations.
  - CLAR-01: 3-state liquidity block envelope; chain_implied_volatility extraction.
  - PRUNE-01: Single-argument extract_market_open_status(client).
  - PAY-24 / PAY-35 / PAY-36 / PAY-47: 3-tenor expiration bracketing engine (Front,
    Near-Sub <=30 DTE, Near-Sup >30 DTE) with skip telemetry (DTE_BELOW_MINIMUM_4).
  - PAY-32 / PAY-40 / PAY-41 / PAY-46 / PAY-51 / PAY-52 / PAY-53: 5-state margin-gated
    fundamentals zero sanitizer with denominator availability checks.
  - PAY-54: Frozen module constants for diagnostic reason codes and states.
========================================================================================
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from schwab_client import SchwabClient

logger = logging.getLogger("schwab_raw_marketdata")
logger.addHandler(logging.NullHandler())

# ------------------------------------------------------------------------------
# CONSTANTS & PROTOCOL TOKENS (PAY-54)
# ------------------------------------------------------------------------------
DATA_SCHEMA_VERSION = "16.21"
PROTOCOL_VERSION = "v16.21"

REASON_DTE_BELOW_MINIMUM_4 = "DTE_BELOW_MINIMUM_4"
REASON_SKEW_SPREAD_TOLERANCE_EXCEEDED = "skew_wing_liquidity_insufficient_relative_spread_exceeds_tolerance"
REASON_MARKET_CAP_INTEGRITY_FAILURE = "upstream_market_cap_divergence_integrity_failure"

STATE_AS_REPORTED = "AS_REPORTED"
STATE_AS_REPORTED_POSITIVE_MARGIN = "AS_REPORTED_ZERO_WITH_POSITIVE_MARGIN"
STATE_VENDOR_UNAVAILABLE_NEG_EARNINGS = "VENDOR_UNAVAILABLE_NEGATIVE_EARNINGS"
STATE_VENDOR_UNAVAILABLE_NEG_OP_INCOME = "VENDOR_UNAVAILABLE_NEGATIVE_OPERATING_INCOME"
STATE_ZERO_NET_MARGIN_MISSING = "VENDOR_ZERO_UNCORROBORATED_NET_MARGIN_MISSING"
STATE_DROPOUT_MISSING_PROFITABILITY = "VENDOR_UNAVAILABLE_MISSING_PROFITABILITY_DATA"
STATE_MISSING_DENOMINATOR_EQUITY = "VENDOR_UNAVAILABLE_NEGATIVE_OR_MISSING_EQUITY"
STATE_MISSING_DENOMINATOR_ASSETS = "VENDOR_UNAVAILABLE_MISSING_ASSET_BASE"

ALLOWED_DIV_FREQS: Set[float] = {1.0, 2.0, 4.0, 12.0}
SYMBOL_REGEX = re.compile(r"^[$A-Z0-9.-_/ ]{1,30}$")


# ------------------------------------------------------------------------------
# NUMERIC & SANITIZATION UTILITIES
# ------------------------------------------------------------------------------
def sanitize_and_validate_symbols(raw_symbol: str) -> str:
    """Cleans, validates, and standardizes ticker symbols."""
    sym = raw_symbol.strip().upper()
    if not SYMBOL_REGEX.match(sym):
        raise ValueError(f"Invalid symbol format: '{raw_symbol}'")
    return sym


def _safe_float(val: Any) -> Optional[float]:
    """Defensive float conversion stripping currency symbols and commas."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return None
        return float(val)
    if isinstance(val, str):
        cleaned = val.replace("$", "").replace(",", "").strip()
        if not cleaned:
            return None
        try:
            f = float(cleaned)
            return None if math.isnan(f) or math.isinf(f) else f
        except ValueError:
            return None
    return None


def normalize_dividend_yield(
    div_yield_raw: Optional[float],
    div_amount: Optional[float],
    div_freq: Optional[float],
    div_freq_source: str,
    spot_ref: Optional[float],
) -> Tuple[Optional[float], str]:
    """
    Implements REF-01 dynamic hybrid tolerance normalizer with discrete frequency whitelist.
    Guarantees idempotency and protects against floating-point dust.
    """
    if div_yield_raw is None or spot_ref is None or spot_ref <= 0.0:
        return None, "NO_DIVIDEND_OR_INVALID_INPUT"

    div_yield_raw = float(div_yield_raw)
    if div_yield_raw < 0.01:
        return round(div_yield_raw, 4), "VENDOR_UNVERIFIED"

    if div_amount is None or div_amount <= 0.0:
        return round(div_yield_raw, 4), "VENDOR_UNVERIFIED"

    yield_direct = (float(div_amount) / float(spot_ref)) * 100.0
    tol = max(0.05 * div_yield_raw, (0.01 / float(spot_ref)) * 100.0)

    # Branch 1: Direct annual confirmation
    if abs(yield_direct - div_yield_raw) <= tol:
        return round(div_yield_raw, 4), "DIRECT_CONFIRMED"

    # Branch 2: Vendor frequency periodic annualization
    if (
        div_freq_source == "VENDOR"
        and div_freq is not None
        and div_freq > 0.0
        and float(div_freq) in ALLOWED_DIV_FREQS
    ):
        scaled_yield = yield_direct * float(div_freq)
        if abs(scaled_yield - div_yield_raw) <= tol:
            return round(scaled_yield, 4), "ANNUALIZED_FROM_PERIODIC"

    return round(div_yield_raw, 4), "VENDOR_UNVERIFIED"


def _sanitize_fundamentals_ratio(
    raw_val: Any,
    field_name: str,
    net_margin: Optional[float],
    op_margin: Optional[float],
    denominator_available: bool = True,
) -> Tuple[Optional[float], str]:
    """
    Evaluates raw fundamental ratios against Step 0.4 denominator gates and
    the PAY-46 / PAY-51 / PAY-52 5-state margin-gated decision table.
    """
    cleaned = _safe_float(raw_val)
    if cleaned is None:
        return None, "VENDOR_UNAVAILABLE"

    # Non-zero passthrough
    if abs(cleaned) > 1e-6:
        return cleaned, STATE_AS_REPORTED

    # Special handling for standalone zero-swarm variables (PAY-32, PAY-40)
    if field_name == "beta":
        return None, "VENDOR_UNAVAILABLE_OR_ZERO"
    if field_name == "pegRatio":
        return None, "VENDOR_ZERO_NON_MEANINGFUL"
    if field_name == "pcfRatio":
        return None, "NON_POSITIVE_OR_UNAVAILABLE"
    if field_name == "revChangeYear":
        if op_margin is not None and op_margin < 0.0:
            return None, "VENDOR_ZERO_UNVERIFIED"
        return 0.0, STATE_AS_REPORTED

    # Margin-gated fields (ROE, ROA)
    if field_name in ("returnOnEquity", "returnOnAssets"):
        # Stage 1: Denominator Sanity Gate (PAY-53)
        if not denominator_available:
            return (
                None,
                STATE_MISSING_DENOMINATOR_EQUITY
                if field_name == "returnOnEquity"
                else STATE_MISSING_DENOMINATOR_ASSETS,
            )

        # Stage 2: 5-State Margin Decision Table
        if net_margin is not None and net_margin < 0.0:
            return None, STATE_VENDOR_UNAVAILABLE_NEG_EARNINGS
        if net_margin is not None and net_margin > 0.0:
            return 0.0, STATE_AS_REPORTED_POSITIVE_MARGIN
        if net_margin is None and op_margin is not None and op_margin < 0.0:
            return None, STATE_VENDOR_UNAVAILABLE_NEG_OP_INCOME
        if net_margin is None and op_margin is not None and op_margin >= 0.0:
            return None, STATE_ZERO_NET_MARGIN_MISSING
        if net_margin is None and op_margin is None:
            return None, STATE_DROPOUT_MISSING_PROFITABILITY

    return cleaned, STATE_AS_REPORTED


# ------------------------------------------------------------------------------
# EXTRACTION ROUTINES
# ------------------------------------------------------------------------------
def extract_market_open_status(client: SchwabClient) -> Optional[bool]:
    """Single-argument interface aligned with SchwabClient (PRUNE-01)."""
    try:
        if hasattr(client, "get_market_hours"):
            raw_hours = client.get_market_hours(markets="equity")
            if isinstance(raw_hours, dict):
                return raw_hours.get("equity", {}).get("EQ", {}).get("isOpen", False)
    except Exception as exc:
        logger.debug("Market hours retrieval skipped: %s", type(exc).__name__)
    return None


def extract_strict_underlying_data(
    client: SchwabClient, symbol: str, tz: ZoneInfo
) -> Dict[str, Any]:
    """
    Extracts underlying fundamentals, quotes, and borrow locate data into
    Protocol v16.21-compliant structured payloads.
    """
    sym = sanitize_and_validate_symbols(symbol)
    try:
        raw_payload = client.get_quote(symbol=sym, fields="quote,fundamental,reference")
    except Exception as exc:
        logger.error("Failed to fetch quote for %s: %s", sym, type(exc).__name__)
        raise RuntimeError(f"API request failed for symbol {sym}") from exc

    payload = raw_payload.get(sym, raw_payload)
    quote_c = payload.get("quote", {})
    fund_c = payload.get("fundamental", {})
    ref_c = payload.get("reference", {})

    inst_fund_c = {}
    try:
        if hasattr(client, "get_instruments"):
            inst_payload = client.get_instruments(symbol=sym, projection="fundamental")
            inst_list = inst_payload.get("instruments", [])
            if inst_list and isinstance(inst_list, list):
                inst_fund_c = inst_list[0].get("fundamental", {})
            elif isinstance(inst_payload, dict):
                inst_fund_c = inst_payload.get("fundamental", {})
    except Exception as exc:
        logger.debug("Instruments query fallback skipped: %s", type(exc).__name__)

    def resolve(field: str) -> Any:
        v = fund_c.get(field)
        return inst_fund_c.get(field) if v is None or pd.isna(v) else v

    # Phase 0 Grounding Close & Spot
    last_price = _safe_float(quote_c.get("lastPrice"))
    close_price = _safe_float(quote_c.get("closePrice"))

    quote_epoch = quote_c.get("quoteTime")
    quote_iso = None
    if quote_epoch and not pd.isna(quote_epoch) and _safe_float(quote_epoch) and float(quote_epoch) > 0:
        try:
            quote_iso = datetime.fromtimestamp(float(quote_epoch) / 1000.0, tz=timezone.utc).astimezone(tz).isoformat()
        except Exception as exc:
            logger.debug("Failed to parse quote timestamp %s: %s", quote_epoch, type(exc).__name__)

    # Margins and Suspicion Check (PAY-08)
    net_margin = _safe_float(resolve("netProfitMarginTTM"))
    op_margin = _safe_float(resolve("operatingMarginTTM"))
    gross_margin = _safe_float(resolve("grossMarginTTM"))

    margin_identical = False
    if net_margin is not None and op_margin is not None:
        if abs(net_margin - op_margin) < 1e-4:
            margin_identical = True

    # Share Count and ADR Suppression
    shares_raw = _safe_float(resolve("sharesOutstanding"))
    shares_state = "CONFIRMED"
    shares_out = shares_raw
    if shares_raw is None or shares_raw <= 0.0:
        shares_out = None
        shares_state = "UNAVAILABLE_FOR_FOREIGN_ADR"

    # Fundamental Zero Sanitization (PAY-32, PAY-40, PAY-41, PAY-46, PAY-53)
    # Check balance-sheet denominators:
    book_value_per_share = _safe_float(resolve("bookValuePerShare"))
    has_positive_equity = True
    if book_value_per_share is not None and book_value_per_share <= 0.0:
        has_positive_equity = False

    beta_val, beta_st = _sanitize_fundamentals_ratio(fund_c.get("beta"), "beta", net_margin, op_margin)
    peg_val, peg_st = _sanitize_fundamentals_ratio(fund_c.get("pegRatio"), "pegRatio", net_margin, op_margin)
    pcf_val, pcf_st = _sanitize_fundamentals_ratio(fund_c.get("pcfRatio"), "pcfRatio", net_margin, op_margin)
    roe_val, roe_st = _sanitize_fundamentals_ratio(
        fund_c.get("returnOnEquity"), "returnOnEquity", net_margin, op_margin, denominator_available=has_positive_equity
    )
    roa_val, roa_st = _sanitize_fundamentals_ratio(
        fund_c.get("returnOnAssets"), "returnOnAssets", net_margin, op_margin, denominator_available=True
    )
    rev_val, rev_st = _sanitize_fundamentals_ratio(
        resolve("revChangeYear"), "revChangeYear", net_margin, op_margin
    )

    # Dividend Processing (REF-01, ADD-02)
    div_amt = _safe_float(fund_c.get("divAmount"))
    div_freq_raw = _safe_float(fund_c.get("divFreq"))
    div_freq_src = "VENDOR" if div_freq_raw is not None and div_freq_raw > 0 else "UNKNOWN"
    norm_yield, div_basis = normalize_dividend_yield(
        _safe_float(fund_c.get("divYield")), div_amt, div_freq_raw, div_freq_src, last_price
    )

    # Short Locate Reference (SAFE-01, REF-06)
    is_shortable = ref_c.get("isShortable")
    is_htb = ref_c.get("isHardToBorrow")
    htb_rate = _safe_float(ref_c.get("htbRate"))

    if is_shortable is None and is_htb is None and htb_rate is None:
        short_state = "UNKNOWN"
        short_reason = "broker_reference_keys_absent"
    elif is_shortable is not None and is_htb is not None:
        short_state = "FULL_PASSTHROUGH"
        short_reason = None
    else:
        short_state = "PARTIAL_PASSTHROUGH"
        short_reason = "broker_reference_keys_partial"

    # Liquidity Processing (REF-02, PAY-04, PAY-10)
    vol_10d_raw = _safe_float(fund_c.get("vol10DayAvg"))
    vol_3m_raw = _safe_float(fund_c.get("vol3MonthAvg"))
    tot_vol = _safe_float(quote_c.get("totalVolume"))

    vol_10d = vol_10d_raw
    vol_10d_state = "AS_REPORTED"
    if vol_10d_raw is not None and vol_10d_raw <= 0.0 and tot_vol is not None and tot_vol > 1000.0:
        vol_10d = None
        vol_10d_state = "VENDOR_SUSPECT_ZERO"

    vol_3m = vol_3m_raw
    vol_3m_state = "AS_REPORTED"
    if vol_3m_raw is not None and vol_3m_raw <= 0.0 and tot_vol is not None and tot_vol > 1000.0:
        vol_3m = None
        vol_3m_state = "VENDOR_SUSPECT_ZERO"

    liq_fields = [
        quote_c.get("bidPrice"), quote_c.get("askPrice"),
        quote_c.get("bidSize"), quote_c.get("askSize"),
        tot_vol, vol_10d, vol_3m
    ]
    present_count = sum(1 for f in liq_fields if f is not None)
    if present_count == len(liq_fields):
        liq_state = "FULL_PASSTHROUGH"
    elif present_count > 0:
        liq_state = "PARTIAL_PASSTHROUGH"
    else:
        liq_state = "UNKNOWN"

    return {
        "phase_0_grounding": {
            "symbol": sym,
            "lastPrice": last_price,
            "closePrice": close_price,
            "quoteTime_ISO_ET": quote_iso,
        },
        "step_1_fundamentals": {
            "beta": beta_val,
            "beta_state": beta_st,
            "peRatio": _safe_float(fund_c.get("peRatio")),
            "pegRatio": peg_val,
            "pegRatio_state": peg_st,
            "pbRatio": _safe_float(fund_c.get("pbRatio")),
            "prRatio": _safe_float(fund_c.get("prRatio")),
            "pcfRatio": pcf_val,
            "pcfRatio_state": pcf_st,
            "quickRatio": _safe_float(fund_c.get("quickRatio")),
            "currentRatio": _safe_float(fund_c.get("currentRatio")),
            "totalDebtToEquity": _safe_float(fund_c.get("totalDebtToEquity")),
            "totalDebtToEquity_basis": "VENDOR_RAW_UNVERIFIED",
            "grossMarginTTM": gross_margin,
            "netProfitMarginTTM": net_margin,
            "operatingMarginTTM": op_margin,
            "margin_fields_suspect": margin_identical,
            "margin_fields_suspect_reason": "vendor_net_and_operating_margins_identical" if margin_identical else None,
            "returnOnEquity": roe_val,
            "returnOnEquity_state": roe_st,
            "returnOnAssets": roa_val,
            "returnOnAssets_state": roa_st,
            "eps": _safe_float(fund_c.get("eps")),
            "revChangeYear": rev_val,
            "revChangeYear_state": rev_st,
            "divYield": norm_yield,
            "divYield_basis": div_basis,
            "divYield_raw": _safe_float(fund_c.get("divYield")),
            "divAmount": div_amt,
            "divFreq": div_freq_raw,
            "div_freq_source": div_freq_src,
            "divDate": fund_c.get("divDate"),
            "sharesOutstanding": shares_out,
            "shares_outstanding_state": shares_state,
            "sharesFloat": _safe_float(resolve("sharesFloat")),
            "marketCap": _safe_float(fund_c.get("marketCap")),
            "marketCap_unit": "VENDOR_RAW_UNVERIFIED",
        },
        "step_3_short_reference": {
            "state": short_state,
            "reason": short_reason,
            "isShortable": is_shortable,
            "isHardToBorrow": is_htb,
            "htbRate": htb_rate,
        },
        "step_8_liquidity_sizing": {
            "state": liq_state,
            "bidPrice": _safe_float(quote_c.get("bidPrice")),
            "askPrice": _safe_float(quote_c.get("askPrice")),
            "bidSize": _safe_float(quote_c.get("bidSize")),
            "askSize": _safe_float(quote_c.get("askSize")),
            "totalVolume": tot_vol,
            "vol10DayAvg": vol_10d,
            "vol10DayAvg_state": vol_10d_state,
            "vol3MonthAvg": vol_3m,
            "vol3MonthAvg_state": vol_3m_state,
        },
    }


def extract_in_memory_price_history(
    client: SchwabClient, symbol: str, hist_cfg: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Pulls OHLCV history cleanly in-memory."""
    sym = sanitize_and_validate_symbols(symbol)
    try:
        raw = client.get_price_history(
            symbol=sym,
            period_type=hist_cfg.get("HISTORICAL_PERIOD_TYPE", "year"),
            period=hist_cfg.get("HISTORICAL_PERIOD", 1),
            frequency_type=hist_cfg.get("HISTORICAL_FREQUENCY_TYPE", "daily"),
            frequency=hist_cfg.get("HISTORICAL_FREQUENCY", 1),
            need_extended_hours=hist_cfg.get("HISTORICAL_NEED_EXTENDED_HOURS", False),
        )
        candles = raw.get("candles", []) if isinstance(raw, dict) else []
        return candles
    except Exception as exc:
        logger.error("PriceHistory fetch failed for %s: %s", sym, type(exc).__name__)
        return []


def extract_in_memory_option_expirations(
    client: SchwabClient, symbol: str
) -> List[Dict[str, Any]]:
    """Retrieves full expiration calendar with secondary deterministic sort."""
    sym = sanitize_and_validate_symbols(symbol)
    try:
        payload = client.get_option_expirations(sym)
        exp_list = payload.get("expirationList", [])
        if not exp_list:
            return []
        df = pd.DataFrame(exp_list)
        if "daysToExpiration" in df.columns and "expirationDate" in df.columns:
            df = df.sort_values(by=["daysToExpiration", "expirationDate"], ascending=[True, True])
            return df.to_dict(orient="records")
        return exp_list
    except Exception as exc:
        logger.error("OptionExpirations query failed for %s: %s", sym, type(exc).__name__)
        return []


def resolve_optimal_expirations(
    expirations_list: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Implements PAY-24 / PAY-35 / PAY-47 3-tenor bracketing engine:
      1. Front tenor (DTE >= 4) with skip telemetry (DTE_BELOW_MINIMUM_4).
      2. Near-Sub tenor (DTE <= 30).
      3. Near-Sup tenor (DTE > 30).
    """
    if not expirations_list:
        return {
            "target_expirations": [],
            "front_tenor_selection": {
                "selected_dte": None,
                "skipped_expirations_count": 0,
                "skipped_expirations": [],
            },
            "near_30_sub": None,
            "near_30_sup": None,
        }

    skipped_expirations: List[Dict[str, Any]] = []
    eligible_expirations: List[Dict[str, Any]] = []

    for exp in expirations_list:
        dte = exp.get("daysToExpiration")
        if dte is not None and isinstance(dte, (int, float)):
            dte_val = int(dte)
            if dte_val < 4:
                skipped_expirations.append({"dte": dte_val, "reason": REASON_DTE_BELOW_MINIMUM_4})
            else:
                eligible_expirations.append(exp)

    if not eligible_expirations:
        return {
            "target_expirations": [],
            "front_tenor_selection": {
                "selected_dte": None,
                "skipped_expirations_count": len(skipped_expirations),
                "skipped_expirations": skipped_expirations,
            },
            "near_30_sub": None,
            "near_30_sup": None,
        }

    # 1. Front tenor: lowest DTE >= 4
    front_exp = eligible_expirations[0]
    front_date = front_exp["expirationDate"]

    # 2. Near-Sub tenor: max DTE <= 30
    sub_candidates = [e for e in eligible_expirations if e["daysToExpiration"] <= 30]
    near_sub_exp = max(sub_candidates, key=lambda x: x["daysToExpiration"]) if sub_candidates else None

    # 3. Near-Sup tenor: min DTE > 30
    sup_candidates = [e for e in eligible_expirations if e["daysToExpiration"] > 30]
    near_sup_exp = min(sup_candidates, key=lambda x: x["daysToExpiration"]) if sup_candidates else None

    # Assembly
    target_dates: List[str] = [front_date]
    if near_sub_exp and near_sub_exp["expirationDate"] not in target_dates:
        target_dates.append(near_sub_exp["expirationDate"])
    if near_sup_exp and near_sup_exp["expirationDate"] not in target_dates:
        target_dates.append(near_sup_exp["expirationDate"])

    return {
        "target_expirations": target_dates,
        "front_tenor_selection": {
            "selected_dte": front_exp["daysToExpiration"],
            "skipped_expirations_count": len(skipped_expirations),
            "skipped_expirations": skipped_expirations,
        },
        "near_30_sub": near_sub_exp,
        "near_30_sup": near_sup_exp,
    }


def extract_in_memory_option_chains(
    client: SchwabClient,
    symbol: str,
    target_expirations: Any,
    strike_count: int = 14,
    strategy: str = "SINGLE",
    include_underlying_quote: bool = True,
) -> Tuple[Optional[float], Optional[float], List[Dict[str, Any]], Dict[str, int]]:
    """
    Extracts options chains, tracking rejection counters and isolating vendor metadata.
    Returns: (vendor_raw_chain_volatility_metadata, spot_price, records, telemetry)
    """
    sym = sanitize_and_validate_symbols(symbol)
    rejection_counters = {
        "rejected_zero_strike_count": 0,
        "rejected_expired_contract_count": 0,
        "rejected_negative_mark_count": 0,
        "rejected_negative_price_count": 0,
    }

    target_dates: Optional[List[str]] = None
    if isinstance(target_expirations, dict):
        target_dates = target_expirations.get("target_expirations")
    elif isinstance(target_expirations, list):
        target_dates = target_expirations

    from_date = target_dates[0] if target_dates else None
    to_date = target_dates[-1] if target_dates else None

    try:
        raw_chain = client.get_option_chain(
            symbol=sym,
            contract_type="ALL",
            strike_count=strike_count,
            include_underlying_quote=include_underlying_quote,
            strategy=strategy,
            from_date=from_date,
            to_date=to_date,
        )
    except Exception as exc:
        logger.error("OptionChains extraction failed for %s: %s", sym, type(exc).__name__)
        return None, None, [], rejection_counters

    vendor_raw_iv = _safe_float(raw_chain.get("volatility"))
    underlying_price = _safe_float(raw_chain.get("underlyingPrice"))
    records: List[Dict[str, Any]] = []

    def parse_side(exp_map: Dict[str, Any], default_indicator: str):
        if not isinstance(exp_map, dict):
            return
        for exp_key, strike_map in exp_map.items():
            parts = exp_key.split(":")
            exp_date = parts[0]
            dte = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None

            if target_dates and exp_date not in target_dates:
                continue
            if not isinstance(strike_map, dict):
                continue

            for _, contracts in strike_map.items():
                if not isinstance(contracts, list):
                    continue
                for c in contracts:
                    strike = _safe_float(c.get("strikePrice"))
                    contract_dte = c.get("daysToExpiration", dte)
                    mark = _safe_float(c.get("mark"))
                    bid = _safe_float(c.get("bid"))
                    ask = _safe_float(c.get("ask"))

                    # Non-negative & integrity guards (REF-03, ADD-03)
                    if strike is None or strike <= 0.0:
                        rejection_counters["rejected_zero_strike_count"] += 1
                        continue
                    if contract_dte is not None and contract_dte <= 0:
                        rejection_counters["rejected_expired_contract_count"] += 1
                        continue
                    if mark is not None and mark < 0.0:
                        rejection_counters["rejected_negative_mark_count"] += 1
                        continue
                    if (bid is not None and bid < 0.0) or (ask is not None and ask < 0.0):
                        rejection_counters["rejected_negative_price_count"] += 1
                        continue

                    records.append({
                        "putCallIndicator": c.get("putCallIndicator", default_indicator),
                        "daysToExpiration": contract_dte,
                        "expirationDate": exp_date,
                        "strikePrice": strike,
                        "bid": bid,
                        "ask": ask,
                        "mark": mark,
                        "totalVolume": _safe_float(c.get("totalVolume")),
                        "openInterest": _safe_float(c.get("openInterest")),
                        "volatility": _safe_float(c.get("volatility")),
                        "delta": _safe_float(c.get("delta")),
                        "gamma": _safe_float(c.get("gamma")),
                        "theta": _safe_float(c.get("theta")),
                        "vega": _safe_float(c.get("vega")),
                        "rho": _safe_float(c.get("rho")),
                        "inTheMoney": c.get("inTheMoney"),
                        "contractId": c.get("symbol", c.get("contractId")),
                    })

    parse_side(raw_chain.get("callExpDateMap", {}), "CALL")
    parse_side(raw_chain.get("putExpDateMap", {}), "PUT")

    return vendor_raw_iv, underlying_price, records, rejection_counters