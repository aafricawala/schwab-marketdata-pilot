"""
schwab_serializer.py

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
    "lastPrice",
    "closePrice",
    "bidPrice",
    "askPrice",
    "divAmount",
    "cfo_per_share",
    "strikePrice",
    "mark",
    "bid",
    "ask",
}

PRESERVE_NULL_CONTAINERS: Set[str] = {
    "phase_0_grounding",
    "market_cap_divergence",
    "short_locate_status",
    "step_1_fundamentals",
    "step_1_fundamentals_and_quality",
    "step_3_and_7_derivatives_and_surface",
    "step_5_technicals_and_flows",
    "skew_30d",
    "flow_ratios",
}

SAFE_INTEGER_LIMIT = 2**53 - 1


def sanitize_payload_for_serialization(
    obj: Any, key_name: str = "", current_path: str = ""
) -> Any:
    if isinstance(obj, (pd.DataFrame, pd.Series)):
        return sanitize_payload_for_serialization(
            obj.to_dict(), key_name=key_name, current_path=current_path
        )

    if isinstance(obj, np.ndarray):
        return [
            sanitize_payload_for_serialization(
                item, key_name=key_name, current_path=current_path
            )
            for item in obj.tolist()
        ]

    root_section = current_path.split(".")[0] if current_path else ""
    in_calc_scope = (root_section == "calculated_metrics")

    if isinstance(obj, (np.floating, float)):
        if math.isnan(obj) or math.isinf(obj):
            return None
        if not in_calc_scope and key_name in CURRENCY_KEYS:
            return f"${float(obj):,.2f}"
        if in_calc_scope:
            flt_val = float(obj)
            return 0.0 if (flt_val == 0.0 or abs(flt_val) < 1e-12) else flt_val
        v = round(float(obj), 2)
        return 0.0 if (v == 0.0 or abs(v) < 1e-12) else v

    if isinstance(obj, (np.integer, int)) and not isinstance(obj, (bool, np.bool_)):
        int_val = int(obj)
        if not in_calc_scope and key_name in CURRENCY_KEYS:
            if abs(int_val) > SAFE_INTEGER_LIMIT:
                return f"${int_val:,}"
            return f"${float(int_val):,.2f}"
        return int_val

    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)

    if isinstance(obj, str):
        if in_calc_scope:
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
            val = sanitize_payload_for_serialization(
                v, key_name=str(k), current_path=child_path
            )
            if val is not None or preserve_nulls:
                cleaned[str(k)] = val
        return cleaned

    if isinstance(obj, (list, tuple, set)):
        return [
            sanitize_payload_for_serialization(
                item, key_name=key_name, current_path=current_path
            )
            for item in obj
            if item is not None
        ]

    if obj is None or pd.isna(obj):
        return None

    return obj


def clean_for_json(data: Any, path: str = "") -> Any:
    return sanitize_payload_for_serialization(data, current_path=path)


def export_compact_json(
    data: Dict[str, Any], filepath: str | Path
) -> Tuple[Path, Dict[str, Any]]:
    path = Path(filepath)
    cleaned_data = sanitize_payload_for_serialization(data)
    json_str = json.dumps(
        cleaned_data, separators=(",", ":"), ensure_ascii=False, default=str
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json_str)
    return path, cleaned_data


def serialize_and_export_thesis(
    payload: Dict[str, Any], output_path: Optional[str] = None
) -> str:
    path = Path(output_path) if output_path else Path("thesis_output.json")
    _, cleaned = export_compact_json(payload, path)
    return json.dumps(
        cleaned, separators=(",", ":"), ensure_ascii=False, default=str
    )