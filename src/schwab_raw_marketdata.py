"""
schwab_raw_marketdata.py
========================================================================================
Institutional Charles Schwab Market Data Extraction & Upstream Normalization Layer
Protocol v16.21 Production Certified
========================================================================================
Changelog v16.21 (PAY-57 through PAY-65 Reconciliation):
  - PAY-57: Sanitize foreign ADR EPS stubs when net margin is positive.
  - PAY-59: Purged residual 'volatility_30d_surface' from surface_parameters.
  - PAY-61: Restored explicit quote extraction of 'marketCap' into step_1_fundamentals.
  - PAY-51/52/53: 5-state margin table & ROE/ROA denominator sanity gating.
========================================================================================
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("schwab_raw_marketdata")
logger.addHandler(logging.NullHandler())

# Protocol Reason and State Constants (PAY-54)
REASON_DTE_BELOW_MINIMUM_4 = "DTE_BELOW_MINIMUM_4"
STATE_AS_REPORTED_POSITIVE_MARGIN = "AS_REPORTED_ZERO_WITH_POSITIVE_MARGIN"
STATE_ZERO_NET_MARGIN_MISSING = "VENDOR_ZERO_UNCORROBORATED_NET_MARGIN_MISSING"
STATE_UNAVAILABLE_FOREIGN_ADR = "UNAVAILABLE_FOR_FOREIGN_ADR"

ALLOWED_DIV_FREQS: Set[float] = {1.0, 2.0, 4.0, 12.0}


def _clean_numeric_val(val: Any) -> Optional[float]:
    """Coerces numerical inputs to clean float primitives or None."""
    if val is None:
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


def resolve_optimal_expirations(expirations: List[Dict[str, Any]]) -> Tuple[List[str], Dict[str, Any]]:
    """
    PAY-24 / PAY-35 / PAY-47: 3-Tenor Bracketing Engine.
    Locates:
      1. Front tenor (DTE >= 4)
      2. Nearest tenor <= 30 DTE
      3. Nearest tenor > 30 DTE
    """
    telemetry: Dict[str, Any] = {
        "selected_dte": None,
        "skipped_expirations_count": 0,
        "skipped_expirations": []
    }

    if not expirations:
        return [], telemetry

    sorted_expiries = sorted(expirations, key=lambda x: x.get("daysToExpiration", 9999))
    eligible = []

    for exp in sorted_expiries:
        dte = exp.get("daysToExpiration", 0)
        if dte < 4:
            telemetry["skipped_expirations_count"] += 1
            telemetry["skipped_expirations"].append({"dte": dte, "reason": REASON_DTE_BELOW_MINIMUM_4})
        else:
            eligible.append(exp)

    if not eligible:
        return [], telemetry

    front_exp = eligible[0]
    telemetry["selected_dte"] = front_exp.get("daysToExpiration")

    sub_30 = [e for e in eligible if e.get("daysToExpiration", 0) <= 30]
    sup_30 = [e for e in eligible if e.get("daysToExpiration", 0) > 30]

    selected_expirations_set = set()
    selected_expirations_list = []

    for candidate in [
        front_exp,
        sub_30[-1] if sub_30 else None,
        sup_30[0] if sup_30 else None
    ]:
        if candidate is not None:
            exp_date = candidate.get("expirationDate")
            if exp_date and exp_date not in selected_expirations_set:
                selected_expirations_set.add(exp_date)
                selected_expirations_list.append(exp_date)

    return selected_expirations_list, telemetry


def evaluate_5_state_return_metric(
    raw_val: Optional[float],
    m_net: Optional[float],
    m_op: Optional[float],
    denominator_valid: bool = True,
    denominator_err_state: str = "VENDOR_UNAVAILABLE_MISSING_DENOMINATOR"
) -> Tuple[Optional[float], str]:
    """
    PAY-46 / PAY-51 / PAY-52 / PAY-53: 5-State Margin Decision Table with Denominator Gate.
    """
    if not denominator_valid:
        return None, denominator_err_state

    if raw_val is None:
        return None, "VENDOR_UNAVAILABLE"

    if raw_val != 0.0:
        return raw_val, "AS_REPORTED"

    # Evaluate 0.0 against margins
    if m_net is not None and m_net < 0.0:
        return None, "VENDOR_UNAVAILABLE_NEGATIVE_EARNINGS"
    if m_net is not None and m_net > 0.0:
        return 0.0, STATE_AS_REPORTED_POSITIVE_MARGIN
    if m_net is None and m_op is not None and m_op < 0.0:
        return None, "VENDOR_UNAVAILABLE_NEGATIVE_OPERATING_INCOME"
    if m_net is None and m_op is not None and m_op >= 0.0:
        return None, STATE_ZERO_NET_MARGIN_MISSING
    return None, "VENDOR_UNAVAILABLE_MISSING_PROFITABILITY_DATA"


def extract_strict_underlying_data(quotes_resp: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    """Extracts raw market data, sanitizes fundamentals, and preserves raw unverified primitives."""
    quote_data = quotes_resp.get(symbol, {})
    raw_quote = quote_data.get("quote", {})
    raw_fund = quote_data.get("fundamental", {})
    raw_ref = quote_data.get("reference", {})

    last_price = _clean_numeric_val(raw_quote.get("lastPrice"))
    close_price = _clean_numeric_val(raw_quote.get("closePrice"))

    # Margin metrics extraction
    net_margin = _clean_numeric_val(raw_fund.get("netProfitMarginTTM"))
    op_margin = _clean_numeric_val(raw_fund.get("operatingMarginTTM"))
    gross_margin = _clean_numeric_val(raw_fund.get("grossMarginTTM"))

    margin_suspect = False
    margin_suspect_reason = None
    if net_margin is not None and op_margin is not None:
        if net_margin == op_margin:
            margin_suspect = True
            margin_suspect_reason = "vendor_net_and_operating_margins_identical"

    # PAY-53: Denominator availability checks
    total_equity = _clean_numeric_val(raw_fund.get("totalStockholdersEquity"))
    total_assets = _clean_numeric_val(raw_fund.get("totalAssets"))
    equity_valid = total_equity is None or total_equity > 0.0
    assets_valid = total_assets is None or total_assets > 0.0

    roe_val, roe_state = evaluate_5_state_return_metric(
        _clean_numeric_val(raw_fund.get("returnOnEquity")),
        net_margin,
        op_margin,
        denominator_valid=equity_valid,
        denominator_err_state="VENDOR_UNAVAILABLE_NEGATIVE_OR_MISSING_EQUITY"
    )

    roa_val, roa_state = evaluate_5_state_return_metric(
        _clean_numeric_val(raw_fund.get("returnOnAssets")),
        net_margin,
        op_margin,
        denominator_valid=assets_valid,
        denominator_err_state="VENDOR_UNAVAILABLE_MISSING_ASSET_BASE"
    )

    # Beta sanitization
    beta_raw = _clean_numeric_val(raw_fund.get("beta"))
    beta_val, beta_state = (None, "VENDOR_UNAVAILABLE") if (beta_raw is None or beta_raw == 0.0) else (beta_raw, "AS_REPORTED")

    # PEG Ratio sanitization
    peg_raw = _clean_numeric_val(raw_fund.get("pegRatio"))
    peg_val, peg_state = (None, "VENDOR_UNAVAILABLE") if (peg_raw is None or peg_raw == 0.0) else (peg_raw, "AS_REPORTED")

    # PCF Ratio sanitization
    pcf_raw = _clean_numeric_val(raw_fund.get("pcfRatio"))
    pcf_val, pcf_state = (None, "VENDOR_UNAVAILABLE") if (pcf_raw is None or pcf_raw == 0.0) else (pcf_raw, "AS_REPORTED")

    # Revenue Change Year sanitization
    rev_raw = _clean_numeric_val(raw_fund.get("revChangeYear"))
    rev_val, rev_state = (0.0, "VENDOR_ZERO_UNVERIFIED") if rev_raw == 0.0 else (rev_raw, "AS_REPORTED")

    # Dividend extraction & normalization (REF-01)
    div_yield_raw = _clean_numeric_val(raw_fund.get("dividendYield"))
    div_amount = _clean_numeric_val(raw_fund.get("dividendAmount"))
    div_freq = _clean_numeric_val(raw_fund.get("dividendFreq"))

    div_yield = div_yield_raw
    div_basis = "VENDOR_UNVERIFIED"
    div_freq_source = "VENDOR" if div_freq in ALLOWED_DIV_FREQS else "UNKNOWN"

    if div_yield_raw is not None and div_yield_raw > 0.0:
        div_basis = "DIRECT_CONFIRMED"
    elif div_yield_raw == 0.0:
        div_basis = "VENDOR_UNVERIFIED"

    # Shares Outstanding & Foreign ADR handling (DEF-03 / PAY-57)
    shares_raw = _clean_numeric_val(raw_fund.get("sharesOutstanding"))
    is_foreign_adr = shares_raw is None or shares_raw <= 0.0
    shares_val = None if is_foreign_adr else shares_raw
    shares_state = STATE_UNAVAILABLE_FOREIGN_ADR if is_foreign_adr else "CONFIRMED"

    # PAY-57: EPS sanitization for Foreign ADRs / micro stubs
    eps_raw = _clean_numeric_val(raw_fund.get("eps"))
    eps_val = eps_raw
    eps_state = "AS_REPORTED"
    if is_foreign_adr and (eps_raw is None or eps_raw == 0.0 or (net_margin is not None and net_margin > 0.0 and eps_raw < 0.01)):
        eps_val = None
        eps_state = "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED"
    elif eps_raw == 0.0 and net_margin is not None and net_margin < 0.0:
        eps_val = None
        eps_state = "VENDOR_UNAVAILABLE_NEGATIVE_EARNINGS"

    # PAY-61: Explicit Quote Extraction of Market Capitalization
    raw_mcap = _clean_numeric_val(raw_fund.get("marketCap"))

    return {
        "phase_0_grounding": {
            "symbol": symbol,
            "lastPrice": f"${last_price:,.2f}" if last_price is not None else None,
            "closePrice": f"${close_price:,.2f}" if close_price is not None else None,
            "quoteTime_ISO_ET": raw_quote.get("quoteTime"),
            "market_isOpen": raw_quote.get("isMarketOpen", True)
        },
        "step_1_fundamentals": {
            "beta": beta_val,
            "beta_state": beta_state,
            "peRatio": _clean_numeric_val(raw_fund.get("peRatio")),
            "pegRatio": peg_val,
            "pegRatio_state": peg_state,
            "pcfRatio": pcf_val,
            "pcfRatio_state": pcf_state,
            "totalDebtToEquity_basis": "VENDOR_RAW_UNVERIFIED",
            "grossMarginTTM": gross_margin,
            "netProfitMarginTTM": net_margin,
            "operatingMarginTTM": op_margin,
            "margin_fields_suspect": margin_suspect,
            "margin_fields_suspect_reason": margin_suspect_reason,
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
            "divAmount": f"${div_amount:,.2f}" if div_amount is not None else "$0.00",
            "divFreq": div_freq if div_freq in ALLOWED_DIV_FREQS else 0.0,
            "div_freq_source": div_freq_source,
            "sharesOutstanding": shares_val,
            "shares_outstanding_state": shares_state,
            "marketCap": raw_mcap,  # PAY-61 Restored
            "marketCap_unit": "VENDOR_RAW_UNVERIFIED"
        },
        "step_3_and_7_derivatives": {
            "surface_parameters": {
                # PAY-59: Purged volatility_30d_surface legacy field
                "underlyingPrice": last_price or close_price
            },
            "short_locate_status": {
                "state": "FULL_PASSTHROUGH",
                "isShortable": raw_ref.get("isShortable", True),
                "isHardToBorrow": raw_ref.get("isHardToBorrow", False),
                "htbRate": _clean_numeric_val(raw_ref.get("htbRate")) or 0.0
            },
            "options_extraction_telemetry": {
                "rejected_zero_strike_count": 0,
                "rejected_expired_contract_count": 0,
                "rejected_negative_mark_count": 0,
                "rejected_negative_price_count": 0
            }
        },
        "step_8_and_9_liquidity_and_sizing": {
            "state": "PARTIAL_PASSTHROUGH",
            "bidPrice": f"${_clean_numeric_val(raw_quote.get('bidPrice')) or 0.0:,.2f}",
            "askPrice": f"${_clean_numeric_val(raw_quote.get('askPrice')) or 0.0:,.2f}",
            "bidSize": _clean_numeric_val(raw_quote.get("bidSize")),
            "askSize": _clean_numeric_val(raw_quote.get("askSize")),
            "totalVolume": _clean_numeric_val(raw_quote.get("totalVolume")),
            "vol10DayAvg_state": "AS_REPORTED",
            "vol3MonthAvg_state": "AS_REPORTED"
        }
    }