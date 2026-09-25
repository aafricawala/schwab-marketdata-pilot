"""
schwab_serializer.py
========================================================================================
Institutional Charles Schwab JSON Sanitization & Serializer (Protocol v16.21)
========================================================================================
Guarantees:
  - Whitelist preservation (PRESERVE_NULL_CONTAINERS): market_cap_divergence, 
    short_locate_status, step_1_fundamentals (preserves margin_fields_suspect: null).
  - Prefix exclusion (EXCLUDED_FORMAT_PREFIXES): Preserves bare float primitives.
  - Recursively formats quote strings without polluting pure mathematical blocks.
========================================================================================
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("schwab_serializer")
logger.addHandler(logging.NullHandler())

CURRENCY_KEYS: Set[str] = {
    "lastPrice", "closePrice", "bidPrice", "askPrice", "divAmount",
    "cfo_per_share", "strikePrice", "mark", "bid", "ask",
}

EXCLUDED_FORMAT_PREFIXES: Tuple[str, ...] = (
    "calculated_metrics",
    "step_1_fundamentals_and_quality",
    "step_5_technicals_and_flows",
    "step_3_and_7_derivatives_and_surface",
)

PRESERVE_NULL_CONTAINERS: Set[str] = {
    "market_cap_divergence",
    "short_locate_status",
    "step_1_fundamentals",
}


def sanitize_payload_for_serialization(
    obj: Any, key_name: str = "", current_path: str = ""
) -> Any:
    """Recursively formats raw quotes while preserving bare float primitives in calculation blocks."""
    if isinstance(obj, (pd.DataFrame, pd.Series)):
        return sanitize_payload_for_serialization(
            obj.to_dict(), key_name=key_name, current_path=current_path
        )

    if isinstance(obj, np.ndarray):
        return [
            sanitize_payload_for_serialization(item, key_name=key_name, current_path=current_path)
            for item in obj.tolist()
        ]

    in_excluded_scope = any(
        current_path == prefix or current_path.startswith(f"{prefix}.")
        for prefix in EXCLUDED_FORMAT_PREFIXES
    )

    if isinstance(obj, (np.floating, float)):
        if math.isnan(obj) or math.isinf(obj):
            return None
        if not in_excluded_scope and key_name in CURRENCY_KEYS:
            return f"${float(obj):,.2f}"
        return float(obj) if in_excluded_scope else round(float(obj), 2)

    if isinstance(obj, (np.integer, int)) and not isinstance(obj, (bool, np.bool_)):
        if not in_excluded_scope and key_name in CURRENCY_KEYS:
            return f"${float(obj):,.2f}"
        return int(obj)

    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)

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

    if isinstance(obj, dict):
        current_container = current_path.split(".")[-1] if current_path else ""
        preserve_nulls = current_container in PRESERVE_NULL_CONTAINERS

        cleaned: Dict[str, Any] = {}
        for k, v in obj.items():
            child_path = f"{current_path}.{k}" if current_path else str(k)
            val = sanitize_payload_for_serialization(v, key_name=str(k), current_path=child_path)
            if val is not None or preserve_nulls:
                cleaned[str(k)] = val
        return cleaned

    if isinstance(obj, (list, tuple, set)):
        return [
            sanitize_payload_for_serialization(item, key_name=key_name, current_path=current_path)
            for item in obj
            if item is not None
        ]

    if obj is None or pd.isna(obj):
        return None

    return obj


def clean_for_json(data: Any, path: str = "") -> Any:
    """Public interface for dictionary sanitization."""
    return sanitize_payload_for_serialization(data, current_path=path)


def export_compact_json(
    data: Dict[str, Any], filepath: str | Path
) -> Tuple[Path, Dict[str, Any]]:
    """Minifies Master Thesis JSON payload and writes to disk."""
    path = Path(filepath)
    cleaned_data = sanitize_payload_for_serialization(data)
    json_str = json.dumps(
        cleaned_data,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json_str)

    return path, cleaned_data


def serialize_and_export_thesis(
    payload: Dict[str, Any], output_path: Optional[str] = None
) -> str:
    """Returns raw minified JSON string."""
    path = Path(output_path) if output_path else Path("thesis_output.json")
    _, cleaned = export_compact_json(payload, path)
    return json.dumps(cleaned, separators=(",", ":"), ensure_ascii=False, default=str)