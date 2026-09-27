"""
schwab_grounding_schema.py
---
Purpose
    This module creates a "fake" (synthetic) standardized data profile for a stock when the vendor fails to return real data, usually because the stock's trading is halted by the exchange or the ticker symbol doesn't exist. This prevents the rest of the application from crashing when trying to read missing data.

Prerequisites
    - Standard Python environment supporting typing and timezones.

What this module does
    1. Accepts a stock symbol, a timestamp, and an age measurement for a failed/halted quote.
    2. Builds a massive dictionary that exactly mimics the structure of a successful data pull.
    3. Fills every numerical field (like price, volume, and ratios) with `None` or `0.0`.
    4. Fills every status field with explicit error messages like "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED".
    5. Returns this synthetic dictionary so the program can safely process the failure.

Configuration knobs
    None. The schema structure and failure states are completely hardcoded.

Outputs
    Returns a multi-layered dictionary containing sections for:
    - `phase_0_grounding` (core price/time data)
    - `step_1_fundamentals` (company financial ratios)
    - `short_locate_status` (borrowing status)
    - `step_8_and_9_liquidity_and_sizing` (order book and volume)

Notes
    This is extracted directly from older code to keep the fake schema definition out of the main logic files.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations

# Import typing helpers to describe that variables can be Any type, Dictionaries, or Optional (might be None)
from typing import Any, Dict, Optional
# Import ZoneInfo to explicitly declare the timezone type used in the function signature
from zoneinfo import ZoneInfo

# Define the function that builds the fake data profile for a halted stock
def build_halted_grounding(
    # Accept the clean stock symbol
    clean_sym: str,
    # Accept the timezone object (unused in the logic, but kept for signature compatibility)
    tz_et: ZoneInfo,
    # Accept how old the failed quote request was (in seconds)
    q_age: Optional[float],
    # Accept the exact timestamp of when the request failed
    q_time_iso: Optional[str]
) -> Dict[str, Any]:

    # Return a massive dictionary that mimics the shape of a healthy data response
    return {
        # Section 0: The most basic price and timing data
        "phase_0_grounding": {
            "symbol": clean_sym,                     # The requested stock symbol
            "company_name": "",                      # Blank company name because we couldn't look it up
            "lastPrice": None,                       # No last price because it's halted
            "closePrice": None,                      # No closing price because it's halted
            "quoteTime_ISO_ET": q_time_iso,          # The timestamp of the failure
            "quote_age_seconds": q_age,              # How long ago the failure happened
            # An explicit flag telling the system the asset is halted
            "quote_age_classification": "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED",
        },
        # Section 1: Deep financial data (PE ratio, dividends, debt, etc.)
        "step_1_fundamentals": {
            "beta": None,                            # No beta (volatility metric) available
            "beta_state": "VENDOR_UNAVAILABLE",      # Note explaining why beta is missing
            "peRatio": None,                         # No PE Ratio available
            "peRatio_state": "VENDOR_UNAVAILABLE_ASSET_HALTED", # Note explaining PE ratio is missing due to halt
            "pegRatio": None,                        # No PEG Ratio
            "pegRatio_state": "VENDOR_UNAVAILABLE",  # Note
            "pcfRatio": None,                        # No Price-to-Cash-Flow ratio
            "pcfRatio_state": "VENDOR_UNAVAILABLE",  # Note
            "pbRatio": None,                         # No Price-to-Book ratio
            "totalDebtToEquity": None,               # No debt info
            "totalDebtToEquity_basis": "VENDOR_RAW_UNVERIFIED", # Note
            "grossMarginTTM": None,                  # No gross margin info
            "netProfitMarginTTM": None,              # No net profit margin info
            "operatingMarginTTM": None,              # No operating margin info
            "margin_fields_suspect": None,           # Flag for bad margin data is None
            "margin_fields_suspect_reason": None,    # No reason needed
            "margin_fields_suspect_state": "VENDOR_UNAVAILABLE_INPUTS_ABSENT", # Note explaining why margin checks failed
            "returnOnEquity": None,                  # No ROE
            "returnOnEquity_state": "VENDOR_UNAVAILABLE", # Note
            "returnOnAssets": None,                  # No ROA
            "returnOnAssets_state": "VENDOR_UNAVAILABLE", # Note
            "eps": None,                             # No Earnings Per Share
            "eps_state": "VENDOR_UNAVAILABLE_ASSET_HALTED", # Note explaining EPS is missing due to halt
            "revChangeYear": None,                   # No Revenue change
            "revChangeYear_state": "VENDOR_UNAVAILABLE", # Note
            "divYield": 0.0,                         # Dividend yield explicitly set to 0.0 instead of None to prevent math crashes
            "divYield_basis": "VENDOR_UNAVAILABLE",  # Note
            "divYield_raw": 0.0,                     # Raw dividend yield set to 0.0
            "divAmount": "$0.00",                    # Dividend amount set to a safe string of "$0.00"
            "div_amount_basis": "ANNUAL",            # Assume annual just to have a default
            "divFreq": 0.0,                          # Dividend frequency set to 0.0
            "sharesOutstanding": None,               # No shares outstanding info
            "shares_outstanding_state": "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED", # Note
            "marketCap": None,                       # No market cap info
            "marketCap_unit": "VENDOR_RAW_UNVERIFIED", # Note
        },
        # Section 2: Shorting data (can you borrow the stock to short it?)
        "short_locate_status": {
            "state": "UNKNOWN",                      # We don't know the short status
            "reason": "asset_halted_or_unquoted_locate_unavailable", # Reason is because it's halted
        },
        # Section 3: Liquidity and sizing (how many people are trying to buy/sell)
        "step_8_and_9_liquidity_and_sizing": {
            "state": "UNVERIFIED_EMPTY_ORDER_BOOK",  # Flag the order book as empty
            "bidPrice": None,                        # No buyers (bid)
            "askPrice": None,                        # No sellers (ask)
            "bidSize": 0.0,                          # Number of buyers is 0
            "askSize": 0.0,                          # Number of sellers is 0
            "totalVolume": 0.0,                      # Total volume traded today is 0
            "vol10DayAvg": None,                     # No 10-day volume average
            "vol10DayAvg_state": "VENDOR_UNAVAILABLE", # Note
            "vol3MonthAvg_state": "VENDOR_FIELD_NOT_PROVIDED", # Note explicitly that Schwab doesn't provide 3-month averages anyway
            "vol1YearAvg": None,                     # No 1-year volume average
            "vol1YearAvg_state": "VENDOR_UNAVAILABLE", # Note
            "reason": "asset_halted_or_unquoted",    # Core reason everything is empty
            "book_liquidity_note": "EMPTY_ORDER_BOOK_ASSET_HALTED", # Final summary note
        },
    }