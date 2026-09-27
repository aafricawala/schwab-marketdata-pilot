"""
schwab_utils.py
---
Purpose
    This module acts as a "toolbox" containing small, reusable helper functions that are used throughout the entire project. It handles common tasks like ensuring a stock symbol is formatted correctly, safely converting raw text into numbers, and safely performing division without causing the program to crash.

Prerequisites
    - Requires the `pandas` library to check for "Not a Number" (NaN) values common in data tables.

What this module does
    1. Defines rules for what a valid stock symbol looks like (regular expressions).
    2. Validates and cleans up stock symbols provided by the user.
    3. Provides a `safe_float` function that tries very hard to convert messy data (like "$1,234.50") into a clean decimal number, returning `None` instead of crashing if it fails.
    4. Provides a `safe_div` function that divides two numbers, returning `None` instead of crashing if the denominator is zero.

Configuration knobs
    - `RE_VALID_SYMBOL`: A regular expression pattern dictating that symbols must start with a letter and be up to 10 characters long.
    - `RESERVED_ENVELOPE_KEYS`: A list of words that are not allowed to be used as stock symbols because they conflict with internal system keywords.

Outputs
    - `validate_symbol`: Returns a clean, uppercase string.
    - `safe_float`: Returns a clean floating-point number, or None.
    - `safe_div`: Returns the result of division as a floating-point number, or None.

Notes
    These functions are designed to fail gracefully (returning None) rather than throwing errors, which is critical for processing messy real-world market data without stopping the whole program.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations
# Import the math library to check for special math conditions like infinity or "Not a Number"
import math
# Import the regular expression library to match text patterns
import re
# Import typing helpers to describe that variables can be Any type, or Optional (meaning they can be None)
from typing import Any, Optional
# Import pandas for data manipulation, mostly used here to check if a value is missing (NaN)
import pandas as pd

# Compile a regular expression rule: starts with an uppercase letter, followed by up to 9 letters, numbers, dots, slashes, or dashes
RE_VALID_SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,9}$")
# Create a set of specific words that cannot be used as stock symbols because the vendor's API uses them as hidden category labels
RESERVED_ENVELOPE_KEYS = {
    "QUOTE",
    "REFERENCE",
    "FUNDAMENTAL",
    "FUND",
    "ASSETMAINTYPE",
    "ASSETSUBTYPE",
    "DESCRIPTION",
}

# Define a function to validate and clean up a stock symbol, taking a string and returning a string
def validate_symbol(symbol: str) -> str:
    # Check if the provided symbol is not a string type
    if not isinstance(symbol, str):
        # If it's not a string, raise an error explaining what type it incorrectly received
        raise TypeError(f"Symbol must be a string, received {type(symbol).__name__}")
    # Remove any extra spaces from the beginning or end of the string, and make it all uppercase
    clean = symbol.strip().upper()
    # Check if the string is empty after removing spaces
    if not clean:
        # If it's empty, raise an error
        raise ValueError("Symbol cannot be empty.")
    # Check if the cleaned symbol perfectly matches one of the forbidden reserved words
    if clean in RESERVED_ENVELOPE_KEYS:
        # If it does, raise an error explaining the collision
        raise ValueError(f"Symbol '{clean}' collides with reserved broker envelope keys.")
    # Check if the cleaned symbol fails to match the regular expression rule we defined at the top
    if not RE_VALID_SYMBOL.match(clean):
        # If it fails, raise an error explaining the formatting issue
        raise ValueError(f"Symbol '{clean}' contains invalid characters or exceeds 10 chars.")
    # If it passes all tests, return the cleaned-up symbol
    return clean

# Define a function to safely convert any unknown value into a decimal number (float), returning None if it fails
def safe_float(v: Any) -> Optional[float]:
    # Check if the value is explicitly None, or if pandas considers it a missing/empty value
    if v is None or pd.isna(v):
        # Return None
        return None
    # Check if the value is NOT a string, integer, or float (e.g., if it's a list or dictionary)
    if not isinstance(v, (str, int, float)):
        # Return None because we can't convert complex objects to a simple number
        return None
    # Start a block of code that might fail
    try:
        # Convert the value to a string, remove dollar signs, remove commas, remove spaces, and try to turn it into a float
        f = float(str(v).replace("$", "").replace(",", "").strip())
        # Check if the resulting number is mathematically "Not a Number" (NaN) or Infinity
        if math.isnan(f) or math.isinf(f):
            # If so, return None
            return None
        # Return exactly 0.0 if the number is mathematically zero or incredibly close to zero (floating point rounding error), otherwise return the number itself
        return 0.0 if (f == 0.0 or abs(f) < 1e-12) else f
    # If the conversion to float crashes (like trying to convert the word "apple")
    except (ValueError, TypeError):
        # Catch the error and just return None safely
        return None

# Define a function to safely divide two numbers, returning None if it fails or if dividing by zero
def safe_div(n: Any, d: Any) -> Optional[float]:
    # Try to safely convert both the numerator (n) and denominator (d) into clean floats using our function above
    fn, fd = safe_float(n), safe_float(d)
    # Check if either number failed to convert (is None), or if the denominator is exactly zero
    if fn is None or fd is None or fd == 0.0:
        # We can't divide by zero or None, so return None
        return None
    # Perform the actual division
    res = fn / fd
    # Return None if the result is NaN or Infinity, otherwise return the actual result
    return None if math.isnan(res) or math.isinf(res) else res