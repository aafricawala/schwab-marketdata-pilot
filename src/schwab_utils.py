# schwab_utils.py
from __future__ import annotations
import math
import re
from typing import Any, Optional
import pandas as pd

RE_VALID_SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,9}$")
RESERVED_ENVELOPE_KEYS = {
    "QUOTE",
    "REFERENCE",
    "FUNDAMENTAL",
    "FUND",
    "ASSETMAINTYPE",
    "ASSETSUBTYPE",
    "DESCRIPTION",
}


def validate_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise TypeError(f"Symbol must be a string, received {type(symbol).__name__}")
    clean = symbol.strip().upper()
    if not clean:
        raise ValueError("Symbol cannot be empty.")
    if clean in RESERVED_ENVELOPE_KEYS:
        raise ValueError(f"Symbol '{clean}' collides with reserved broker envelope keys.")
    if not RE_VALID_SYMBOL.match(clean):
        raise ValueError(f"Symbol '{clean}' contains invalid characters or exceeds 10 chars.")
    return clean


def safe_float(v: Any) -> Optional[float]:
    if v is None or pd.isna(v):
        return None
    if not isinstance(v, (str, int, float)):
        return None
    try:
        f = float(str(v).replace("$", "").replace(",", "").strip())
        if math.isnan(f) or math.isinf(f):
            return None
        return 0.0 if (f == 0.0 or abs(f) < 1e-12) else f
    except (ValueError, TypeError):
        return None


def safe_div(n: Any, d: Any) -> Optional[float]:
    fn, fd = safe_float(n), safe_float(d)
    if fn is None or fd is None or fd == 0.0:
        return None
    res = fn / fd
    return None if math.isnan(res) or math.isinf(res) else res