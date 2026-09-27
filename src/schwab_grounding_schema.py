"""
schwab_grounding_schema.py

Canonical synthetic grounding payload for empty / malformed / halted quote envelopes.
Extracted verbatim from schwab_raw_marketdata.py (no logic change).
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo


def build_halted_grounding(
    clean_sym: str, tz_et: ZoneInfo, q_age: Optional[float], q_time_iso: Optional[str]
) -> Dict[str, Any]:
    """Synthetic halted/unquoted grounding payload for empty or malformed quote envelopes."""
    return {
        "phase_0_grounding": {
            "symbol": clean_sym,
            "company_name": "",
            "lastPrice": None,
            "closePrice": None,
            "quoteTime_ISO_ET": q_time_iso,
            "quote_age_seconds": q_age,
            "quote_age_classification": "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED",
        },
        "step_1_fundamentals": {
            "beta": None,
            "beta_state": "VENDOR_UNAVAILABLE",
            "peRatio": None,
            "peRatio_state": "VENDOR_UNAVAILABLE_ASSET_HALTED",
            "pegRatio": None,
            "pegRatio_state": "VENDOR_UNAVAILABLE",
            "pcfRatio": None,
            "pcfRatio_state": "VENDOR_UNAVAILABLE",
            "pbRatio": None,
            "totalDebtToEquity": None,
            "totalDebtToEquity_basis": "VENDOR_RAW_UNVERIFIED",
            "grossMarginTTM": None,
            "netProfitMarginTTM": None,
            "operatingMarginTTM": None,
            "margin_fields_suspect": None,
            "margin_fields_suspect_reason": None,
            "margin_fields_suspect_state": "VENDOR_UNAVAILABLE_INPUTS_ABSENT",
            "returnOnEquity": None,
            "returnOnEquity_state": "VENDOR_UNAVAILABLE",
            "returnOnAssets": None,
            "returnOnAssets_state": "VENDOR_UNAVAILABLE",
            "eps": None,
            "eps_state": "VENDOR_UNAVAILABLE_ASSET_HALTED",
            "revChangeYear": None,
            "revChangeYear_state": "VENDOR_UNAVAILABLE",
            "divYield": 0.0,
            "divYield_basis": "VENDOR_UNAVAILABLE",
            "divYield_raw": 0.0,
            "divAmount": "$0.00",
            "div_amount_basis": "ANNUAL",
            "divFreq": 0.0,
            "sharesOutstanding": None,
            "shares_outstanding_state": "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED",
            "marketCap": None,
            "marketCap_unit": "VENDOR_RAW_UNVERIFIED",
        },
        "short_locate_status": {
            "state": "UNKNOWN",
            "reason": "asset_halted_or_unquoted_locate_unavailable",
        },
        "step_8_and_9_liquidity_and_sizing": {
            "state": "UNVERIFIED_EMPTY_ORDER_BOOK",
            "bidPrice": None,
            "askPrice": None,
            "bidSize": 0.0,
            "askSize": 0.0,
            "totalVolume": 0.0,
            "vol10DayAvg": None,
            "vol10DayAvg_state": "VENDOR_UNAVAILABLE",
            "vol3MonthAvg_state": "VENDOR_FIELD_NOT_PROVIDED",
            "vol1YearAvg": None,
            "vol1YearAvg_state": "VENDOR_UNAVAILABLE",
            "reason": "asset_halted_or_unquoted",
            "book_liquidity_note": "EMPTY_ORDER_BOOK_ASSET_HALTED",
        },
    }