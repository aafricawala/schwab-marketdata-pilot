"""
schwab_price_history.py
---
Purpose
    This module is responsible for retrieving past price data (often called "candles" or "bars") for a specific stock or asset. It handles asking the vendor for the data, retrying if the request fails, and filtering out bad or incomplete data.

Prerequisites
    - A valid Schwab client instance.
    - Configuration dictionary containing history parameters.

What this module does
    1. Validates the requested stock symbol.
    2. Reads configuration settings to figure out how far back to look and how detailed the data should be (e.g., 1 year of daily data).
    3. Builds the request arguments.
    4. Tries to fetch the data from the API up to 3 times if it fails.
    5. Parses the vendor's response.
    6. Filters out any price candles that are missing a valid 'open' or 'close' price.
    7. Returns the clean list of price candles, or an empty list if something goes wrong.

Configuration knobs
    Reads the following from the provided config dictionary:
    - HISTORICAL_PERIOD_TYPE (default: 'year')
    - HISTORICAL_PERIOD (default: 1)
    - HISTORICAL_FREQUENCY_TYPE (default: 'daily')
    - HISTORICAL_FREQUENCY (default: 1)
    - HISTORICAL_NEED_EXTENDED_HOURS (default: False)

Outputs
    Returns a list of dictionaries, where each dictionary represents a single price candle (with open, close, high, low, volume, etc.). Returns an empty list on failure.

Notes
    The inner function `_fetch_candles` is defined inside the main function so it can use the `retry_vendor_call` decorator while having access to the local variables.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations

# Import the standard logging library to record messages and errors
import logging
# Import typing helpers to describe that variables can be Any type, Dictionaries, or Lists
from typing import Any, Dict, List

# Import utility functions for safely turning data into numbers and validating stock ticker symbols
from schwab_utils import safe_float, validate_symbol
# Import resilience functions for reading vendor responses and automatically retrying failed calls
from schwab_vendor_resilience import parse_client_response, retry_vendor_call

# Create a logger specific to raw market data for this file to use
logger = logging.getLogger("schwab_raw_marketdata")
# Add a NullHandler so it doesn't print errors if no main logging is set up
logger.addHandler(logging.NullHandler())


# Define the main function that extracts price history, taking a client, a stock symbol, and a config dictionary, returning a list of dictionaries
def extract_in_memory_price_history(
    client: Any, symbol: str, config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    # Make sure the requested stock symbol is clean and valid (e.g., uppercase, no weird characters)
    clean_sym = validate_symbol(symbol)

    # Get the overarching period type (like 'year', 'month', 'day') from config, default to 'year'
    p_type = config.get("HISTORICAL_PERIOD_TYPE", "year")
    # Get the length of the overarching period (like '1' year) from config, default to 1
    p_val = config.get("HISTORICAL_PERIOD", 1)
    # Get the frequency type (how detailed the data is, like 'daily' or 'minute') from config, default to 'daily'
    f_type = config.get("HISTORICAL_FREQUENCY_TYPE", "daily")
    # Get the length of the frequency (like '1' day) from config, default to 1
    f_val = config.get("HISTORICAL_FREQUENCY", 1)
    # Get a true/false value on whether to include after-hours and pre-market trading, default to False
    ext_hrs = config.get("HISTORICAL_NEED_EXTENDED_HOURS", False)

    # Package all those settings into a dictionary of keyword arguments to easily pass to the API
    kwargs = {
        "period_type": p_type,  # Set the overarching period type
        "period": p_val,        # Set the length of that period
        "frequency_type": f_type, # Set how often a price candle is generated
        "frequency": f_val,     # Set the length of that frequency
        "need_extended_hours": ext_hrs, # Set whether to include after-hours trading
    }

    # Add a decorator to this inner helper function to make it retry up to 3 times, waiting 0.25 seconds between tries
    @retry_vendor_call(max_retries=3, base_delay=0.25)
    # Define a temporary inner function to actually make the API call
    def _fetch_candles() -> Any:
        # Call the client's get_price_history method with the clean symbol and unpack the keyword arguments we built above
        return client.get_price_history(clean_sym, **kwargs)

    # Start a block of code that might fail and need to be caught
    try:
        # Call our retry-enabled helper function to fetch the data
        r = _fetch_candles()
        # Parse the raw response from the vendor into a standard Python dictionary
        d = parse_client_response(r)
        # If the parsing worked and we have a dictionary
        if d:
            # Try to get the list of 'candles' from the dictionary, or default to an empty list if it's missing or None
            candles = d.get("candles", []) or []

            # Use a list comprehension to filter the candles and return the final clean list
            return [
                # Keep the candle 'c'
                c
                # For every candle 'c' in our list of candles
                for c in candles
                # ONLY IF we can successfully convert its 'close' price to a number (meaning it's not None/missing)
                if safe_float(c.get("close")) is not None
                # AND we can successfully convert its 'open' price to a number (meaning it's not None/missing)
                and safe_float(c.get("open")) is not None
            ]
    # Catch any data format errors (missing keys, wrong types, empty objects) that happen during parsing or filtering
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        # Log a warning that we failed to extract price history, including the stock symbol and the exact error
        logger.warning("Price history extraction encountered an error for %s: %s", clean_sym, e)

    # If the try block failed or the data was empty, return an empty list as a safe fallback
    return []