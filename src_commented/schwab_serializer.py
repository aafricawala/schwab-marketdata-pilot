# Filename.py: schwab_serializer.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

# Filename.py: schwab_serializer.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

"""
# Execute this line of logic to process the data
schwab_serializer.py

# Execute this line of logic to process the data
Purpose:
# Execute this line of logic to process the data
This module prepares raw Python objects, dataframes, and numerical types for safe,
# Execute this line of logic to process the data
clean JSON serialization. It recursively sanitizes nested structures, ensuring that
# Execute this line of logic to process the data
special values like NaN or Infinity are handled, currency values are correctly formatted,
# Execute this line of logic to process the data
and unneeded nulls are removed, while preserving nulls in critical sections.

# Execute this line of logic to process the data
Prerequisites:
# Execute this line of logic to process the data
- Requires standard libraries (`json`, `logging`, `math`, `pathlib`, `typing`).
# Execute this line of logic to process the data
- Requires `numpy` and `pandas` for handling data science structures.

# Execute this line of logic to process the data
What this module does:
# Execute this line of logic to process the data
1. Converts pandas Series and DataFrames into dictionaries.
# Execute this line of logic to process the data
2. Converts numpy arrays into standard Python lists.
# Execute this line of logic to process the data
3. Formats floating-point numbers and integers, optionally as currency if their key matches `CURRENCY_KEYS`.
# Execute this line of logic to process the data
4. Removes None, NaN, or Infinity values, unless the dictionary key belongs to a specific set (`PRESERVE_NULL_CONTAINERS`).
# Execute this line of logic to process the data
5. Converts numpy booleans and integers into standard Python types.
# Execute this line of logic to process the data
6. Provides helper functions to export sanitized data directly to a JSON file.

# Execute this line of logic to process the data
Configuration knobs:
# Execute this line of logic to process the data
- `CURRENCY_KEYS`: A set of strings representing dictionary keys that should be formatted as currency (e.g., "$1.00").
# Execute this line of logic to process the data
- `PRESERVE_NULL_CONTAINERS`: A set of dictionary keys where `None` values should NOT be stripped out.
# Execute this line of logic to process the data
- `SAFE_INTEGER_LIMIT`: A constant set to 2^53 - 1, the max safe integer in JSON/JavaScript.

# Execute this line of logic to process the data
Outputs:
# Execute this line of logic to process the data
- The main function returns a fully sanitized, JSON-serializable Python dictionary or list.
# Execute this line of logic to process the data
- Helper functions export the sanitized data to a JSON file and return the JSON string or file path.

# Execute this line of logic to process the data
Notes:
# Execute this line of logic to process the data
- Data inside the "calculated_metrics" section is treated specially (e.g., currency formatting is bypassed).
"""

# Enable modern type hinting features from the future.
# Import specific components from a module
from __future__ import annotations
# Import the standard JSON library for serialization.
# Import the required external module
import json
# Import the logging library to track events.
# Import the required external module
import logging
# Import math for checking special float values like NaN and Infinity.
# Import the required external module
import math
# Import Path for cross-platform file path handling.
# Import specific components from a module
from pathlib import Path
# Import typing structures for type annotations.
# Import specific components from a module
from typing import Any, Dict, Optional, Set, Tuple
# Import numpy for handling numerical data types and arrays.
# Import the required external module
import numpy as np
# Import pandas for handling DataFrames and Series.
# Import the required external module
import pd

# Create a logger specifically for this serializer module.
# Assign a value or initialize a variable
logger = logging.getLogger("schwab_serializer")
# Add a null handler to prevent logging errors if no other handlers are configured.
# Log an important message or event
logger.addHandler(logging.NullHandler())

# Define a set of dictionary keys that represent monetary values.
# Assign a value or initialize a variable
CURRENCY_KEYS: Set[str] = {
    # Last traded price of an asset.
    # Execute this line of logic to process the data
    "lastPrice",
    # Closing price of an asset.
    # Execute this line of logic to process the data
    "closePrice",
    # Bid price (what a buyer is willing to pay).
    # Execute this line of logic to process the data
    "bidPrice",
    # Ask price (what a seller is asking for).
    # Execute this line of logic to process the data
    "askPrice",
    # Dividend amount paid by a stock.
    # Execute this line of logic to process the data
    "divAmount",
    # Cash flow from operations per share.
    # Execute this line of logic to process the data
    "cfo_per_share",
    # Strike price of an option.
    # Execute this line of logic to process the data
    "strikePrice",
    # Mark price (the mid-point or fair value).
    # Execute this line of logic to process the data
    "mark",
    # Shortened key for bid price.
    # Execute this line of logic to process the data
    "bid",
    # Shortened key for ask price.
    # Execute this line of logic to process the data
    "ask",
# Execute this line of logic to process the data
}

# Define a set of section names where None (null) values must be kept intact, not stripped.
# Assign a value or initialize a variable
PRESERVE_NULL_CONTAINERS: Set[str] = {
    # The phase 0 grounding section.
    # Execute this line of logic to process the data
    "phase_0_grounding",
    # The market cap divergence metrics section.
    # Execute this line of logic to process the data
    "market_cap_divergence",
    # The short locate status section.
    # Execute this line of logic to process the data
    "short_locate_status",
    # The fundamental metrics section (step 1).
    # Execute this line of logic to process the data
    "step_1_fundamentals",
    # The fundamentals and quality combined section.
    # Execute this line of logic to process the data
    "step_1_fundamentals_and_quality",
    # The derivatives and surface metrics section.
    # Execute this line of logic to process the data
    "step_3_and_7_derivatives_and_surface",
    # The technicals and flows metrics section.
    # Execute this line of logic to process the data
    "step_5_technicals_and_flows",
    # The 30-day skew metrics section.
    # Execute this line of logic to process the data
    "skew_30d",
    # The flow ratios metrics section.
    # Execute this line of logic to process the data
    "flow_ratios",
# Execute this line of logic to process the data
}

# Define the maximum integer value safely representable in standard JSON (JavaScript max safe integer).
# Assign a value or initialize a variable
SAFE_INTEGER_LIMIT = 2**53 - 1


# Define the main recursive function that cleans objects for JSON serialization.
# Define a new function or method
def sanitize_payload_for_serialization(
    # The object to sanitize (could be a dict, list, float, etc.).
    # Execute this line of logic to process the data
    obj: Any,
    # The key name of the object in its parent dictionary (default is empty).
    # Assign a value or initialize a variable
    key_name: str = "",
    # The full dot-separated path to this object (used for context).
    # Assign a value or initialize a variable
    current_path: str = ""
# Execute this line of logic to process the data
) -> Any:
    # Check if the object is a pandas DataFrame or Series.
    # Check a conditional statement
    if isinstance(obj, (pd.DataFrame, pd.Series)):
        # Convert it to a dictionary and recursively sanitize it.
        # Return the final computed result to the caller
        return sanitize_payload_for_serialization(
            # Assign a value or initialize a variable
            obj.to_dict(), key_name=key_name, current_path=current_path
        # Execute this line of logic to process the data
        )

    # Check if the object is a numpy array.
    # Check a conditional statement
    if isinstance(obj, np.ndarray):
        # Convert the array to a list and recursively sanitize each item.
        # Return the final computed result to the caller
        return [
            # Call the sanitizer on each item inside the array.
            # Execute this line of logic to process the data
            sanitize_payload_for_serialization(
                # Assign a value or initialize a variable
                item, key_name=key_name, current_path=current_path
            # Execute this line of logic to process the data
            )
            # Iterate through the numpy array as a standard Python list.
            # Start a loop over the given collection
            for item in obj.tolist()
        # Execute this line of logic to process the data
        ]

    # Extract the root section name from the current path (everything before the first dot).
    # Assign a value or initialize a variable
    root_section = current_path.split(".")[0] if current_path else ""
    # Check if the current context is inside the "calculated_metrics" section.
    # Assign a value or initialize a variable
    in_calc_scope = (root_section == "calculated_metrics")

    # Check if the object is a floating-point number (either numpy float or standard python float).
    # Check a conditional statement
    if isinstance(obj, (np.floating, float)):
        # If the number is Not-a-Number (NaN) or Infinity.
        # Check a conditional statement
        if math.isnan(obj) or math.isinf(obj):
            # JSON cannot handle NaN or Inf, so return None (null).
            # Return the final computed result to the caller
            return None
        # If not in calculated metrics, and the key is known to be a currency value.
        # Check a conditional statement
        if not in_calc_scope and key_name in CURRENCY_KEYS:
            # Format the float as a standard US dollar string (e.g., "$1,234.56").
            # Return the final computed result to the caller
            return f"${float(obj):,.2f}"
        # If we are inside the calculated metrics scope.
        # Check a conditional statement
        if in_calc_scope:
            # Convert the numpy float to a standard python float.
            # Assign a value or initialize a variable
            flt_val = float(obj)
            # Prevent scientific notation dust (e.g. 1e-13) by forcing very small numbers to exactly 0.0.
            # Assign a value or initialize a variable
            return 0.0 if (flt_val == 0.0 or abs(flt_val) < 1e-12) else flt_val
        # For standard floats not in calc scope, round to 2 decimal places.
        # Assign a value or initialize a variable
        v = round(float(obj), 2)
        # Again, force extremely small numbers to exactly 0.0.
        # Assign a value or initialize a variable
        return 0.0 if (v == 0.0 or abs(v) < 1e-12) else v

    # Check if the object is an integer (but ensure it's not actually a boolean).
    # Check a conditional statement
    if isinstance(obj, (np.integer, int)) and not isinstance(obj, (bool, np.bool_)):
        # Convert the numpy int to a standard python int.
        # Assign a value or initialize a variable
        int_val = int(obj)
        # If not in calculated metrics and the key implies a currency value.
        # Check a conditional statement
        if not in_calc_scope and key_name in CURRENCY_KEYS:
            # If the integer is extremely large (above safe limit).
            # Check a conditional statement
            if abs(int_val) > SAFE_INTEGER_LIMIT:
                # Format with commas but without decimals to prevent float precision loss.
                # Return the final computed result to the caller
                return f"${int_val:,}"
            # Otherwise, format normally with two decimal places.
            # Return the final computed result to the caller
            return f"${float(int_val):,.2f}"
        # Return the standard python integer.
        # Return the final computed result to the caller
        return int_val

    # Check if the object is a boolean (numpy or python standard).
    # Check a conditional statement
    if isinstance(obj, (bool, np.bool_)):
        # Ensure it is returned as a native Python bool.
        # Return the final computed result to the caller
        return bool(obj)

    # Check if the object is a string.
    # Check a conditional statement
    if isinstance(obj, str):
        # If inside calculated metrics, leave the string exactly as is.
        # Check a conditional statement
        if in_calc_scope:
            # Return the final computed result to the caller
            return obj
        # If it's a currency key, but the string does not start with a dollar sign.
        # Check a conditional statement
        if key_name in CURRENCY_KEYS and not obj.startswith("$"):
            # Start a try-catch block to handle potential errors
            try:
                # Attempt to strip commas and convert to a float.
                # Assign a value or initialize a variable
                num = float(obj.replace(",", "").strip())
                # If successful, re-format it as a proper currency string.
                # Return the final computed result to the caller
                return f"${num:,.2f}"
            # Catch and handle an exception
            except ValueError:
                # If conversion fails (e.g., the string says "N/A"), return the original string.
                # Return the final computed result to the caller
                return obj
        # Return the string normally.
        # Return the final computed result to the caller
        return obj

    # Check if the object is a dictionary (like a JSON object).
    # Check a conditional statement
    if isinstance(obj, dict):
        # Determine the name of the immediate parent container.
        # Assign a value or initialize a variable
        current_container = current_path.split(".")[-1] if current_path else ""
        # Check if this container is on the list of containers where nulls should be preserved.
        # Assign a value or initialize a variable
        preserve_nulls = current_container in PRESERVE_NULL_CONTAINERS
        # Create a new, empty dictionary to hold the cleaned data.
        # Assign a value or initialize a variable
        cleaned: Dict[str, Any] = {}
        # Iterate over all key-value pairs in the original dictionary.
        # Start a loop over the given collection
        for k, v in obj.items():
            # Build the new path by appending the current key.
            # Assign a value or initialize a variable
            child_path = f"{current_path}.{k}" if current_path else str(k)
            # Recursively call the sanitizer on the child value.
            # Assign a value or initialize a variable
            val = sanitize_payload_for_serialization(
                # Assign a value or initialize a variable
                v, key_name=str(k), current_path=child_path
            # Execute this line of logic to process the data
            )
            # If the sanitized value is not None, OR if we are mandated to preserve nulls.
            # Check a conditional statement
            if val is not None or preserve_nulls:
                # Add the sanitized value to our cleaned dictionary using a string key.
                # Assign a value or initialize a variable
                cleaned[str(k)] = val
        # Return the newly built, cleaned dictionary.
        # Return the final computed result to the caller
        return cleaned

    # Check if the object is a list, tuple, or set.
    # Check a conditional statement
    if isinstance(obj, (list, tuple, set)):
        # Return a list comprehension that processes every item.
        # Return the final computed result to the caller
        return [
            # Recursively call the sanitizer on each list item.
            # Execute this line of logic to process the data
            sanitize_payload_for_serialization(
                # Assign a value or initialize a variable
                item, key_name=key_name, current_path=current_path
            # Execute this line of logic to process the data
            )
            # Iterate through the items in the collection.
            # Start a loop over the given collection
            for item in obj
            # Exclude the item from the new list completely if it evaluated to None.
            # Check a conditional statement
            if item is not None
        # Execute this line of logic to process the data
        ]

    # Check if the object is natively None, or a pandas missing value indicator (pd.isna).
    # Check a conditional statement
    if obj is None or pd.isna(obj):
        # Return standard None for JSON null.
        # Return the final computed result to the caller
        return None

    # If the object is of an unrecognized type, return it as-is.
    # Return the final computed result to the caller
    return obj


# Define a small wrapper function for public use to clean data for JSON.
# Define a new function or method
def clean_for_json(data: Any, path: str = "") -> Any:
    # Just pass the arguments directly to the main sanitize function.
    # Assign a value or initialize a variable
    return sanitize_payload_for_serialization(data, current_path=path)


# Define a function to sanitize data and immediately export it to a compact JSON file.
# Define a new function or method
def export_compact_json(
    # The dictionary of data to export.
    # Execute this line of logic to process the data
    data: Dict[str, Any],
    # The file path to save it to.
    # Execute this line of logic to process the data
    filepath: str | Path
# Execute this line of logic to process the data
) -> Tuple[Path, Dict[str, Any]]:
    # Convert the file path to a pathlib Path object.
    # Assign a value or initialize a variable
    path = Path(filepath)
    # Sanitize the input data by removing nulls, fixing floats, etc.
    # Assign a value or initialize a variable
    cleaned_data = sanitize_payload_for_serialization(data)
    # Convert the cleaned dictionary to a JSON string.
    # Assign a value or initialize a variable
    json_str = json.dumps(
        # The data to dump.
        # Execute this line of logic to process the data
        cleaned_data,
        # Remove spaces around commas and colons to make the file smaller (compact).
        # Assign a value or initialize a variable
        separators=(",", ":"),
        # Allow unicode characters directly (don't escape them to \uXXXX).
        # Assign a value or initialize a variable
        ensure_ascii=False,
        # If an unknown object is encountered, convert it to a string as a fallback.
        # Assign a value or initialize a variable
        default=str
    # Execute this line of logic to process the data
    )
    # Ensure the parent directory exists, creating it if it doesn't.
    # Assign a value or initialize a variable
    path.parent.mkdir(parents=True, exist_ok=True)
    # Open the file for writing in UTF-8 mode.
    # Assign a value or initialize a variable
    with open(path, "w", encoding="utf-8") as f:
        # Write the JSON string to the file.
        # Execute this line of logic to process the data
        f.write(json_str)
    # Return both the finalized Path object and the dictionary of cleaned data.
    # Return the final computed result to the caller
    return path, cleaned_data


# Define a function to sanitize data, optionally save it to a file, and return the JSON string.
# Define a new function or method
def serialize_and_export_thesis(
    # The dictionary of thesis data to serialize.
    # Execute this line of logic to process the data
    payload: Dict[str, Any],
    # Optional file path to output to; defaults to None.
    # Assign a value or initialize a variable
    output_path: Optional[str] = None
# Execute this line of logic to process the data
) -> str:
    # If an output path is provided, use it; otherwise use a default filename "thesis_output.json".
    # Assign a value or initialize a variable
    path = Path(output_path) if output_path else Path("thesis_output.json")
    # Call the export_compact_json function which cleans the data and writes the file.
    # Assign a value or initialize a variable
    _, cleaned = export_compact_json(payload, path)
    # Convert the cleaned dictionary to a JSON string again.
    # Return the final computed result to the caller
    return json.dumps(
        # The cleaned data to convert.
        # Execute this line of logic to process the data
        cleaned,
        # Remove spaces to make the JSON compact.
        # Assign a value or initialize a variable
        separators=(",", ":"),
        # Allow unicode characters.
        # Assign a value or initialize a variable
        ensure_ascii=False,
        # Fallback for unknown objects.
        # Assign a value or initialize a variable
        default=str
    # Execute this line of logic to process the data
    )
