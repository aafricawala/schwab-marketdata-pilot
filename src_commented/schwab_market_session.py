"""
schwab_market_session.py
---
Purpose
    This module determines if the stock market (specifically the equity market) is currently open for trading. It first tries to ask the vendor (Schwab) directly, and if that fails, it falls back to checking the current time in New York.

Prerequisites
    - A valid Schwab client instance to query the API.
    - Python environment must support `zoneinfo` for timezone calculations.

What this module does
    1. Sends a request to the Schwab API to ask for current equity market hours.
    2. Parses the response to see if the 'isOpen' flag is set to true.
    3. If the API fails or returns unexpected data, it logs a warning.
    4. As a backup, checks the current Eastern Time (New York time).
    5. Returns false if it's the weekend, otherwise returns true only if the current time is between 9:30 AM and 4:00 PM Eastern.

Configuration knobs
    - max_retries: Hardcoded to 2 for the vendor call.
    - base_delay: Hardcoded to 0.1 seconds between retries.
    - Timezone: Hardcoded to 'America/New_York' for the fallback check.

Outputs
    Produces a single boolean value (`True` if the market is open, `False` if it is closed).

Notes
    The fallback logic (checking the clock) does not account for market holidays. It assumes every Monday through Friday is a regular trading day.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations

# Import the standard logging library to record messages and errors
import logging
# Import datetime objects for working with current dates and times in UTC
from datetime import datetime, timezone
# Import Any to allow type hints for variables that can be of any type
from typing import Any
# Import ZoneInfo to correctly calculate times in specific global timezones (like New York)
from zoneinfo import ZoneInfo

# Import the function that reads and understands what the vendor sent back
# Import the function that automatically tries again if a vendor call fails
from schwab_vendor_resilience import parse_client_response, retry_vendor_call

# Create a logger specific to raw market data for this file to use
logger = logging.getLogger("schwab_raw_marketdata")
# Add a NullHandler so it doesn't print errors if no main logging is set up
logger.addHandler(logging.NullHandler())


# Add a decorator that tells this function to try up to 2 times (with a 0.1s delay) if it fails
@retry_vendor_call(max_retries=2, base_delay=0.1)
# Define the function that checks if the market is open, accepting a client object and returning a True/False boolean
def extract_market_open_status(client: Any) -> bool:
    # Start a block of code that might fail and need to be caught
    try:
        # Ask the client for the current market hours specifically for the 'equity' (stock) market
        r = client.get_market_hours("equity")
        # Read the raw response and turn it into a standard Python dictionary
        d = parse_client_response(r)
        # If the response dictionary actually contains data
        if d:
            # Grab the 'equity' section of the response (defaulting to an empty dictionary if missing)
            eq = d.get("equity", {})
            # Loop through the possible names the API might use for the equity market ("EQ" or "equity")
            for m in ["EQ", "equity"]:
                # If we found one of those names in the data, and it has an 'isOpen' status
                if m in eq and "isOpen" in eq[m]:
                    # Convert that status to a true/false boolean and return it immediately
                    return bool(eq[m]["isOpen"])
    # If anything goes wrong (like missing keys, bad data types, or empty objects)
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        # Log a warning message saying we couldn't figure it out from the API, including the error details
        logger.warning("Could not resolve market open status via client: %s", e)

    # Get the exact current time in UTC, and then convert it to New York time (Eastern Time)
    now_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
    # Check if the current day of the week is 5 (Saturday) or 6 (Sunday)
    if now_et.weekday() >= 5:
        # If it is the weekend, the market is definitely closed, so return False
        return False
    # If it's a weekday, return True only if the time is exactly 9:30 AM or later, BUT strictly before 4:00 PM
    return (9, 30) <= (now_et.hour, now_et.minute) < (16, 0)
