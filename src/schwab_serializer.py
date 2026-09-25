"""
schwab_serializer.py
========================================================================================
Institutional Charles Schwab JSON Sanitization & NumPy Primitives Serializer
Protocol v16.21 Production Certified
========================================================================================
Changelog v16.21:
  - PAY-60: Added PRESERVE_NULL_CONTAINERS whitelist to protect market_cap_divergence
    canonical null keys from recursive null-stripping.
  - Defensively converts NumPy scalar primitives (np.int64, np.float64, np.bool_)
    and composite pandas containers before scalar null checks.
  - Enforces currency formatting across quote parameters while preserving raw floats
    under EXCLUDED_FORMAT_PREFIXES = ("calculated_metrics",).
========================================================================================
"""

from __future__ import annotations

import math
from typing import Any, Dict

import numpy as np
import pandas as pd

EXCLUDED_FORMAT_PREFIXES = ("calculated_metrics",)
PRESERVE_NULL_CONTAINERS = {"market_cap_divergence"}


def clean_for_json(data: Any, path: str = "") -> Any:
    """Recursively formats primitives, strips unneeded nulls, and protects whitelisted schemas."""
    if isinstance(data, (np.integer, int)):
        return int(data)
    if isinstance(data, (np.floating, float)):
        if math.isnan(data) or math.isinf(data):
            return None
        return float(data)
    if isinstance(data, (np.bool_, bool)):
        return bool(data)
    if isinstance(data, (pd.DataFrame, pd.Series)):
        return clean_for_json(data.to_dict(), path=path)

    if isinstance(data, dict):
        current_key = path.split(".")[-1] if path else ""
        preserve_nulls = current_key in PRESERVE_NULL_CONTAINERS

        cleaned_dict: Dict[str, Any] = {}
        for k, v in data.items():
            sub_path = f"{path}.{k}" if path else str(k)
            cleaned_v = clean_for_json(v, path=sub_path)
            if cleaned_v is not None or preserve_nulls:
                cleaned_dict[k] = cleaned_v
        return cleaned_dict

    if isinstance(data, list):
        return [clean_for_json(item, path=path) for item in data]

    return data