"""
schwab_instrument_classification.py
---
Purpose
Provides simple functions to categorize financial instruments based on the data provided by the Schwab API. It determines if an asset is a warrant, a mutual fund, an ETF/ETN, a foreign asset, or an American Depositary Receipt (ADR). It also classifies how recent a price quote is.

Prerequisites
None beyond standard Python libraries. The module relies on the `re` (regular expression) module to match specific patterns in ticker symbols or text descriptions.

What this module does
1. Identifies if a security is a warrant by checking its category, description, or ticker symbol format.
2. Identifies if a security is a mutual fund by checking its category or looking for the standard 5-letter ticker symbol ending in "X".
3. Identifies general fund types (ETFs, ETNs, etc.) by combining category checks with the mutual fund flag.
4. Uses text search in the asset's description to spot keywords related to pooled investments (like "TRUST", "PORTFOLIO", or "ETF").
5. Combines the fund flags to determine if the asset is a "structural wrapper" (a fund rather than a single company's stock).
6. Determines if the asset originates from a foreign country.
7. Identifies American Depositary Receipts (ADRs) representing foreign stocks traded in the US.
8. Provides a small helper function to safely check if a number is practically zero.
9. Classifies the age of a price quote into buckets like "REAL_TIME", "RECENT", or "STALE".

Configuration knobs
- Hardcoded ticker symbol patterns (e.g., ending in `.WS` for warrants, or `X` for mutual funds).
- Hardcoded lists of fund types (e.g., "ETF", "ETN", "CEF").
- Hardcoded list of country names in descriptions to flag foreign assets.
- Hardcoded time thresholds in seconds for classifying quote age (60s for real-time, 600s for recent, 3600s for delayed).
- A hardcoded threshold of `< 0.01` to define what counts as functionally zero.

Outputs
Provides a set of boolean (True/False) classification functions, one string-returning function (`classify_quote_age`), and one boolean helper (`functionally_zero`).

Notes
These functions were extracted verbatim from older, inline code (`schwab_raw_marketdata.py`) to preserve the exact original behavior without any logic changes. The logic relies heavily on string matching to handle inconsistencies in how the vendor categorizes different assets.
"""

# Enable modern type hinting features, allowing types to be used before they are defined
from __future__ import annotations

# Import the regular expression module for pattern matching in text (like looking for specific words in a description)
import re
# Import specific types from the typing module to help define what kind of data the functions expect and return
from typing import Any, Dict, Optional


# Define a function to determine if a financial asset is a warrant
def classify_warrant(
    asset_sub: str, asset_main: str, desc: str, clean_sym: str
) -> bool:
    # Return True if any of the following conditions are met:
    return (
        # The sub-asset type provided by the vendor is exactly "WARRANT" or "WARNT"
        asset_sub in ["WARRANT", "WARNT"]
        # Or the main asset type is exactly "WARRANT" or "WARNT"
        or asset_main in ["WARRANT", "WARNT"]
        # Or the text description contains the whole word "WARRANT", "WARNT", or "WRNT" (ignoring case usually, but regex here is uppercase)
        or bool(re.search(r"\b(WARRANT|WARNT|WRNT)\b", desc))
        # Or the stock symbol ends with a common warrant suffix like ".WS", "-WT", or is a 5-letter symbol ending in "WW"
        or bool(re.search(r"(\.WS|[\.\/\-\s]WS|\.WT|[\.\/\-\s]WT|^[A-Z]{3,4}WW)$", clean_sym))
    )


# Define a function to determine if an asset is a mutual fund
def classify_mutual_fund(
    asset_sub: str, asset_main: str, clean_sym: str
) -> bool:
    # Return True if any of the following conditions are met:
    return (
        # The sub-asset type is marked as a mutual fund or open-ended fund
        asset_sub in ["MUTUAL_FUND", "OPEN_END_FUND"]
        # Or the main asset type is marked as a mutual fund
        or asset_main in ["MUTUAL_FUND"]
        # Or the stock symbol consists of exactly 4 uppercase letters followed by an "X" (the standard format for mutual funds)
        or bool(re.search(r"^[A-Z]{4}X$", clean_sym))
    )


# Define a function to determine if an asset is some type of investment fund
def classify_fund_type(
    asset_sub: str, asset_main: str, mutual_fund_flag: bool
) -> bool:
    # Return True if any of the following conditions are met:
    return (
        # We already proved it is a mutual fund
        mutual_fund_flag
        # Or the sub-asset type indicates it's an ETF, ETN, Closed-End Fund (CEF), or Unit Investment Trust (UIT)
        or asset_sub in ["ETF", "ETN", "CEF", "UIT", "CLOSED_END_FUND"]
        # Or the main asset type generally describes a fund or collective investment
        or asset_main in ["ETF", "ETN", "FUND", "COLLECTIVE_INVESTMENT"]
    )


# Define a function to check the description for words indicating a pooled investment (like a fund)
def classify_desc_pooled_match(desc: str) -> bool:
    # Return True if the description contains any of these specific whole words or phrases indicating a fund structure
    return bool(
        re.search(
            r"\b(ETF|ETN|MUTUAL FUND|INDEX FUND|TRUST|INDEX|PORTFOLIO|ETRACS|TREASURY BOND|BOND FUND|ADMIRAL|INVESTOR CLASS)\b",
            desc,
        )
    )


# Define a function to classify if the asset is a structural wrapper (a container holding other assets, rather than a single stock)
def classify_structural_wrapper(
    warrant_flag: bool, fund_type_flag: bool, pooled_match: bool
) -> bool:
    # Return True only if it is NOT a warrant AND it has been flagged as either a fund type or has a matching pooled description
    return not warrant_flag and (fund_type_flag or pooled_match)


# Define a function to determine if the listed country code means it's a foreign asset
def classify_foreign_country(country: str) -> bool:
    # Return True if all of the following are met:
    return (
        # A country string was actually provided (not empty)
        bool(country)
        # And the string is exactly 2 or 3 uppercase letters
        and bool(re.match(r"^[A-Z]{2,3}$", country))
        # And the country code is not "US" or "USA"
        and (country not in ["US", "USA"])
    )


# Define a function to determine if the asset is a foreign American Depositary Receipt (ADR)
def classify_foreign_adr(
    desc: str,
    asset_sub: str,
    foreign_country_flag: bool,
) -> bool:
    # Return True if any of the following conditions are met:
    return (
        # The description contains the whole word "ADR"
        bool(re.search(r"\bADR\b", desc))
        # Or the sub-asset type is exactly "ADR"
        or asset_sub == "ADR"
        # Or we already determined it's from a foreign country
        or foreign_country_flag
        # Or the description contains the name of one of these specific major foreign countries
        or bool(
            re.search(
                r"\b(CHINA|ISRAEL|UNITED KINGDOM|BERMUDA|NETHERLANDS|GERMANY|SWITZERLAND|FRANCE|IRELAND|JAPAN|TAIWAN|BRAZIL|CANADA|KOREA|SOUTH AFRICA)\b",
                desc,
            )
        )
    )


# Define a simple helper function to see if a number is close enough to zero to be treated as zero
def functionally_zero(v: Optional[float]) -> bool:
    # Return True if the value is missing (None) or if its absolute value is less than one penny (0.01)
    return v is None or abs(v) < 0.01


# Define a function to categorize how old a price quote is into human-readable buckets
def classify_quote_age(q_age: Optional[float]) -> str:
    # If we actually have a number for the age in seconds
    if q_age is not None:
        # If the quote is less than or equal to 60 seconds old, return "REAL_TIME"
        return (
            "REAL_TIME"
            if q_age <= 60.0
            # Otherwise, evaluate the next bucket
            else (
                # If it's up to 10 minutes (600 seconds) old, return "RECENT"
                "RECENT"
                if q_age <= 600.0
                # If it's up to an hour (3600 seconds) old, return "DELAYED"; otherwise, if older than an hour, return "STALE"
                else ("DELAYED" if q_age <= 3600.0 else "STALE")
            )
        )
    # If the quote age is missing entirely (None), return "UNKNOWN"
    return "UNKNOWN"