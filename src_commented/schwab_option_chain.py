"""
schwab_option_chain.py

Purpose:
This module is responsible for retrieving and processing option chain data from the Schwab API.
It discovers available option expirations, selects the optimal expiration dates based on timeframes,
and extracts option contracts into memory. It handles both targeted specific expirations and falls
back to a default chain if needed, tracking any rejected invalid contracts.

Prerequisites:
- A configured `client` object capable of making Schwab API calls (e.g., `get_option_expirations`, `get_option_chain`).
- The `schwab_utils` module for safe type conversion and symbol validation.
- The `schwab_vendor_resilience` module for parsing responses and retrying failed API calls.

What this module does:
1. Validates and cleans the given stock symbol.
2. Fetches a list of available option expirations for the symbol from the API.
3. Analyzes the expirations to pick the most relevant ones (e.g., nearest term, around 30 days, and further out).
4. Retrieves the full option chains for these selected expirations.
5. Parses the API responses to extract call and put contracts, filtering out invalid data (e.g., negative prices, zero strikes).
6. Falls back to fetching a general, default option chain if targeted fetching fails.
7. Tracks and returns telemetry data about how many contracts were rejected and why.

Configuration knobs:
- `strike_window`: Number of strikes to fetch around the current price (default: 14).
- `strategy`: The options strategy to use when fetching the chain (default: "SINGLE").
- `strike_proximities`: Whether to consider strike proximity (default: True).
- API call retry settings (e.g., `max_retries=2`, `base_delay=0.2`).

Outputs:
- A list of dictionary objects representing available option expirations.
- A list of dictionary objects representing the optimal selected expirations.
- A tuple containing:
    - The 30-day volatility (float or None).
    - The underlying stock price (float or None).
    - A list of dictionaries, where each dictionary is a parsed option contract.
    - A telemetry dictionary tracking rejections and fallback status.

Notes:
- It ignores invalid option contracts during parsing, keeping counts of rejected contracts for monitoring.
- The module relies on closures for parsing and fetching data, maintaining variables in the outer function scope.
"""
# Enable modern Python type hint features even in older versions of Python.
from __future__ import annotations

# Import the logging library to output warnings and information.
import logging
# Import the datetime library to work with dates and times.
from datetime import datetime
# Import typing helpers to describe data structures and function signatures.
from typing import Any, Dict, List, Optional, Tuple

# Import custom utility functions for safe number conversion and symbol checking.
from schwab_utils import safe_float, validate_symbol
# Import resilience tools for handling API errors and retrying failed requests.
from schwab_vendor_resilience import parse_client_response, retry_vendor_call

# Set up a logger specifically for this module's output.
logger = logging.getLogger("schwab_raw_marketdata")
# Add a null handler to prevent logging errors if no other handlers are configured.
logger.addHandler(logging.NullHandler())


# Define a function to get available option expirations for a given stock symbol.
def extract_in_memory_option_expirations(
    # Accept an API client object and a stock symbol string.
    client: Any, symbol: str
# Declare that this function returns a list of dictionaries.
) -> List[Dict[str, Any]]:
    # Clean and validate the provided stock symbol.
    clean_sym = validate_symbol(symbol)

    # Decorate the inner function to automatically retry the API call up to 2 times with a 0.2 second initial delay if it fails.
    @retry_vendor_call(max_retries=2, base_delay=0.2)
    # Define an inner function that actually makes the API call to get the expirations.
    def _fetch_expirations() -> Any:
        # Loop through possible method names the client object might use to fetch expirations.
        for m in ["get_option_expirations", "get_option_expiration_chain"]:
            # Check if the client object has a method with the current name.
            if hasattr(client, m):
                # If it does, call that method with the cleaned symbol and return the result.
                return getattr(client, m)(clean_sym)
        # If neither method is found on the client, return None indicating failure.
        return None

    # Start a try block to catch potential errors.
    try:
        # Execute the inner function to fetch the raw API response for expirations.
        r = _fetch_expirations()
        # Parse the raw API response into a Python dictionary, handling potential errors.
        d = parse_client_response(r)
        # Check if the parsed response is not empty or None.
        if d:
            # Extract the 'expirationList' from the dictionary; return an empty list if it's missing or evaluates to false.
            return d.get("expirationList", []) or []
    # Catch common errors that might occur during data fetching, parsing, or extraction.
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        # Log a warning message indicating that fetching expirations failed for the specific symbol, along with the error.
        logger.warning("Option expirations query encountered an error for %s: %s", clean_sym, e)
    # If any error occurred or no data was found, return an empty list as a safe fallback.
    return []


# Define a function to select a subset of optimal expiration dates from a full list of expirations.
def resolve_optimal_expirations(
    # Accept a list of expiration dictionaries.
    exp_list: List[Dict[str, Any]],
# Declare that this function returns a list of dictionaries.
) -> List[Dict[str, Any]]:
    # Create a new list containing only valid expiration entries.
    valid = [
        # Include the expiration entry 'e'...
        e
        # ...by iterating through every entry in the provided list of expirations.
        for e in exp_list
        # ...but only if the 'daysToExpiration' value exists and can be safely converted to a number.
        if safe_float(e.get("daysToExpiration")) is not None
        # ...and if that number of days until expiration is zero or greater (meaning it hasn't already expired).
        and int(e["daysToExpiration"]) >= 0
    # Close the list comprehension.
    ]
    # Check if the list of valid expirations is empty.
    if not valid:
        # If there are no valid expirations, return an empty list.
        return []
    # Sort the list of valid expirations in ascending order based on the number of days to expiration.
    sorted_exps = sorted(valid, key=lambda x: int(x["daysToExpiration"]))
    # Select the expiration date that is closest in time (the first one in the sorted list).
    front = sorted_exps[0]
    # Create a list of 'candidate' expirations that expire in 30 days or less.
    t1_cands = [e for e in sorted_exps if int(e["daysToExpiration"]) <= 30]
    # Create a list of 'candidate' expirations that expire in 30 days or more.
    t2_cands = [e for e in sorted_exps if int(e["daysToExpiration"]) >= 30]
    # Select target 1 (t1): the expiration closest to, but not exceeding, 30 days.
    t1 = t1_cands[-1] if t1_cands else sorted_exps[0]
    # Select target 2 (t2): the expiration closest to, but not less than, 30 days.
    t2 = t2_cands[0] if t2_cands else sorted_exps[-1]
    # Combine the three selected targets into a single list.
    targets = [front, t1, t2]
    # Initialize an empty set 'seen' to keep track of dates we've added, and an empty list 'uniq' for the final unique targets.
    seen, uniq = set(), []
    # Loop through our list of chosen target expirations.
    for t in targets:
        # Get the actual expiration date string to use as a unique key.
        k = t.get("expirationDate")
        # Check if we haven't already added this expiration date to our unique list.
        if k not in seen:
            # If it's new, add the date key to the 'seen' set.
            seen.add(k)
            # And append the full expiration object to our unique list.
            uniq.append(t)
    # Return the final list containing up to three unique, strategically chosen expiration dates.
    return uniq


# Define a function to fetch full option chains for specific target expirations, or fall back to a default chain.
def extract_in_memory_option_chains(
    # The API client object.
    client: Any,
    # The target stock symbol.
    symbol: str,
    # The list of target expirations to fetch chains for.
    target_expirations: List[Dict[str, Any]],
    # The number of strikes to fetch.
    strike_window: int = 14,
    # The strategy type.
    strategy: str = "SINGLE",
    # Whether to use proximities.
    strike_proximities: bool = True,
# Returns a tuple containing multiple elements.
) -> Tuple[
    # The return types: volatility, underlying price, contracts list, and telemetry dict.
    Optional[float], Optional[float], List[Dict[str, Any]], Dict[str, Any]
]:
    # Clean and validate the provided stock symbol.
    clean_sym = validate_symbol(symbol)
    # Initialize a telemetry dictionary to keep statistics on data processing, such as why certain contracts were rejected.
    telemetry: Dict[str, Any] = {
        # Counter for contracts rejected because their strike price was zero or missing.
        "rejected_zero_strike_count": 0,
        # Counter for contracts rejected because they have already expired.
        "rejected_expired_contract_count": 0,
        # Counter for contracts rejected because their mark (midpoint) price was negative.
        "rejected_negative_mark_count": 0,
        # Counter for contracts rejected because their bid or ask price was negative.
        "rejected_negative_price_count": 0,
        # A flag to indicate whether the targeted fetch failed and the system had to request a generic chain instead.
        "fallback_to_default_chain": False,
    }

    # Initialize an empty list to store all the valid option contracts we parse from the API.
    all_contracts: List[Dict[str, Any]] = []
    # Initialize a variable to hold the price of the underlying stock; it starts as None.
    underlying_price = None
    # Initialize a variable to hold the 30-day volatility metric; it starts as None.
    vol_30d = None

    # Define an inner function that parses the raw API payload containing the option chain data.
    def _parse_chain_payload(payload: Dict[str, Any], provenance: str = "TARGETED_EXPIRATION") -> None:
        # Declare that this inner function will modify the variables defined in the outer scope.
        nonlocal underlying_price, vol_30d
        # If we haven't found the underlying price yet...
        if underlying_price is None:
            # ...try to extract it from the payload, converting it safely to a float.
            underlying_price = safe_float(payload.get("underlyingPrice"))
        # Similarly, if we haven't found the volatility metric yet...
        if vol_30d is None:
            # ...try to extract it from the payload.
            vol_30d = safe_float(payload.get("volatility"))
        # Loop over the two main sections of the payload: calls and puts, setting a default indicator for each.
        for book_key, default_indicator in [("callExpDateMap", "CALL"), ("putExpDateMap", "PUT")]:
            # Extract the specific book (calls or puts) from the payload; default to an empty dictionary if missing.
            book = payload.get(book_key, {})
            # Iterate through each expiration date within that book.
            for date_key, strikes in book.items():
                # For each expiration date, iterate through the available strike prices.
                for strike_key, contract_list in strikes.items():
                    # Finally, iterate through the list of contracts at that specific strike price (usually just one).
                    for c in contract_list:
                        # Safely extract the strike price of the current contract as a float.
                        s_val = safe_float(c.get("strikePrice"))
                        # Extract the number of days until the contract expires.
                        dte_val = c.get("daysToExpiration")
                        # Safely extract the 'mark' (midpoint) price of the contract.
                        mark_val = safe_float(c.get("mark"))
                        # Safely extract the current bid price (what buyers are offering).
                        bid_val = safe_float(c.get("bid"))
                        # Safely extract the current ask price (what sellers are demanding).
                        ask_val = safe_float(c.get("ask"))
                        # Check if the strike price is missing, zero, or negative.
                        if s_val is None or s_val <= 0:
                            # If so, increment the corresponding telemetry counter.
                            telemetry["rejected_zero_strike_count"] += 1
                            # And skip to the next contract (discarding this invalid one).
                            continue
                        # Check if the days-to-expiration is missing or indicates the contract has already expired.
                        if dte_val is None or int(dte_val) < 0:
                            # If so, increment the expired contract counter.
                            telemetry["rejected_expired_contract_count"] += 1
                            # And skip to the next contract (discarding this invalid one).
                            continue
                        # Check if the mark price is inexplicably negative.
                        if mark_val is not None and mark_val < 0:
                            # If so, increment the negative mark counter.
                            telemetry["rejected_negative_mark_count"] += 1
                            # And skip to the next contract (discarding this invalid one).
                            continue
                        # Check if either the bid price or the ask price is negative.
                        if (bid_val is not None and bid_val < 0) or (
                            # (Checking the ask price here).
                            ask_val is not None and ask_val < 0
                        # ...end of the negative bid/ask condition check.
                        ):
                            # If either price is negative, increment the counter.
                            telemetry["rejected_negative_price_count"] += 1
                            # And skip to the next contract (discarding this invalid one).
                            continue

                        # Create a copy of the contract dictionary so we can modify it safely without altering the original payload.
                        contract_item = dict(c)
                        # Ensure the contract has a clear 'putCallIndicator' (e.g., 'CALL' or 'PUT').
                        contract_item["putCallIndicator"] = str(
                            # First, check if the API explicitly provided 'putCallIndicator'.
                            c.get("putCallIndicator")
                            # If not, check for the older 'putCallType' field.
                            or c.get("putCallType")
                            # If neither is present, use the default we determined based on which 'book' we are reading from.
                            or default_indicator
                        # Convert the resulting string to uppercase for consistency.
                        ).upper()
                        # Add a field to track where this contract data came from (e.g., targeted fetch or default fallback).
                        contract_item["provenance"] = provenance
                        # Finally, add the fully parsed, validated, and enriched contract to our master list.
                        all_contracts.append(contract_item)

    # If the caller provided a specific list of target expirations to fetch...
    if target_expirations:
        # Iterate through each requested expiration.
        for exp in target_expirations:
            # Extract the raw expiration date string from the target object.
            exp_date_raw = exp.get("expirationDate")
            # If the expiration object is missing a date string...
            if not exp_date_raw:
                # And skip to the next contract (discarding this invalid one).
                continue

            # Initialize a variable to hold the parsed date object.
            date_obj = None
            # Start a try block to catch potential errors.
            try:
                # Try to parse the first 10 characters of the raw date string (YYYY-MM-DD) into a Python date object.
                date_obj = datetime.strptime(str(exp_date_raw)[:10], "%Y-%m-%d").date()
            # If parsing fails because the format is wrong or it's not a string...
            except (ValueError, TypeError):
                # ...silently ignore the error; date_obj will remain None.
                pass

            # Prepare the arguments to send to the API for fetching the specific option chain.
            call_kwargs = {
                # Tell the API how many strikes to return around the current price.
                "strike_count": strike_window,
                # Set the start date for the query to our parsed date (or raw string if parsing failed).
                "from_date": date_obj if date_obj is not None else exp_date_raw,
                # Set the end date to the same value, restricting the query to exactly this expiration.
                "to_date": date_obj if date_obj is not None else exp_date_raw,
                # Specify the option strategy (e.g., 'SINGLE') to retrieve.
                "strategy": strategy,
            }

            @retry_vendor_call(max_retries=2, base_delay=0.15)
            # Define a tiny inner function that executes the actual API request.
            def _fetch_target_chain() -> Any:
                # Call the client's method to get the option chain for the symbol, unpacking the prepared arguments.
                return client.get_option_chain(clean_sym, **call_kwargs)

            # Start a try block to catch potential errors.
            try:
                # Execute the decorated fetch function.
                r = _fetch_target_chain()
                # Parse the raw API response into a dictionary.
                parsed = parse_client_response(r)
                # Check if parsing succeeded and the resulting dictionary actually contains option chain data.
                if parsed and ("callExpDateMap" in parsed or "putExpDateMap" in parsed):
                    # If valid, pass the payload to our inner parser function, marking it as coming from a targeted fetch.
                    _parse_chain_payload(parsed, provenance="TARGETED_EXPIRATION")
            # Catch common errors that might occur during data fetching, parsing, or extraction.
            except (KeyError, ValueError, TypeError, AttributeError) as e:
                # Log a warning that getting data for this specific expiration failed.
                logger.warning("Targeted expiration chain failed for %s (%s): %s", clean_sym, exp_date_raw, e)

    # If, after trying to fetch target expirations, we still have no contracts...
    if not all_contracts:
        # Define another decorated fetch function, this time for a generic option chain, with retry logic.
        @retry_vendor_call(max_retries=2, base_delay=0.2)
        # Define the inner function for the default fetch.
        def _fetch_default_chain() -> Any:
            # Call the client method to get the option chain, passing only the symbol (no date constraints).
            return client.get_option_chain(clean_sym)

        # Start a try block to catch potential errors.
        try:
            # Execute the fallback fetch.
            r = _fetch_default_chain()
            # Parse the raw API response into a dictionary.
            parsed = parse_client_response(r)
            # Check if parsing succeeded and the resulting dictionary actually contains option chain data.
            if parsed and ("callExpDateMap" in parsed or "putExpDateMap" in parsed):
                # Set the telemetry flag indicating we had to rely on the default fallback chain.
                telemetry["fallback_to_default_chain"] = True
                # Pass the payload to the parser, explicitly marking its source as the default fallback.
                _parse_chain_payload(parsed, provenance="DEFAULT_CHAIN_FALLBACK")
        # Catch any and all exceptions that might occur during the fallback process.
        except Exception as e:
            # Log a warning that even the fallback attempt failed.
            logger.warning("Default chain fallback failed for %s: %s", clean_sym, e)

    # Finally, return the gathered high-level metrics, the compiled list of valid contracts, and the telemetry dictionary.
    return vol_30d, underlying_price, all_contracts, telemetry