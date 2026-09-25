"""
schwab_serializer.py
========================================================================================
Institutional Charles Schwab Data Sanitizer, Formatter & Serialization Engine (v16.21)
========================================================================================
Defensively handles NumPy scalars, multi-element arrays/DataFrames, and formats
raw quotes while preserving bare float primitives in calculated_metrics.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

import numpy as np
import pandas as pd

# Explicit registry of field names formatted as standard currency values
CURRENCY_KEYS: Set[str] = {
    "lastPrice",
    "closePrice",
    "bidPrice",
    "askPrice",
    "divAmount",
    "cfo_per_share",
    "imputed_book_value_of_equity",
    "imputed_total_debt",
    "R3",
    "R2",
    "R1",
    "Pivot",
    "S1",
    "S2",
    "S3",
    "strikePrice",
    "mark",
    "bid",
    "ask",
}

# Scopes strictly excluded from string currency formatting
EXCLUDED_FORMAT_PREFIXES: Tuple[str, ...] = ("calculated_metrics",)


def sanitize_payload_for_serialization(
    obj: Any, key_name: str = "", current_path: str = ""
) -> Any:
    """
    Recursively transforms data structures into minified JSON-compliant primitives:
      - Safely dispatches DataFrames, Series, and NumPy arrays before scalar checks.
      - Converts NumPy integers, floats, and booleans to native Python types.
      - Keeps calculated_metrics values as bare numeric primitives (floats/ints).
      - Converts datetimes and timestamps to ISO-8601 strings.
      - Strips NaNs, infinities, and None values.
    """
    # 1. Container Handling (Must occur BEFORE pd.isna scalar checks)
    if isinstance(obj, pd.DataFrame):
        sanitized_df = obj.where(pd.notnull(obj), None)
        return [
            sanitize_payload_for_serialization(row, key_name=key_name, current_path=current_path)
            for row in sanitized_df.to_dict(orient="records")
        ]

    if isinstance(obj, pd.Series):
        sanitized_s = obj.where(pd.notnull(obj), None)
        return sanitize_payload_for_serialization(
            sanitized_s.to_dict(), key_name=key_name, current_path=current_path
        )

    if isinstance(obj, np.ndarray):
        return [
            sanitize_payload_for_serialization(item, key_name=key_name, current_path=current_path)
            for item in obj.tolist()
        ]

    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in obj.items():
            child_path = f"{current_path}.{k}" if current_path else str(k)
            val = sanitize_payload_for_serialization(v, key_name=str(k), current_path=child_path)
            if val is not None:
                cleaned[str(k)] = val
        return cleaned

    if isinstance(obj, (list, tuple, set)):
        cleaned_list = [
            sanitize_payload_for_serialization(item, key_name=key_name, current_path=current_path)
            for item in obj
        ]
        return [item for item in cleaned_list if item is not None]

    # 2. Scalar Null, NaN, and Inf Checks
    if obj is None:
        return None
    try:
        if pd.isna(obj):
            return None
    except (ValueError, TypeError):
        pass

    # 3. NumPy / Pandas Primitive Conversions
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        obj = int(obj)
    elif isinstance(obj, (np.floating,)):
        obj = float(obj)

    # 4. Path Scoping Check
    in_excluded_scope = any(
        current_path == prefix or current_path.startswith(f"{prefix}.")
        for prefix in EXCLUDED_FORMAT_PREFIXES
    )

    # 5. Floating Point Handling
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        if not in_excluded_scope and key_name in CURRENCY_KEYS:
            return f"${obj:,.2f}"
        return round(obj, 4) if in_excluded_scope else round(obj, 2)

    # 6. Integer Handling (Exclude booleans)
    if isinstance(obj, int) and not isinstance(obj, bool):
        if not in_excluded_scope and key_name in CURRENCY_KEYS:
            return f"${float(obj):,.2f}"
        return int(obj)

    # 7. String Handling
    if isinstance(obj, str):
        if in_excluded_scope:
            return obj
        if key_name in CURRENCY_KEYS and not obj.startswith("$"):
            try:
                num = float(obj.replace(",", "").strip())
                return f"${num:,.2f}"
            except ValueError:
                return obj
        return obj

    # 8. Date / Time Handling
    if isinstance(obj, (datetime, date, pd.Timestamp)):
        return obj.isoformat()

    return obj


def _json_default_fallback(o: Any) -> Any:
    """Defensive fallback handler for json.dumps."""
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (datetime, date, pd.Timestamp)):
        return o.isoformat()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")


def export_compact_json(
    data: Dict[str, Any], filepath: str | Path
) -> Tuple[Path, Dict[str, Any]]:
    """Serializes compact Master Thesis JSON payload and returns (saved_path, final_data)."""
    path = Path(filepath)
    cleaned_data = sanitize_payload_for_serialization(data)
    json_str = json.dumps(
        cleaned_data,
        indent=2,
        ensure_ascii=False,
        default=_json_default_fallback,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json_str)

    return path, cleaned_data


def serialize_and_export_thesis(
    payload: Dict[str, Any], output_path: Optional[str] = None
) -> str:
    """Alternative signature returning the raw formatted JSON string."""
    path = Path(output_path) if output_path else Path("thesis_output.json")
    _, cleaned = export_compact_json(payload, path)
    return json.dumps(cleaned, indent=2, ensure_ascii=False, default=_json_default_fallback)
