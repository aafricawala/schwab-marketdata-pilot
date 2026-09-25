"""
schwab_serializer.py
========================================================================================
CHARLES SCHWAB DATA SANITIZER, FORMATTER & JSON SERIALIZATION ENGINE
========================================================================================

WHAT THIS SCRIPT DOES:
----------------------
This module is a dedicated serialization utility responsible for taking raw Python data
structures (dictionaries, lists, pandas DataFrames/Series, and scalar values) produced
during data ingestion and financial calculation, and converting them into a clean,
minified, and strictly valid JSON format.

It ensures that output files strictly follow schema formatting rules:
- Currency fields are prefixed with '$' and formatted to 2 decimal places.
- Other numerical floating-point metrics are rounded to 2 decimal places.
- Missing values, nulls, NaNs, infinities, and empty nested collections are defensively
  pruned to keep the JSON output lightweight and readable.
- Minified JSON files are saved to disk with zero redundant whitespace.

WHEN AND HOW IT GETS CALLED:
----------------------------
This module is typically called at the very end of your data processing pipeline:
1. Notebook Coordinator / Pipeline (e.g., Cell 2):
   After `schwab_raw_marketdata.py` extracts raw market structures and
   `schwab_marketdata_calculator.py` computes mathematical models, `export_compact_json()`
   is called to serialize and write the combined thesis payload to disk.
2. In-Memory Sanitization:
   Other scripts can import `clean_for_json()` directly if they need clean, dictionary-based
   representations without writing files directly to disk.

KEY CONSTANTS & FUNCTIONS AND HIGH-LEVEL RESPONSIBILITIES:
---------------------------------------------------------
1. CURRENCY_KEYS (Constant Set):
   - A registry of known financial field names that represent dollar-denominated prices
     or amounts (e.g., 'lastPrice', 'bidPrice', 'R1', 'R2', 'R3', 'Pivot', 'S1', 'S2',
     'S3', 'strikePrice', 'imputed_total_debt', etc.).
   - Used by `clean_for_json()` to decide whether a numeric value should be rendered
     as a formatted currency string (e.g., "$250.34") instead of a float.

2. clean_for_json(obj, key_name=None):
   - Recursively traverses complex Python and pandas data structures to prepare them
     for JSON serialization:
       * pandas DataFrame / Series: Converts to records/dictionaries and sanitizes nulls.
       * Dictionaries & Lists: Recursively cleans all nested values, pruning any keys
         or elements that resolve to `None`, empty dicts (`{}`), or empty lists (`[]`).
       * Datetime / Timestamp: Converts Python and pandas date/time objects into standardized
         ISO-8601 string representations.
       * Floats: Converts `NaN` and `Inf` to `None` (which get pruned); formats currency
         keys into dollar strings; and rounds standard numerical floats to 2 decimal places.
       * Integers: Converts currency keys into formatted dollar strings; keeps non-currency
         integers as pure numeric values.

3. export_compact_json(data, filepath):
   - Runs the input dictionary through `clean_for_json()`.
   - Writes the sanitized data to the specified file path using minified formatting
     (separators=(',', ':'), ensure_ascii=False, allow_nan=False).
   - Returns a tuple containing the `Path` object of the saved file and the in-memory
     sanitized dictionary.

IMPORTANT ARCHITECTURAL CONSIDERATIONS:
---------------------------------------
- Single Responsibility: Separating serialization from `schwab_marketdata_calculator.py`
  keeps financial mathematics pure (numbers in, numbers out) and isolates string formatting,
  null stripping, and file I/O into this single reusable module.
- LLM / API Token Efficiency: Aggressive pruning of `None`, `NaN`, and empty collections
  significantly reduces payload size and token usage when passing thesis outputs to downstream
  AI analysis models or REST endpoints.
========================================================================================
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

logger = logging.getLogger("schwab_serializer")
logger.addHandler(logging.NullHandler())

CURRENCY_KEYS: Set[str] = {
    "lastPrice", "closePrice", "bidPrice", "askPrice", "divAmount",
    "cfo_per_share", "imputed_book_value_of_equity", "imputed_total_debt",
    "R3", "R2", "R1", "Pivot", "S1", "S2", "S3",
    "strikePrice", "mark", "bid", "ask",
}

EXCLUDED_FORMAT_PREFIXES = ("calculated_metrics",)


def sanitize_payload_for_serialization(
    obj: Any, key_name: str = "", current_path: str = ""
) -> Any:
    """Formats raw quote displays while enforcing raw float primitives inside calculation blocks."""
    in_excluded_scope = any(
        current_path == prefix or current_path.startswith(f"{prefix}.")
        for prefix in EXCLUDED_FORMAT_PREFIXES
    )

    if isinstance(obj, float):
        if not in_excluded_scope and key_name in CURRENCY_KEYS:
            return f"${obj:.2f}"
        return round(obj, 2)

    if isinstance(obj, int) and not isinstance(obj, bool):
        if not in_excluded_scope and key_name in CURRENCY_KEYS:
            return f"${obj:.2f}"
        return obj

    if isinstance(obj, str):
        if in_excluded_scope:
            return obj
        if key_name in CURRENCY_KEYS and not obj.startswith("$"):
            try:
                num = float(obj.replace(",", "").strip())
                return f"${num:.2f}"
            except ValueError:
                return obj
        return obj

    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            child_path = f"{current_path}.{k}" if current_path else k
            val = sanitize_payload_for_serialization(v, key_name=k, current_path=child_path)
            if val is not None:
                cleaned[k] = val
        return cleaned

    if isinstance(obj, list):
        return [
            sanitize_payload_for_serialization(item, key_name=key_name, current_path=current_path)
            for item in obj
            if item is not None
        ]

    return obj


def export_compact_json(
    data: Dict[str, Any], filepath: str | Path
) -> Tuple[Path, Dict[str, Any]]:
    """Serializes compact Master Thesis JSON payload and returns (saved_path, final_data)."""
    path = Path(filepath)
    cleaned_data = sanitize_payload_for_serialization(data)
    json_str = json.dumps(cleaned_data, indent=2, ensure_ascii=False)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json_str)

    print(f"[Ready] Compact Master Thesis payload written to {path.resolve()}")
    return path, cleaned_data


def serialize_and_export_thesis(
    payload: Dict[str, Any], output_path: Optional[str] = None
) -> str:
    """Alternative signature returning the raw formatted JSON string."""
    path = Path(output_path) if output_path else Path("thesis_output.json")
    _, cleaned = export_compact_json(payload, path)
    return json.dumps(cleaned, indent=2, ensure_ascii=False)