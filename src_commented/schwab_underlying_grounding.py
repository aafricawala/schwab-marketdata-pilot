"""
schwab_underlying_grounding.py

Orchestrator: fetches the vendor quote envelope and assembles the canonical
phase_0 / step_1 / short_locate / liquidity grounding payload.

Inline classification and resolution blocks have been replaced by calls into
the pure resolvers (Batch 2). Bodies of those blocks are unchanged; only the
call sites differ. Statement order matches the original source order.

Extracted from schwab_raw_marketdata.py (no logic change).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict
from zoneinfo import ZoneInfo

from schwab_utils import safe_float, validate_symbol

from schwab_vendor_resilience import parse_client_response, retry_vendor_call
from schwab_grounding_schema import build_halted_grounding
from schwab_instrument_classification import (
    classify_desc_pooled_match,
    classify_foreign_adr,
    classify_foreign_country,
    classify_fund_type,
    classify_mutual_fund,
    classify_quote_age,
    classify_structural_wrapper,
    classify_warrant,
    functionally_zero,
)
from schwab_fundamental_resolvers import (
    resolve_dividend,
    resolve_margin_sanity,
    resolve_pe_eps,
    resolve_shares_outstanding,
)
from schwab_short_locate import resolve_short_locate
from schwab_liquidity_book import resolve_liquidity

logger = logging.getLogger("schwab_raw_marketdata")
logger.addHandler(logging.NullHandler())


def extract_strict_underlying_data(
    client: Any, symbol: str, tz_et: ZoneInfo
) -> Dict[str, Any]:
    clean_sym = validate_symbol(symbol)

    @retry_vendor_call(max_retries=3, base_delay=0.2)
    def _fetch_quote(sym: str) -> Any:
        return client.get_quote(sym)

    try:
        res_dict = parse_client_response(_fetch_quote(clean_sym))
    except Exception as e:
        logger.warning("Quote fetch raised for %s: %s", clean_sym, e)
        res_dict = None

    if not isinstance(res_dict, dict) or not res_dict:
        return build_halted_grounding(clean_sym, tz_et, None, None)

    candidate = (
        res_dict.get(clean_sym)
        or res_dict.get(symbol)
        or res_dict.get(symbol.lower())
        or res_dict
    )
    if isinstance(candidate, dict):
        if clean_sym in candidate and isinstance(candidate[clean_sym], dict):
            candidate = candidate[clean_sym]
        elif symbol in candidate and isinstance(candidate[symbol], dict):
            candidate = candidate[symbol]
    data = candidate if isinstance(candidate, dict) else {}

    if not data:
        return build_halted_grounding(clean_sym, tz_et, None, None)

    ref = data.get("reference", {}) if isinstance(data.get("reference"), dict) else {}
    quote = data.get("quote", {}) if isinstance(data.get("quote"), dict) else {}
    fund = data.get("fundamental", {}) if isinstance(data.get("fundamental"), dict) else {}
    asset_sub = str(ref.get("assetSubType", "") or "").upper()
    asset_main = str(ref.get("assetMainType", "") or "").upper()
    desc = str(ref.get("description", "") or "").upper()

    if not quote and not fund:
        return build_halted_grounding(clean_sym, tz_et, None, None)

    raw_shares = safe_float(fund.get("sharesOutstanding"))

    # --- Classification (Batch 2) — original source position ---
    is_warrant = classify_warrant(asset_sub, asset_main, desc, clean_sym)
    is_mutual_fund = classify_mutual_fund(asset_sub, asset_main, clean_sym)
    is_fund_type = classify_fund_type(asset_sub, asset_main, is_mutual_fund)
    desc_pooled_match = classify_desc_pooled_match(desc)
    is_structural_wrapper = classify_structural_wrapper(
        is_warrant, is_fund_type, desc_pooled_match
    )

    last_p = safe_float(quote.get("lastPrice"))
    close_p = safe_float(quote.get("closePrice"))
    q_time_raw = quote.get("quoteTime", 0)

    if q_time_raw:
        now_ts = datetime.now(timezone.utc).timestamp()
        quote_ts = q_time_raw / 1000.0
        q_time_iso = (
            datetime.fromtimestamp(quote_ts, tz=timezone.utc)
            .astimezone(tz_et)
            .isoformat()
        )
        q_age = max(0.0, round(now_ts - quote_ts, 2))
    else:
        q_time_iso = None
        q_age = None

    is_halted_or_unquoted = (
        (functionally_zero(last_p) and functionally_zero(close_p))
        or (desc == "" and last_p is None)
    )

    if is_halted_or_unquoted:
        q_class = "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
    else:
        q_class = classify_quote_age(q_age)

    raw_pe = safe_float(fund.get("peRatio"))
    raw_eps = safe_float(fund.get("eps"))
    raw_div_amt = safe_float(fund.get("divAmount"))
    raw_div_y = safe_float(fund.get("divYield"))
    raw_div_freq = safe_float(fund.get("divFreq"))

    country = str(
        ref.get("country")
        or quote.get("country")
        or fund.get("country")
        or ""
    ).strip().upper()
    is_foreign_country = classify_foreign_country(country)
    is_foreign_adr = classify_foreign_adr(desc, asset_sub, is_foreign_country)

    # --- Resolvers (Batch 2) ---
    shares_val, shares_state = resolve_shares_outstanding(
        raw_shares,
        is_halted_or_unquoted,
        is_warrant,
        is_structural_wrapper,
        is_foreign_adr,
    )

    pe_val, pe_state, eps_val, eps_state = resolve_pe_eps(
        raw_pe,
        raw_eps,
        is_halted_or_unquoted,
        is_warrant,
        is_structural_wrapper,
        is_foreign_adr,
    )

    raw_div_y, div_y_basis, raw_div_freq, div_freq_state = resolve_dividend(
        raw_div_y, raw_div_amt, raw_div_freq, is_halted_or_unquoted
    )

    net_m = safe_float(fund.get("netProfitMarginTTM"))
    op_m = safe_float(fund.get("operatingMarginTTM"))
    gross_m = safe_float(fund.get("grossMarginTTM"))

    margin_suspect, margin_reason, margin_state = resolve_margin_sanity(net_m, op_m)

    short_dict = resolve_short_locate(ref, quote, is_halted_or_unquoted)

    liq_dict = resolve_liquidity(quote, fund, is_mutual_fund, is_halted_or_unquoted)

    # --- Assembly tail (verbatim) ---
    fund_dict: Dict[str, Any] = {
        "beta": safe_float(fund.get("beta")),
        "beta_state": (
            "AS_REPORTED" if fund.get("beta") is not None else "VENDOR_UNAVAILABLE"
        ),
        "peRatio": pe_val,
        "peRatio_state": pe_state,
        "pegRatio": safe_float(fund.get("pegRatio")),
        "pegRatio_state": (
            "AS_REPORTED"
            if fund.get("pegRatio") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "pcfRatio": safe_float(fund.get("pcfRatio")),
        "pcfRatio_state": (
            "AS_REPORTED"
            if fund.get("pcfRatio") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "pbRatio": safe_float(fund.get("pbRatio")),
        "totalDebtToEquity": safe_float(fund.get("totalDebtToEquity")),
        "totalDebtToEquity_basis": "VENDOR_RAW_UNVERIFIED",
        "grossMarginTTM": gross_m,
        "netProfitMarginTTM": net_m,
        "operatingMarginTTM": op_m,
        "margin_fields_suspect": margin_suspect,
        "margin_fields_suspect_reason": margin_reason,
        "margin_fields_suspect_state": margin_state,
        "returnOnEquity": safe_float(fund.get("returnOnEquity")),
        "returnOnEquity_state": (
            "AS_REPORTED"
            if fund.get("returnOnEquity") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "returnOnAssets": safe_float(fund.get("returnOnAssets")),
        "returnOnAssets_state": (
            "AS_REPORTED"
            if fund.get("returnOnAssets") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "eps": eps_val,
        "eps_state": eps_state,
        "revChangeYear": safe_float(fund.get("revChangeYear")),
        "revChangeYear_state": (
            "AS_REPORTED"
            if fund.get("revChangeYear") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "divYield": raw_div_y if raw_div_y is not None else 0.0,
        "divYield_basis": div_y_basis,
        "divYield_raw": raw_div_y if raw_div_y is not None else 0.0,
        "divAmount": f"${raw_div_amt:.2f}" if raw_div_amt is not None else "$0.00",
        "div_amount_basis": "ANNUAL",
        "divFreq": raw_div_freq,
        "sharesOutstanding": shares_val,
        "shares_outstanding_state": shares_state,
        "marketCap": safe_float(fund.get("marketCap")),
        "marketCap_unit": "VENDOR_RAW_UNVERIFIED",
    }
    if div_freq_state:
        fund_dict["divFreq_state"] = div_freq_state

    return {
        "phase_0_grounding": {
            "symbol": clean_sym,
            "company_name": desc,
            "lastPrice": f"${last_p:.2f}" if last_p is not None else None,
            "closePrice": f"${close_p:.2f}" if close_p is not None else None,
            "quoteTime_ISO_ET": q_time_iso,
            "quote_age_seconds": q_age,
            "quote_age_classification": q_class,
        },
        "step_1_fundamentals": fund_dict,
        "short_locate_status": short_dict,
        "step_8_and_9_liquidity_and_sizing": liq_dict,
    }