"""
schwab_liquidity_book.py
---
Purpose
    This module analyzes the "Order Book" or "Liquidity" of a stock. It looks at how many shares people are trying to buy (the bid) and sell (the ask), as well as total trading volume. It has special rules built in for Mutual Funds (which don't trade intraday) and halted stocks.

Prerequisites
    - Requires `schwab_utils.safe_float` to safely convert raw text data to decimal numbers.

What this module does
    1. Extracts the current bid price, ask price, bid size (number of shares wanted), and ask size (number of shares offered).
    2. Extracts the total volume traded today.
    3. Evaluates specific scenarios that affect liquidity:
        - If it's a Mutual Fund, notes that intraday trading doesn't happen.
        - If it's halted, notes that the order book is empty.
        - If sizes are exactly 0, evaluates if it's because of zero volume or just an empty order book.
    4. Checks for an extremely wide "spread" (the gap between the bid and ask price). If the ask is more than 200% higher than the bid, it triggers a warning flag.
    5. Formats all the prices and volume data neatly into a dictionary.
    6. Extracts 10-day and 1-year historical volume averages and assigns status labels to them.

Configuration knobs
    None. The 2.0 (200%) threshold for extreme spread warnings is hardcoded.

Outputs
    Returns a dictionary containing:
    - The state of the liquidity data ('FULL_PASSTHROUGH', 'UNVERIFIED_EMPTY_ORDER_BOOK', etc.).
    - Formatted string versions of bidPrice and askPrice (e.g., "$10.50").
    - Raw decimal numbers for bidSize, askSize, and totalVolume.
    - Historical volume averages and their states.
    - Optional notes, reasons, and warnings if triggered by the logic above.

Notes
    The `vol3MonthAvg_state` is hardcoded to "VENDOR_FIELD_NOT_PROVIDED" because the Schwab API does not supply a 3-month average volume metric.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations

# Import typing helpers to describe that variables can be Any type or Dictionaries
from typing import Any, Dict

# Import a utility function to safely turn text/messy data into a clean decimal number
from schwab_utils import safe_float


# Define the main function that resolves liquidity data
def resolve_liquidity(
    # Accept the 'quote' dictionary containing current prices and sizes
    quote: Dict[str, Any],
    # Accept the 'fund' dictionary containing historical volume averages
    fund: Dict[str, Any],
    # Accept a true/false flag indicating if the asset is a Mutual Fund
    is_mutual_fund: bool,
    # Accept a true/false flag indicating if the asset is halted from trading
    is_halted_or_unquoted: bool,
) -> Dict[str, Any]:

    # Safely extract the bid price (what buyers are offering)
    bid_p = safe_float(quote.get("bidPrice"))
    # Safely extract the ask price (what sellers are demanding)
    ask_p = safe_float(quote.get("askPrice"))
    # Safely extract the bid size (how many shares buyers want), defaulting to 0.0
    bid_s = safe_float(quote.get("bidSize", 0.0))
    # Safely extract the ask size (how many shares sellers have), defaulting to 0.0
    ask_s = safe_float(quote.get("askSize", 0.0))
    # Safely extract the total volume traded today, defaulting to 0.0
    tot_vol = safe_float(quote.get("totalVolume", 0.0))

    # Assume by default that the data is perfectly fine and passing through fully
    liq_state = "FULL_PASSTHROUGH"
    # Initialize variables to hold optional warnings and notes, setting them to None by default
    book_note, book_reason, spread_warn = None, None, None

    # Check if the asset is a Mutual Fund
    if is_mutual_fund:
        # Mutual funds don't have active intraday order books, they price once a day at the end of the day. Set the state to reflect this.
        liq_state = "NOT_APPLICABLE_MUTUAL_FUND_NO_INTRADAY_BOOK"
        # Provide the technical reason
        book_reason = "mutual_fund_nav_priced_once_daily"
        # Provide a general note
        book_note = "NO_INTRADAY_ORDER_BOOK_MUTUAL_FUND"
    # If not a mutual fund, check if it's halted or unquoted
    elif is_halted_or_unquoted:
        # A halted stock has no active order book. Set the state to reflect this.
        liq_state = "UNVERIFIED_EMPTY_ORDER_BOOK"
        # Provide the technical reason
        book_reason = "asset_halted_or_unquoted"
        # Provide a general note
        book_note = "EMPTY_ORDER_BOOK_ASSET_HALTED"
    # If it's active and not a mutual fund, check if both the bid size and ask size are exactly zero
    elif bid_s == 0.0 and ask_s == 0.0:
        # Set the state to reflect an empty order book
        liq_state = "UNVERIFIED_EMPTY_ORDER_BOOK"
        # Check if there is actual volume reported despite the empty book (happens in after-hours or glitchy data)
        if tot_vol is not None and tot_vol > 0.0:
            # Provide a specific reason explaining this discrepancy
            book_reason = "zero_bid_ask_depth_with_reported_volume"
            book_note = "ZERO_BID_ASK_DEPTH_REPORTED"
        # If there is no volume either
        else:
            # Provide a reason explaining that there is just no activity at all
            book_reason = "zero_book_activity_recorded"
            book_note = "EMPTY_ORDER_BOOK_NO_VOLUME"

    # Check if we have valid bid and ask prices, and ensure the bid price is greater than zero to prevent dividing by zero
    if bid_p is not None and ask_p is not None and bid_p > 0.0:
        # Calculate the "spread" (ask minus bid) as a percentage of the bid. If the spread is greater than 200% (2.0):
        if (ask_p - bid_p) / bid_p > 2.0:
            # Trigger a warning flag indicating an extremely wide and risky spread
            spread_warn = "EXTREME_SPREAD_EXCEEDS_200_PCT_HEURISTIC"

    # Construct the final dictionary of liquidity data
    liq_dict: Dict[str, Any] = {
        # The main state we determined above
        "state": liq_state,
        # Format the bid price to have exactly 2 decimal places and a dollar sign, or leave as None if it doesn't exist
        "bidPrice": f"${bid_p:.2f}" if bid_p is not None else None,
        # Format the ask price to have exactly 2 decimal places and a dollar sign, or leave as None
        "askPrice": f"${ask_p:.2f}" if ask_p is not None else None,
        # The raw bid size number
        "bidSize": bid_s,
        # The raw ask size number
        "askSize": ask_s,
        # The raw total volume number
        "totalVolume": tot_vol,
        # Safely extract the 10-day volume average from the fundamental data
        "vol10DayAvg": safe_float(fund.get("vol10DayAvg")),
        # Set the state of the 10-day average: 'AS_REPORTED' if it exists, otherwise 'VENDOR_UNAVAILABLE'
        "vol10DayAvg_state": (
            "AS_REPORTED"
            if fund.get("vol10DayAvg") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        # Hardcode the 3-month state to indicate the vendor never provides it
        "vol3MonthAvg_state": "VENDOR_FIELD_NOT_PROVIDED",
        # Safely extract the 1-year volume average
        "vol1YearAvg": safe_float(fund.get("vol1YearAvg")),
        # Set the state of the 1-year average:
        "vol1YearAvg_state": (
            # Flag it as suspect if the vendor reported exactly 0.0 for a whole year of volume
            "VENDOR_SUSPECT_ZERO"
            if fund.get("vol1YearAvg") == 0.0
            else (
                # Otherwise, 'AS_REPORTED' if it exists, or 'VENDOR_UNAVAILABLE' if it doesn't
                "AS_REPORTED"
                if fund.get("vol1YearAvg") is not None
                else "VENDOR_UNAVAILABLE"
            )
        ),
    }

    # If we generated a reason during the checks, add it to the final dictionary
    if book_reason:
        liq_dict["reason"] = book_reason
    # If we generated a note during the checks, add it to the final dictionary
    if book_note:
        liq_dict["book_liquidity_note"] = book_note
    # If we triggered the extreme spread warning, add it to the final dictionary
    if spread_warn:
        liq_dict["spread_warning"] = spread_warn

    # Return the completely built dictionary back to the caller
    return liq_dict