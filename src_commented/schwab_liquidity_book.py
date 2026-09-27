"""
schwab_liquidity_book.py

Order-book / liquidity state resolver: bid-ask depth, volume, and averages
with mutual-fund and halted special-casing.

Extracted verbatim from schwab_raw_marketdata.py (no logic change).
"""
from __future__ import annotations

from typing import Any, Dict

from schwab_utils import safe_float


def resolve_liquidity(
    quote: Dict[str, Any],
    fund: Dict[str, Any],
    is_mutual_fund: bool,
    is_halted_or_unquoted: bool,
) -> Dict[str, Any]:
    bid_p = safe_float(quote.get("bidPrice"))
    ask_p = safe_float(quote.get("askPrice"))
    bid_s = safe_float(quote.get("bidSize", 0.0))
    ask_s = safe_float(quote.get("askSize", 0.0))
    tot_vol = safe_float(quote.get("totalVolume", 0.0))

    liq_state = "FULL_PASSTHROUGH"
    book_note, book_reason, spread_warn = None, None, None

    if is_mutual_fund:
        liq_state = "NOT_APPLICABLE_MUTUAL_FUND_NO_INTRADAY_BOOK"
        book_reason = "mutual_fund_nav_priced_once_daily"
        book_note = "NO_INTRADAY_ORDER_BOOK_MUTUAL_FUND"
    elif is_halted_or_unquoted:
        liq_state = "UNVERIFIED_EMPTY_ORDER_BOOK"
        book_reason = "asset_halted_or_unquoted"
        book_note = "EMPTY_ORDER_BOOK_ASSET_HALTED"
    elif bid_s == 0.0 and ask_s == 0.0:
        liq_state = "UNVERIFIED_EMPTY_ORDER_BOOK"
        if tot_vol is not None and tot_vol > 0.0:
            book_reason = "zero_bid_ask_depth_with_reported_volume"
            book_note = "ZERO_BID_ASK_DEPTH_REPORTED"
        else:
            book_reason = "zero_book_activity_recorded"
            book_note = "EMPTY_ORDER_BOOK_NO_VOLUME"

    if bid_p is not None and ask_p is not None and bid_p > 0.0:
        if (ask_p - bid_p) / bid_p > 2.0:
            spread_warn = "EXTREME_SPREAD_EXCEEDS_200_PCT_HEURISTIC"

    liq_dict: Dict[str, Any] = {
        "state": liq_state,
        "bidPrice": f"${bid_p:.2f}" if bid_p is not None else None,
        "askPrice": f"${ask_p:.2f}" if ask_p is not None else None,
        "bidSize": bid_s,
        "askSize": ask_s,
        "totalVolume": tot_vol,
        "vol10DayAvg": safe_float(fund.get("vol10DayAvg")),
        "vol10DayAvg_state": (
            "AS_REPORTED"
            if fund.get("vol10DayAvg") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "vol3MonthAvg_state": "VENDOR_FIELD_NOT_PROVIDED",
        "vol1YearAvg": safe_float(fund.get("vol1YearAvg")),
        "vol1YearAvg_state": (
            "VENDOR_SUSPECT_ZERO"
            if fund.get("vol1YearAvg") == 0.0
            else (
                "AS_REPORTED"
                if fund.get("vol1YearAvg") is not None
                else "VENDOR_UNAVAILABLE"
            )
        ),
    }
    if book_reason:
        liq_dict["reason"] = book_reason
    if book_note:
        liq_dict["book_liquidity_note"] = book_note
    if spread_warn:
        liq_dict["spread_warning"] = spread_warn

    return liq_dict