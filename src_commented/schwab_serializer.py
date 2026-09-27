"""
schwab_serializer.py

Purpose:
This module prepares raw Python objects, dataframes, and numerical types for safe,
clean JSON serialization. It recursively sanitizes nested structures, ensuring that
special values like NaN or Infinity are handled, currency values are correctly formatted,
and unneeded nulls are removed, while preserving nulls in critical sections.

Prerequisites:
- Requires standard libraries (`json`, `logging`, `math`, `pathlib`, `typing`).
- Requires `numpy` and `pandas` for handling data science structures.

What this module does:
1. Converts pandas Series and DataFrames into dictionaries.
2. Converts numpy arrays into standard Python lists.
3. Formats floating-point numbers and integers, optionally as currency if their key matches `CURRENCY_KEYS`.
4. Removes None, NaN, or Infinity values, unless the dictionary key belongs to a specific set (`PRESERVE_NULL_CONTAINERS`).
5. Converts numpy booleans and integers into standard Python types.
6. Provides helper functions to export sanitized data directly to a JSON file.

Configuration knobs:
- `CURRENCY_KEYS`: A set of strings representing dictionary keys that should be formatted as currency (e.g., "$1.00").
- `PRESERVE_NULL_CONTAINERS`: A set of dictionary keys where `None` values should NOT be stripped out.
- `SAFE_INTEGER_LIMIT`: A constant set to 2^53 - 1, the max safe integer in JSON/JavaScript.

Outputs:
- The main function returns a fully sanitized, JSON-serializable Python dictionary or list.
- Helper functions export the sanitized data to a JSON file and return the JSON string or file path.

Notes:
- Data inside the "calculated_metrics" section is treated specially (e.g., currency formatting is bypassed).
"""

# Enable modern type hinting features from the future.
from __future__ import annotations
# Import the standard JSON library for serialization.
import json
# Import the logging library to track events.
import logging
# Import math for checking special float values like NaN and Infinity.
import math
# Import Path for cross-platform file path handling.
from pathlib import Path
# Import typing structures for type annotations.
from typing import Any, Dict, Optional, Set, Tuple
# Import numpy for handling numerical data types and arrays.
import numpy as np
# Import pandas for handling DataFrames and Series.
import pd

# Create a logger specifically for this serializer module.
logger = logging.getLogger("schwab_serializer")
# Add a null handler to prevent logging errors if no other handlers are configured.
logger.addHandler(logging.NullHandler())

# Define a set of dictionary keys that represent monetary values.
CURRENCY_KEYS: Set[str] = {
    # Last traded price of an asset.
    "lastPrice",
    # Closing price of an asset.
    "closePrice",
    # Bid price (what a buyer is willing to pay).
    "bidPrice",
    # Ask price (what a seller is asking for).
    "askPrice",
    # Dividend amount paid by a stock.
    "divAmount",
    # Cash flow from operations per share.
    "cfo_per_share",
    # Strike price of an option.
    "strikePrice",
    # Mark price (the mid-point or fair value).
    "mark",
    # Shortened key for bid price.
    "bid",
    # Shortened key for ask price.
    "ask",
}

# Define a set of section names where None (null) values must be kept intact, not stripped.
PRESERVE_NULL_CONTAINERS: Set[str] = {
    # The phase 0 grounding section.
    "phase_0_grounding",
    # The market cap divergence metrics section.
    "market_cap_divergence",
    # The short locate status section.
    "short_locate_status",
    # The fundamental metrics section (step 1).
    "step_1_fundamentals",
    # The fundamentals and quality combined section.
    "step_1_fundamentals_and_quality",
    # The derivatives and surface metrics section.
    "step_3_and_7_derivatives_and_surface",
    # The technicals and flows metrics section.
    "step_5_technicals_and_flows",
    # The 30-day skew metrics section.
    "skew_30d",
    # The flow ratios metrics section.
    "flow_ratios",
}

# Define the maximum integer value safely representable in standard JSON (JavaScript max safe integer).
SAFE_INTEGER_LIMIT = 2**53 - 1


# Define the main recursive function that cleans objects for JSON serialization.
def sanitize_payload_for_serialization(
    # The object to sanitize (could be a dict, list, float, etc.).
    obj: Any,
    # The key name of the object in its parent dictionary (default is empty).
    key_name: str = "",
    # The full dot-separated path to this object (used for context).
    current_path: str = ""
) -> Any:
    # Check if the object is a pandas DataFrame or Series.
    if isinstance(obj, (pd.DataFrame, pd.Series)):
        # Convert it to a dictionary and recursively sanitize it.
        return sanitize_payload_for_serialization(
            obj.to_dict(), key_name=key_name, current_path=current_path
        )

    # Check if the object is a numpy array.
    if isinstance(obj, np.ndarray):
        # Convert the array to a list and recursively sanitize each item.
        return [
            # Call the sanitizer on each item inside the array.
            sanitize_payload_for_serialization(
                item, key_name=key_name, current_path=current_path
            )
            # Iterate through the numpy array as a standard Python list.
            for item in obj.tolist()
        ]

    # Extract the root section name from the current path (everything before the first dot).
    root_section = current_path.split(".")[0] if current_path else ""
    # Check if the current context is inside the "calculated_metrics" section.
    in_calc_scope = (root_section == "calculated_metrics")

    # Check if the object is a floating-point number (either numpy float or standard python float).
    if isinstance(obj, (np.floating, float)):
        # If the number is Not-a-Number (NaN) or Infinity.
        if math.isnan(obj) or math.isinf(obj):
            # JSON cannot handle NaN or Inf, so return None (null).
            return None
        # If not in calculated metrics, and the key is known to be a currency value.
        if not in_calc_scope and key_name in CURRENCY_KEYS:
            # Format the float as a standard US dollar string (e.g., "$1,234.56").
            return f"${float(obj):,.2f}"
        # If we are inside the calculated metrics scope.
        if in_calc_scope:
            # Convert the numpy float to a standard python float.
            flt_val = float(obj)
            # Prevent scientific notation dust (e.g. 1e-13) by forcing very small numbers to exactly 0.0.
            return 0.0 if (flt_val == 0.0 or abs(flt_val) < 1e-12) else flt_val
        # For standard floats not in calc scope, round to 2 decimal places.
        v = round(float(obj), 2)
        # Again, force extremely small numbers to exactly 0.0.
        return 0.0 if (v == 0.0 or abs(v) < 1e-12) else v

    # Check if the object is an integer (but ensure it's not actually a boolean).
    if isinstance(obj, (np.integer, int)) and not isinstance(obj, (bool, np.bool_)):
        # Convert the numpy int to a standard python int.
        int_val = int(obj)
        # If not in calculated metrics and the key implies a currency value.
        if not in_calc_scope and key_name in CURRENCY_KEYS:
            # If the integer is extremely large (above safe limit).
            if abs(int_val) > SAFE_INTEGER_LIMIT:
                # Format with commas but without decimals to prevent float precision loss.
                return f"${int_val:,}"
            # Otherwise, format normally with two decimal places.
            return f"${float(int_val):,.2f}"
        # Return the standard python integer.
        return int_val

    # Check if the object is a boolean (numpy or python standard).
    if isinstance(obj, (bool, np.bool_)):
        # Ensure it is returned as a native Python bool.
        return bool(obj)

    # Check if the object is a string.
    if isinstance(obj, str):
        # If inside calculated metrics, leave the string exactly as is.
        if in_calc_scope:
            return obj
        # If it's a currency key, but the string does not start with a dollar sign.
        if key_name in CURRENCY_KEYS and not obj.startswith("$"):
            try:
                # Attempt to strip commas and convert to a float.
                num = float(obj.replace(",", "").strip())
                # If successful, re-format it as a proper currency string.
                return f"${num:,.2f}"
            except ValueError:
                # If conversion fails (e.g., the string says "N/A"), return the original string.
                return obj
        # Return the string normally.
        return obj

    # Check if the object is a dictionary (like a JSON object).
    if isinstance(obj, dict):
        # Determine the name of the immediate parent container.
        current_container = current_path.split(".")[-1] if current_path else ""
        # Check if this container is on the list of containers where nulls should be preserved.
        preserve_nulls = current_container in PRESERVE_NULL_CONTAINERS
        # Create a new, empty dictionary to hold the cleaned data.
        cleaned: Dict[str, Any] = {}
        # Iterate over all key-value pairs in the original dictionary.
        for k, v in obj.items():
            # Build the new path by appending the current key.
            child_path = f"{current_path}.{k}" if current_path else str(k)
            # Recursively call the sanitizer on the child value.
            val = sanitize_payload_for_serialization(
                v, key_name=str(k), current_path=child_path
            )
            # If the sanitized value is not None, OR if we are mandated to preserve nulls.
            if val is not None or preserve_nulls:
                # Add the sanitized value to our cleaned dictionary using a string key.
                cleaned[str(k)] = val
        # Return the newly built, cleaned dictionary.
        return cleaned

    # Check if the object is a list, tuple, or set.
    if isinstance(obj, (list, tuple, set)):
        # Return a list comprehension that processes every item.
        return [
            # Recursively call the sanitizer on each list item.
            sanitize_payload_for_serialization(
                item, key_name=key_name, current_path=current_path
            )
            # Iterate through the items in the collection.
            for item in obj
            # Exclude the item from the new list completely if it evaluated to None.
            if item is not None
        ]

    # Check if the object is natively None, or a pandas missing value indicator (pd.isna).
    if obj is None or pd.isna(obj):
        # Return standard None for JSON null.
        return None

    # If the object is of an unrecognized type, return it as-is.
    return obj


# Define a small wrapper function for public use to clean data for JSON.
def clean_for_json(data: Any, path: str = "") -> Any:
    # Just pass the arguments directly to the main sanitize function.
    return sanitize_payload_for_serialization(data, current_path=path)


# Define a function to sanitize data and immediately export it to a compact JSON file.
def export_compact_json(
    # The dictionary of data to export.
    data: Dict[str, Any],
    # The file path to save it to.
    filepath: str | Path
) -> Tuple[Path, Dict[str, Any]]:
    # Convert the file path to a pathlib Path object.
    path = Path(filepath)
    # Sanitize the input data by removing nulls, fixing floats, etc.
    cleaned_data = sanitize_payload_for_serialization(data)
    # Convert the cleaned dictionary to a JSON string.
    json_str = json.dumps(
        # The data to dump.
        cleaned_data,
        # Remove spaces around commas and colons to make the file smaller (compact).
        separators=(",", ":"),
        # Allow unicode characters directly (don't escape them to \uXXXX).
        ensure_ascii=False,
        # If an unknown object is encountered, convert it to a string as a fallback.
        default=str
    )
    # Ensure the parent directory exists, creating it if it doesn't.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Open the file for writing in UTF-8 mode.
    with open(path, "w", encoding="utf-8") as f:
        # Write the JSON string to the file.
        f.write(json_str)
    # Return both the finalized Path object and the dictionary of cleaned data.
    return path, cleaned_data


# Define a function to sanitize data, optionally save it to a file, and return the JSON string.
def serialize_and_export_thesis(
    # The dictionary of thesis data to serialize.
    payload: Dict[str, Any],
    # Optional file path to output to; defaults to None.
    output_path: Optional[str] = None
) -> str:
    # If an output path is provided, use it; otherwise use a default filename "thesis_output.json".
    path = Path(output_path) if output_path else Path("thesis_output.json")
    # Call the export_compact_json function which cleans the data and writes the file.
    _, cleaned = export_compact_json(payload, path)
    # Convert the cleaned dictionary to a JSON string again.
    return json.dumps(
        # The cleaned data to convert.
        cleaned,
        # Remove spaces to make the JSON compact.
        separators=(",", ":"),
        # Allow unicode characters.
        ensure_ascii=False,
        # Fallback for unknown objects.
        default=str
    )
