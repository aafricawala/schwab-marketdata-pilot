"""
schwab_vendor_resilience.py
---
Purpose
    This module makes sure the application doesn't instantly crash if the stock market data vendor (Schwab) has a temporary glitch, a slow connection, or sends back weirdly formatted data. It provides tools to automatically retry failed requests and safely extract data from the responses.

Prerequisites
    - Standard Python environment.

What this module does
    1. Defines a `retry_vendor_call` "decorator" (a wrapper you can put around other functions) that automatically retries a failed function up to a certain number of times.
    2. Implements "exponential backoff" for retries, meaning it waits longer and longer between each failed attempt (e.g., 0.25s, then 0.5s, then 1s) to avoid spamming a broken server.
    3. Aborts the retries immediately if the error is a user error (like a 400 Bad Request or 404 Not Found), but keeps retrying if it's a server error (500) or a timeout (408).
    4. Defines `parse_client_response` to safely extract a Python dictionary from whatever weird object or JSON text the vendor sends back.
    5. Checks the successful data payload for hidden error flags (like the vendor saying "Here is your data: {error: 'System down'}") and blocks it.

Configuration knobs
    - max_retries (default: 3)
    - base_delay (default: 0.25 seconds)

Outputs
    - `retry_vendor_call`: Returns a wrapped version of the original function that has retry logic built in.
    - `parse_client_response`: Returns a clean dictionary of data, or None if it's invalid/contains hidden errors.

Notes
    This is extracted directly from older code to centralize how the application handles vendor API instability.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations

# Import functools to properly write "decorators" (functions that wrap other functions)
import functools
# Import the standard logging library to record messages and errors
import logging
# Import the time library so we can force the program to "sleep" (wait) between retries
import time
# Import typing helpers to describe that variables can be Any type, Functions (Callable), Dictionaries, or Optional (might be None)
from typing import Any, Callable, Dict, Optional

# Create a logger specific to raw market data for this file to use
logger = logging.getLogger("schwab_raw_marketdata")
# Add a NullHandler so it doesn't print errors if no main logging is set up
logger.addHandler(logging.NullHandler())


# Define a function that creates a decorator for retrying vendor API calls
def retry_vendor_call(max_retries: int = 3, base_delay: float = 0.25) -> Callable:
    # This is the actual decorator that receives the function we want to protect
    def decorator(func: Callable) -> Callable:
        # Use wraps to make sure our wrapper function looks exactly like the original function to the rest of the code
        @functools.wraps(func)
        # Define the wrapper function that will actually execute instead of the original one
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Set the initial wait time (delay) to whatever was provided in base_delay
            delay = base_delay
            # Create a variable to remember the last error we hit, in case we fail every time
            last_exc = None

            # Start a loop that tries the exact number of times requested (e.g., attempt 1, 2, and 3)
            for attempt in range(1, max_retries + 1):
                # Start a block of code that might fail
                try:
                    # Try to execute the original function exactly as it was requested and return its result
                    return func(*args, **kwargs)
                # If the function crashes
                except Exception as e:
                    # Save the error so we can raise it later if all attempts fail
                    last_exc = e

                    # Try to figure out if this error has an HTTP status code (like 404 or 500) attached to it directly or hidden inside a 'response' object
                    status = getattr(e, "status_code", None) or getattr(
                        getattr(e, "response", None), "status_code", None
                    )

                    # If we found a status code, AND it's less than 500 (meaning it's our fault, not the server's fault), AND it's not a timeout (408) or rate limit (429)
                    if status and status < 500 and status not in (429, 408):
                        # Log a warning that we made a bad request and there's no point in retrying it
                        logger.warning(
                            "Vendor client error %s in %s; not retrying: %s",
                            status,
                            func.__name__,
                            e,
                        )
                        # Immediately re-raise the error and kill the process without retrying
                        raise

                    # If we haven't hit the maximum number of retries yet
                    if attempt < max_retries:
                        # Log a warning saying which attempt failed and that we are going to try again
                        logger.warning(
                            "Attempt %s/%s failed in %s: %s. Retrying in %.2fs",
                            attempt,
                            max_retries,
                            func.__name__,
                            e,
                            delay,
                        )
                        # Put the program to sleep for the current delay amount (e.g., 0.25 seconds)
                        time.sleep(delay)
                        # Double the delay time for the next attempt (exponential backoff: 0.25s -> 0.5s -> 1.0s)
                        delay *= 2.0
                    # If this was the very last attempt allowed
                    else:
                        # Log a final warning saying we completely failed
                        logger.warning(
                            "All %s attempts failed in %s: %s",
                            max_retries,
                            func.__name__,
                            e,
                        )

            # If the loop finishes without successfully returning the function result, raise the final error that broke it
            raise last_exc

        # Return the wrapper function we just built
        return wrapper

    # Return the decorator we just built
    return decorator


# Define a function that safely parses and cleans up whatever the vendor's API sends back
def parse_client_response(resp: Any) -> Optional[Dict[str, Any]]:
    # If the response is literally nothing, return None
    if resp is None:
        return None

    # Create an empty variable to hold our dictionary once we find it
    d = None

    # Check if the response is already a perfectly formatted Python dictionary
    if isinstance(resp, dict):
        # If it is, just use it directly
        d = resp
    # If it's not a dictionary, check if it's an HTTP Response object (has a 'status_code')
    elif hasattr(resp, "status_code"):
        # Check if the status code is exactly 200 (OK)
        if resp.status_code == 200:
            # Start a block of code that might fail
            try:
                # Try to decode the response body from JSON text into a Python object
                parsed = resp.json()
                # If decoding worked and the result is a dictionary
                if isinstance(parsed, dict):
                    # Save it to our 'd' variable
                    d = parsed
            # Catch errors if the response wasn't actually valid JSON text
            except (ValueError, TypeError) as e:
                # Log a warning that the server lied and gave us bad data
                logger.warning("Failed to decode JSON from 200 response: %s", e)
                # Return None to protect the rest of the application
                return None
        # If the status code was anything other than 200 OK
        else:
            # Log a warning that the API request failed
            logger.warning("Vendor call returned non-200 HTTP status: %s", resp.status_code)
            # Return None
            return None

    # If we successfully found a dictionary of data
    if d is not None:
        # Loop through a list of common words vendors use to flag errors inside their data payload
        for err_key in ("error", "errors", "fault", "faultcode"):
            # Check if any of those words exist as keys in the data dictionary
            if err_key in d:
                # If one does, log a warning that the vendor successfully returned an error message
                logger.warning("Vendor payload envelope reports error flag '%s': %s", err_key, d[err_key])
                # Return None so the application doesn't try to read error text as financial data
                return None

    # If the dictionary exists and has no hidden error flags, return it safely
    return d