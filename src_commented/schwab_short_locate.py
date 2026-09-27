"""
schwab_short_locate.py
---
Purpose
    This module figures out if a stock can be shorted (sold without owning it) and how much it costs to do so. It looks through different parts of the vendor's data (like the reference data or the quote data) to find if the stock is "Shortable", if it is "Hard To Borrow" (HTB), and what the fee (rate) is for borrowing it.

Prerequisites
    - Requires `schwab_utils.safe_float` to safely convert rate numbers.

What this module does
    1. Looks for shorting information inside the 'reference' dictionary.
    2. If it's missing there, it falls back to looking in the 'quote' dictionary.
    3. Normalizes the 'isShortable' flag (True/False).
    4. Normalizes the 'isHardToBorrow' flag (True/False).
    5. Safely extracts the 'htbRate' (the cost to borrow).
    6. Checks if the stock is halted; if so, marks the short data as completely unavailable.
    7. Evaluates the data to generate a human-readable status string (e.g., 'LOCATE_AVAILABLE', 'NOT_APPLICABLE_ETB').
    8. Returns a dictionary containing all the normalized short-locate data.

Configuration knobs
    None.

Outputs
    Returns a dictionary containing:
    - The state of the data extraction ('FULL_PASSTHROUGH', 'PARTIAL_PASSTHROUGH', or 'UNKNOWN').
    - 'isShortable' (boolean).
    - 'isHardToBorrow' (boolean).
    - 'htbRate' (float or None).
    - 'htb_rate_status' (string describing the exact status of the rate).
    - Optionally, the raw rate if it was mathematically invalid (negative).

Notes
    The vendor's API is famously inconsistent about where it puts shorting data, which is why this module checks multiple places using a cascading fallback approach.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations

# Import typing helpers to describe that variables can be Any type or Dictionaries
from typing import Any, Dict

# Import a utility function to safely turn text/messy data into a clean decimal number
from schwab_utils import safe_float


# Define the main function that resolves short locate data, taking in reference data, quote data, and a halted flag
def resolve_short_locate(
    ref: Dict[str, Any],
    quote: Dict[str, Any],
    is_halted_or_unquoted: bool,
) -> Dict[str, Any]:

    # Try to grab the 'shortLocate' section from the reference data. If it's not there, try the quote data. Default to an empty dict.
    short_stat = ref.get("shortLocate", quote.get("shortLocate", {}))
    # If what we got back isn't actually a dictionary (maybe it was a string or None), force it to be an empty dictionary to prevent crashes
    if not isinstance(short_stat, dict):
        short_stat = {}

    # Figure out if the stock is shortable. First check 'ref', if it's there use it.
    is_shortable = (
        ref.get("isShortable")
        if ref.get("isShortable") is not None
        # If it's not in 'ref', try 'quote', and if it's not there, try the 'short_stat' dict we pulled earlier
        else quote.get("isShortable", short_stat.get("isShortable"))
    )

    # Figure out if the stock is Hard To Borrow. First check 'ref', if it's there use it.
    is_htb = (
        ref.get("isHardToBorrow")
        if ref.get("isHardToBorrow") is not None
        # If it's not in 'ref', try 'quote', and if it's not there, try 'short_stat'
        else quote.get("isHardToBorrow", short_stat.get("isHardToBorrow"))
    )

    # Safely extract the borrowing fee rate as a decimal number, checking 'ref', then 'quote', then 'short_stat'
    raw_htb_rate = safe_float(
        ref.get("htbRate", quote.get("htbRate", short_stat.get("rate")))
    )

    # Check if the stock is currently halted from trading entirely
    if is_halted_or_unquoted:
        # If it is halted, we can't short it anyway, so create a failure dictionary
        short_dict: Dict[str, Any] = {
            "state": "UNKNOWN",
            "reason": "asset_halted_or_unquoted_locate_unavailable",
        }
    # Check if we completely failed to find any of the three key pieces of shorting information
    elif is_shortable is None and is_htb is None and raw_htb_rate is None:
        # If we found absolutely nothing, create a failure dictionary explaining that the vendor didn't send the data
        short_dict = {
            "state": "UNKNOWN",
            "reason": "locate_data_not_reported_by_venue_or_tier",
        }
    # If we are not halted and we did find at least some data
    else:
        # Create a variable to hold the final rate we will use
        htb_rate_val = raw_htb_rate
        # Create a variable to hold the original raw rate in case we need to save it for debugging
        raw_htb_store = None

        # Check if the stock is explicitly NOT Hard To Borrow (Easy To Borrow / ETB)
        if is_htb is False:
            # Set the status string accordingly
            htb_status = "NOT_APPLICABLE_ETB"
        # Check if we didn't get an answer on whether it's Hard To Borrow
        elif is_htb is None:
            # Set the status string to say we are waiting on the vendor
            htb_status = "VENDOR_UNAVAILABLE_LOCATE_PENDING"
        # Check if the rate we got is mathematically impossible (less than zero percent)
        elif raw_htb_rate is not None and raw_htb_rate < 0.0:
            # Set the status string to flag this as a vendor error
            htb_status = "INVALID_NEGATIVE_VENDOR_RATE"
            # Move the bad negative rate into the storage variable, and set the final rate to None to protect downstream math
            raw_htb_store, htb_rate_val = raw_htb_rate, None
        # Check if the stock IS Hard To Borrow, but the rate is exactly zero (which usually means the broker is still calculating it)
        elif raw_htb_rate == 0.0:
            # Set the status string to indicate we need to wait for the broker to find shares
            htb_status = "HTB_FLAG_ACTIVE_RATE_PENDING_BROKER_LOCATE"
        # If we got a valid, positive rate number
        elif raw_htb_rate is not None:
            # Set the status string to say everything is good to go
            htb_status = "LOCATE_AVAILABLE"
        # If none of the above conditions met, it means we don't have a rate at all
        else:
            # Set the status string to say we are waiting on the vendor
            htb_status = "VENDOR_UNAVAILABLE_LOCATE_PENDING"

        # Construct the final dictionary of short locate data
        short_dict = {
            # Mark it FULL_PASSTHROUGH if we found both flags, otherwise PARTIAL_PASSTHROUGH
            "state": (
                "FULL_PASSTHROUGH"
                if all(v is not None for v in [is_shortable, is_htb])
                else "PARTIAL_PASSTHROUGH"
            ),
            # Set the shortable flag, defaulting to True if the vendor didn't tell us otherwise
            "isShortable": bool(is_shortable) if is_shortable is not None else True,
            # Set the HTB flag, defaulting to False if the vendor didn't tell us otherwise
            "isHardToBorrow": bool(is_htb) if is_htb is not None else False,
            # Set the final safe fee rate we determined above
            "htbRate": htb_rate_val,
            # Set the descriptive status string we determined above
            "htb_rate_status": htb_status,
        }
        # If we stored a bad raw rate earlier
        if raw_htb_store is not None:
            # Add it to the dictionary under a separate key so developers can see the error
            short_dict["htbRate_raw"] = raw_htb_store

    # Return the completely built dictionary back to the caller
    return short_dict