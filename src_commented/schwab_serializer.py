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
schwab_serializer.py

"""

# Explain this line: from __future__ import annotations...
# Line: from __future__ import annotations
from __future__ import annotations
# Explain this line: import json...
# Line: import json
import json
# Explain this line: import logging...
# Line: import logging
import logging
# Explain this line: import math...
# Line: import math
import math
# Explain this line: from pathlib import Path...
# Line: from pathlib import Path
from pathlib import Path
# Explain this line: from typing import Any, Dict, Optional, ...
# Line: from typing import Any, Dict, Optional, Set, Tuple
from typing import Any, Dict, Optional, Set, Tuple
# Explain this line: import numpy as np...
# Line: import numpy as np
import numpy as np
# Explain this line: import pandas as pd...
# Line: import pandas as pd
import pandas as pd

# Explain this line: logger = logging.getLogger("schwab_seria...
# Line: logger = logging.getLogger("schwab_serializer")
logger = logging.getLogger("schwab_serializer")
# Explain this line: logger.addHandler(logging.NullHandler())...
# Line: logger.addHandler(logging.NullHandler())
logger.addHandler(logging.NullHandler())

# Explain this line: CURRENCY_KEYS: Set[str] = {...
# Line: CURRENCY_KEYS: Set[str] = {
CURRENCY_KEYS: Set[str] = {
    # Explain this line: "lastPrice",...
    # Line: "lastPrice",
    "lastPrice",
    # Explain this line: "closePrice",...
    # Line: "closePrice",
    "closePrice",
    # Explain this line: "bidPrice",...
    # Line: "bidPrice",
    "bidPrice",
    # Explain this line: "askPrice",...
    # Line: "askPrice",
    "askPrice",
    # Explain this line: "divAmount",...
    # Line: "divAmount",
    "divAmount",
    # Explain this line: "cfo_per_share",...
    # Line: "cfo_per_share",
    "cfo_per_share",
    # Explain this line: "strikePrice",...
    # Line: "strikePrice",
    "strikePrice",
    # Explain this line: "mark",...
    # Line: "mark",
    "mark",
    # Explain this line: "bid",...
    # Line: "bid",
    "bid",
    # Explain this line: "ask",...
    # Line: "ask",
    "ask",
# Explain this line: }...
# Line: }
}

# Explain this line: PRESERVE_NULL_CONTAINERS: Set[str] = {...
# Line: PRESERVE_NULL_CONTAINERS: Set[str] = {
PRESERVE_NULL_CONTAINERS: Set[str] = {
    # Explain this line: "phase_0_grounding",...
    # Line: "phase_0_grounding",
    "phase_0_grounding",
    # Explain this line: "market_cap_divergence",...
    # Line: "market_cap_divergence",
    "market_cap_divergence",
    # Explain this line: "short_locate_status",...
    # Line: "short_locate_status",
    "short_locate_status",
    # Explain this line: "step_1_fundamentals",...
    # Line: "step_1_fundamentals",
    "step_1_fundamentals",
    # Explain this line: "step_1_fundamentals_and_quality",...
    # Line: "step_1_fundamentals_and_quality",
    "step_1_fundamentals_and_quality",
    # Explain this line: "step_3_and_7_derivatives_and_surface",...
    # Line: "step_3_and_7_derivatives_and_surface",
    "step_3_and_7_derivatives_and_surface",
    # Explain this line: "step_5_technicals_and_flows",...
    # Line: "step_5_technicals_and_flows",
    "step_5_technicals_and_flows",
    # Explain this line: "skew_30d",...
    # Line: "skew_30d",
    "skew_30d",
    # Explain this line: "flow_ratios",...
    # Line: "flow_ratios",
    "flow_ratios",
# Explain this line: }...
# Line: }
}

# Explain this line: SAFE_INTEGER_LIMIT = 2**53 - 1...
# Line: SAFE_INTEGER_LIMIT = 2**53 - 1
SAFE_INTEGER_LIMIT = 2**53 - 1


# Explain this line: def sanitize_payload_for_serialization(...
# Line: def sanitize_payload_for_serialization(
def sanitize_payload_for_serialization(
    # Explain this line: obj: Any, key_name: str = "", current_pa...
    # Line: obj: Any, key_name: str = "", current_path: str =
    obj: Any, key_name: str = "", current_path: str = ""
# Explain this line: ) -> Any:...
# Line: ) -> Any:
) -> Any:
    # Explain this line: if isinstance(obj, (pd.DataFrame, pd.Ser...
    # Line: if isinstance(obj, (pd.DataFrame, pd.Series)):
    if isinstance(obj, (pd.DataFrame, pd.Series)):
        # Explain this line: return sanitize_payload_for_serializatio...
        # Line: return sanitize_payload_for_serialization(
        return sanitize_payload_for_serialization(
            # Explain this line: obj.to_dict(), key_name=key_name, curren...
            # Line: obj.to_dict(), key_name=key_name, current_path=cur
            obj.to_dict(), key_name=key_name, current_path=current_path
        # Explain this line: )...
        # Line: )
        )

    # Explain this line: if isinstance(obj, np.ndarray):...
    # Line: if isinstance(obj, np.ndarray):
    if isinstance(obj, np.ndarray):
        # Explain this line: return [...
        # Line: return [
        return [
            # Explain this line: sanitize_payload_for_serialization(...
            # Line: sanitize_payload_for_serialization(
            sanitize_payload_for_serialization(
                # Explain this line: item, key_name=key_name, current_path=cu...
                # Line: item, key_name=key_name, current_path=current_path
                item, key_name=key_name, current_path=current_path
            # Explain this line: )...
            # Line: )
            )
            # Explain this line: for item in obj.tolist()...
            # Line: for item in obj.tolist()
            for item in obj.tolist()
        # Explain this line: ]...
        # Line: ]
        ]

    # Explain this line: root_section = current_path.split(".")[0...
    # Line: root_section = current_path.split(".")[0] if curre
    root_section = current_path.split(".")[0] if current_path else ""
    # Explain this line: in_calc_scope = (root_section == "calcul...
    # Line: in_calc_scope = (root_section == "calculated_metri
    in_calc_scope = (root_section == "calculated_metrics")

    # Explain this line: if isinstance(obj, (np.floating, float))...
    # Line: if isinstance(obj, (np.floating, float)):
    if isinstance(obj, (np.floating, float)):
        # Explain this line: if math.isnan(obj) or math.isinf(obj):...
        # Line: if math.isnan(obj) or math.isinf(obj):
        if math.isnan(obj) or math.isinf(obj):
            # Explain this line: return None...
            # Line: return None
            return None
        # Explain this line: if not in_calc_scope and key_name in CUR...
        # Line: if not in_calc_scope and key_name in CURRENCY_KEYS
        if not in_calc_scope and key_name in CURRENCY_KEYS:
            # Explain this line: return f"${float(obj):,.2f}"...
            # Line: return f"${float(obj):,.2f}"
            return f"${float(obj):,.2f}"
        # Explain this line: if in_calc_scope:...
        # Line: if in_calc_scope:
        if in_calc_scope:
            # Explain this line: flt_val = float(obj)...
            # Line: flt_val = float(obj)
            flt_val = float(obj)
            # Explain this line: return 0.0 if (flt_val == 0.0 or abs(flt...
            # Line: return 0.0 if (flt_val == 0.0 or abs(flt_val) < 1e
            return 0.0 if (flt_val == 0.0 or abs(flt_val) < 1e-12) else flt_val
        # Explain this line: v = round(float(obj), 2)...
        # Line: v = round(float(obj), 2)
        v = round(float(obj), 2)
        # Explain this line: return 0.0 if (v == 0.0 or abs(v) < 1e-1...
        # Line: return 0.0 if (v == 0.0 or abs(v) < 1e-12) else v
        return 0.0 if (v == 0.0 or abs(v) < 1e-12) else v

    # Explain this line: if isinstance(obj, (np.integer, int)) an...
    # Line: if isinstance(obj, (np.integer, int)) and not isin
    if isinstance(obj, (np.integer, int)) and not isinstance(obj, (bool, np.bool_)):
        # Explain this line: int_val = int(obj)...
        # Line: int_val = int(obj)
        int_val = int(obj)
        # Explain this line: if not in_calc_scope and key_name in CUR...
        # Line: if not in_calc_scope and key_name in CURRENCY_KEYS
        if not in_calc_scope and key_name in CURRENCY_KEYS:
            # Explain this line: if abs(int_val) > SAFE_INTEGER_LIMIT:...
            # Line: if abs(int_val) > SAFE_INTEGER_LIMIT:
            if abs(int_val) > SAFE_INTEGER_LIMIT:
                # Explain this line: return f"${int_val:,}"...
                # Line: return f"${int_val:,}"
                return f"${int_val:,}"
            # Explain this line: return f"${float(int_val):,.2f}"...
            # Line: return f"${float(int_val):,.2f}"
            return f"${float(int_val):,.2f}"
        # Explain this line: return int_val...
        # Line: return int_val
        return int_val

    # Explain this line: if isinstance(obj, (bool, np.bool_)):...
    # Line: if isinstance(obj, (bool, np.bool_)):
    if isinstance(obj, (bool, np.bool_)):
        # Explain this line: return bool(obj)...
        # Line: return bool(obj)
        return bool(obj)

    # Explain this line: if isinstance(obj, str):...
    # Line: if isinstance(obj, str):
    if isinstance(obj, str):
        # Explain this line: if in_calc_scope:...
        # Line: if in_calc_scope:
        if in_calc_scope:
            # Explain this line: return obj...
            # Line: return obj
            return obj
        # Explain this line: if key_name in CURRENCY_KEYS and not obj...
        # Line: if key_name in CURRENCY_KEYS and not obj.startswit
        if key_name in CURRENCY_KEYS and not obj.startswith("$"):
            # Explain this line: try:...
            # Line: try:
            try:
                # Explain this line: num = float(obj.replace(",", "").strip()...
                # Line: num = float(obj.replace(",", "").strip())
                num = float(obj.replace(",", "").strip())
                # Explain this line: return f"${num:,.2f}"...
                # Line: return f"${num:,.2f}"
                return f"${num:,.2f}"
            # Explain this line: except ValueError:...
            # Line: except ValueError:
            except ValueError:
                # Explain this line: return obj...
                # Line: return obj
                return obj
        # Explain this line: return obj...
        # Line: return obj
        return obj

    # Explain this line: if isinstance(obj, dict):...
    # Line: if isinstance(obj, dict):
    if isinstance(obj, dict):
        # Explain this line: current_container = current_path.split("...
        # Line: current_container = current_path.split(".")[-1] if
        current_container = current_path.split(".")[-1] if current_path else ""
        # Explain this line: preserve_nulls = current_container in PR...
        # Line: preserve_nulls = current_container in PRESERVE_NUL
        preserve_nulls = current_container in PRESERVE_NULL_CONTAINERS
        # Explain this line: cleaned: Dict[str, Any] = {}...
        # Line: cleaned: Dict[str, Any] = {}
        cleaned: Dict[str, Any] = {}
        # Explain this line: for k, v in obj.items():...
        # Line: for k, v in obj.items():
        for k, v in obj.items():
            # Explain this line: child_path = f"{current_path}.{k}" if cu...
            # Line: child_path = f"{current_path}.{k}" if current_path
            child_path = f"{current_path}.{k}" if current_path else str(k)
            # Explain this line: val = sanitize_payload_for_serialization...
            # Line: val = sanitize_payload_for_serialization(
            val = sanitize_payload_for_serialization(
                # Explain this line: v, key_name=str(k), current_path=child_p...
                # Line: v, key_name=str(k), current_path=child_path
                v, key_name=str(k), current_path=child_path
            # Explain this line: )...
            # Line: )
            )
            # Explain this line: if val is not None or preserve_nulls:...
            # Line: if val is not None or preserve_nulls:
            if val is not None or preserve_nulls:
                # Explain this line: cleaned[str(k)] = val...
                # Line: cleaned[str(k)] = val
                cleaned[str(k)] = val
        # Explain this line: return cleaned...
        # Line: return cleaned
        return cleaned

    # Explain this line: if isinstance(obj, (list, tuple, set)):...
    # Line: if isinstance(obj, (list, tuple, set)):
    if isinstance(obj, (list, tuple, set)):
        # Explain this line: return [...
        # Line: return [
        return [
            # Explain this line: sanitize_payload_for_serialization(...
            # Line: sanitize_payload_for_serialization(
            sanitize_payload_for_serialization(
                # Explain this line: item, key_name=key_name, current_path=cu...
                # Line: item, key_name=key_name, current_path=current_path
                item, key_name=key_name, current_path=current_path
            # Explain this line: )...
            # Line: )
            )
            # Explain this line: for item in obj...
            # Line: for item in obj
            for item in obj
            # Explain this line: if item is not None...
            # Line: if item is not None
            if item is not None
        # Explain this line: ]...
        # Line: ]
        ]

    # Explain this line: if obj is None or pd.isna(obj):...
    # Line: if obj is None or pd.isna(obj):
    if obj is None or pd.isna(obj):
        # Explain this line: return None...
        # Line: return None
        return None

    # Explain this line: return obj...
    # Line: return obj
    return obj


# Explain this line: def clean_for_json(data: Any, path: str ...
# Line: def clean_for_json(data: Any, path: str = "") -> A
def clean_for_json(data: Any, path: str = "") -> Any:
    # Explain this line: return sanitize_payload_for_serializatio...
    # Line: return sanitize_payload_for_serialization(data, cu
    return sanitize_payload_for_serialization(data, current_path=path)


# Explain this line: def export_compact_json(...
# Line: def export_compact_json(
def export_compact_json(
    # Explain this line: data: Dict[str, Any], filepath: str | Pa...
    # Line: data: Dict[str, Any], filepath: str | Path
    data: Dict[str, Any], filepath: str | Path
# Explain this line: ) -> Tuple[Path, Dict[str, Any]]:...
# Line: ) -> Tuple[Path, Dict[str, Any]]:
) -> Tuple[Path, Dict[str, Any]]:
    # Explain this line: path = Path(filepath)...
    # Line: path = Path(filepath)
    path = Path(filepath)
    # Explain this line: cleaned_data = sanitize_payload_for_seri...
    # Line: cleaned_data = sanitize_payload_for_serialization(
    cleaned_data = sanitize_payload_for_serialization(data)
    # Explain this line: json_str = json.dumps(...
    # Line: json_str = json.dumps(
    json_str = json.dumps(
        # Explain this line: cleaned_data, separators=(",", ":"), ens...
        # Line: cleaned_data, separators=(",", ":"), ensure_ascii=
        cleaned_data, separators=(",", ":"), ensure_ascii=False, default=str
    # Explain this line: )...
    # Line: )
    )
    # Explain this line: path.parent.mkdir(parents=True, exist_ok...
    # Line: path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Explain this line: with open(path, "w", encoding="utf-8") a...
    # Line: with open(path, "w", encoding="utf-8") as f:
    with open(path, "w", encoding="utf-8") as f:
        # Explain this line: f.write(json_str)...
        # Line: f.write(json_str)
        f.write(json_str)
    # Explain this line: return path, cleaned_data...
    # Line: return path, cleaned_data
    return path, cleaned_data


# Explain this line: def serialize_and_export_thesis(...
# Line: def serialize_and_export_thesis(
def serialize_and_export_thesis(
    # Explain this line: payload: Dict[str, Any], output_path: Op...
    # Line: payload: Dict[str, Any], output_path: Optional[str
    payload: Dict[str, Any], output_path: Optional[str] = None
# Explain this line: ) -> str:...
# Line: ) -> str:
) -> str:
    # Explain this line: path = Path(output_path) if output_path ...
    # Line: path = Path(output_path) if output_path else Path(
    path = Path(output_path) if output_path else Path("thesis_output.json")
    # Explain this line: _, cleaned = export_compact_json(payload...
    # Line: _, cleaned = export_compact_json(payload, path)
    _, cleaned = export_compact_json(payload, path)
    # Explain this line: return json.dumps(...
    # Line: return json.dumps(
    return json.dumps(
        # Explain this line: cleaned, separators=(",", ":"), ensure_a...
        # Line: cleaned, separators=(",", ":"), ensure_ascii=False
        cleaned, separators=(",", ":"), ensure_ascii=False, default=str
    # Explain this line: )...
    # Line: )
    )