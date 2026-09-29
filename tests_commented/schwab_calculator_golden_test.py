# Filename.py: schwab_calculator_golden_test.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

# Filename.py: schwab_calculator_golden_test.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

"""
schwab_calculator_golden_test.py

Calculator-layer golden harness for MasterThesisCalculator.calculate_metrics().

Complements tests/schwab_refactor_payload_mock_test.py (which covers the
grounding layer) by pinning the output of the calculator facade itself.

First run: if tests/schwab_calculator_golden.json is absent, the harness
          writes it and passes (self-bootstrap).
Later runs: the harness asserts byte-for-byte dict equality.
"""
# Explain this line: from __future__ import annotations...
# Line: from __future__ import annotations
from __future__ import annotations

# Explain this line: import json...
# Line: import json
import json
# Explain this line: import os...
# Line: import os
import os
# Explain this line: import sys...
# Line: import sys
import sys

# Explain this line: import numpy as np...
# Line: import numpy as np
import numpy as np
# Explain this line: import pandas as pd...
# Line: import pandas as pd
import pandas as pd
# Explain this line: import pytest...
# Line: import pytest
import pytest

# Explain this line: _THIS_DIR = os.path.dirname(os.path.absp...
# Line: _THIS_DIR = os.path.dirname(os.path.abspath(__file
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# Explain this line: _SRC_DIR = os.path.join(os.path.dirname(...
# Line: _SRC_DIR = os.path.join(os.path.dirname(_THIS_DIR)
_SRC_DIR = os.path.join(os.path.dirname(_THIS_DIR), "src")
# Explain this line: if _SRC_DIR not in sys.path:...
# Line: if _SRC_DIR not in sys.path:
if _SRC_DIR not in sys.path:
    # Explain this line: sys.path.insert(0, _SRC_DIR)...
    # Line: sys.path.insert(0, _SRC_DIR)
    sys.path.insert(0, _SRC_DIR)

# Explain this line: from schwab_marketdata_calculator import...
# Line: from schwab_marketdata_calculator import MasterThe
from schwab_marketdata_calculator import MasterThesisCalculator  # noqa: E402

# Explain this line: _GOLDEN_PATH = os.path.join(_THIS_DIR, "...
# Line: _GOLDEN_PATH = os.path.join(_THIS_DIR, "schwab_cal
_GOLDEN_PATH = os.path.join(_THIS_DIR, "schwab_calculator_golden.json")


# Explain this line: def _price_history(n=260, base=100.0, se...
# Line: def _price_history(n=260, base=100.0, seed=7):
def _price_history(n=260, base=100.0, seed=7):
    # Explain this line: rng = np.random.default_rng(seed)...
    # Line: rng = np.random.default_rng(seed)
    rng = np.random.default_rng(seed)
    # Explain this line: idx = pd.date_range("2023-01-01", period...
    # Line: idx = pd.date_range("2023-01-01", periods=n, freq=
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    # Explain this line: rets = rng.normal(0.0, 0.012, size=n)...
    # Line: rets = rng.normal(0.0, 0.012, size=n)
    rets = rng.normal(0.0, 0.012, size=n)
    # Explain this line: close = base * np.exp(np.cumsum(rets))...
    # Line: close = base * np.exp(np.cumsum(rets))
    close = base * np.exp(np.cumsum(rets))
    # Explain this line: high = close * (1.0 + np.abs(rng.normal(...
    # Line: high = close * (1.0 + np.abs(rng.normal(0.0, 0.004
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.004, size=n)))
    # Explain this line: low = close * (1.0 - np.abs(rng.normal(0...
    # Line: low = close * (1.0 - np.abs(rng.normal(0.0, 0.004,
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.004, size=n)))
    # Explain this line: open_ = np.concatenate([[close[0]], clos...
    # Line: open_ = np.concatenate([[close[0]], close[:-1]])
    open_ = np.concatenate([[close[0]], close[:-1]])
    # Explain this line: return pd.DataFrame({"datetime": idx, "o...
    # Line: return pd.DataFrame({"datetime": idx, "open": open
    return pd.DataFrame({"datetime": idx, "open": open_, "high": high, "low": low, "close": close})


# Explain this line: def _options(spot=100.0, dtes=(7, 21, 35...
# Line: def _options(spot=100.0, dtes=(7, 21, 35, 60), see
def _options(spot=100.0, dtes=(7, 21, 35, 60), seed=11):
    # Explain this line: rng = np.random.default_rng(seed)...
    # Line: rng = np.random.default_rng(seed)
    rng = np.random.default_rng(seed)
    # Explain this line: rows = []...
    # Line: rows = []
    rows = []
    # Explain this line: for dte in dtes:...
    # Line: for dte in dtes:
    for dte in dtes:
        # Explain this line: for k_off in (-0.10, -0.05, 0.0, 0.05, 0...
        # Line: for k_off in (-0.10, -0.05, 0.0, 0.05, 0.10):
        for k_off in (-0.10, -0.05, 0.0, 0.05, 0.10):
            # Explain this line: strike = round(spot * (1.0 + k_off), 2)...
            # Line: strike = round(spot * (1.0 + k_off), 2)
            strike = round(spot * (1.0 + k_off), 2)
            # Explain this line: for pc in ("PUT", "CALL"):...
            # Line: for pc in ("PUT", "CALL"):
            for pc in ("PUT", "CALL"):
                # Explain this line: delta = (-1 if pc == "PUT" else 1) * max...
                # Line: delta = (-1 if pc == "PUT" else 1) * max(0.05, 0.5
                delta = (-1 if pc == "PUT" else 1) * max(0.05, 0.5 - abs(k_off) * 3.0)
                # Explain this line: iv = 0.25 + abs(k_off) * 1.2 + rng.norma...
                # Line: iv = 0.25 + abs(k_off) * 1.2 + rng.normal(0.0, 0.0
                iv = 0.25 + abs(k_off) * 1.2 + rng.normal(0.0, 0.005)
                # Explain this line: mark = max(0.05, spot * 0.02 * (1.0 + ab...
                # Line: mark = max(0.05, spot * 0.02 * (1.0 + abs(k_off) *
                mark = max(0.05, spot * 0.02 * (1.0 + abs(k_off) * 3.0))
                # Explain this line: rows.append({...
                # Line: rows.append({
                rows.append({
                    # Explain this line: "putCallIndicator": pc,...
                    # Line: "putCallIndicator": pc,
                    "putCallIndicator": pc,
                    # Explain this line: "daysToExpiration": dte,...
                    # Line: "daysToExpiration": dte,
                    "daysToExpiration": dte,
                    # Explain this line: "strikePrice": strike,...
                    # Line: "strikePrice": strike,
                    "strikePrice": strike,
                    # Explain this line: "delta": delta,...
                    # Line: "delta": delta,
                    "delta": delta,
                    # Explain this line: "volatility": iv,...
                    # Line: "volatility": iv,
                    "volatility": iv,
                    # Explain this line: "mark": mark,...
                    # Line: "mark": mark,
                    "mark": mark,
                    # Explain this line: "bid": round(mark * 0.98, 2),...
                    # Line: "bid": round(mark * 0.98, 2),
                    "bid": round(mark * 0.98, 2),
                    # Explain this line: "ask": round(mark * 1.02, 2),...
                    # Line: "ask": round(mark * 1.02, 2),
                    "ask": round(mark * 1.02, 2),
                    # Explain this line: "totalVolume": int(rng.integers(10, 5000...
                    # Line: "totalVolume": int(rng.integers(10, 5000)),
                    "totalVolume": int(rng.integers(10, 5000)),
                    # Explain this line: "openInterest": int(rng.integers(50, 200...
                    # Line: "openInterest": int(rng.integers(50, 20000)),
                    "openInterest": int(rng.integers(50, 20000)),
                # Explain this line: })...
                # Line: })
                })
    # Explain this line: return pd.DataFrame(rows)...
    # Line: return pd.DataFrame(rows)
    return pd.DataFrame(rows)


# Explain this line: def _build_inputs():...
# Line: def _build_inputs():
def _build_inputs():
    # Explain this line: raw = {...
    # Line: raw = {
    raw = {
        # Explain this line: "phase_0_grounding": {"lastPrice": 102.0...
        # Line: "phase_0_grounding": {"lastPrice": 102.0, "closePr
        "phase_0_grounding": {"lastPrice": 102.0, "closePrice": 101.5, "market_isOpen": True, "quote_age_seconds": 30.0},
        # Explain this line: "step_1_fundamentals": {...
        # Line: "step_1_fundamentals": {
        "step_1_fundamentals": {
            # Explain this line: "peRatio": 22.5, "eps": 4.10, "divAmount...
            # Line: "peRatio": 22.5, "eps": 4.10, "divAmount": 1.20, "
            "peRatio": 22.5, "eps": 4.10, "divAmount": 1.20, "divYield": 1.18,
            # Explain this line: "sharesOutstanding": 1_000_000_000.0, "m...
            # Line: "sharesOutstanding": 1_000_000_000.0, "marketCap":
            "sharesOutstanding": 1_000_000_000.0, "marketCap": 102_500_000_000.0,
            # Explain this line: "eps_state": "VENDOR_PROVIDED", "peRatio...
            # Line: "eps_state": "VENDOR_PROVIDED", "peRatio_state": "
            "eps_state": "VENDOR_PROVIDED", "peRatio_state": "VENDOR_PROVIDED",
            # Explain this line: "shares_outstanding_state": "VENDOR_PROV...
            # Line: "shares_outstanding_state": "VENDOR_PROVIDED",
            "shares_outstanding_state": "VENDOR_PROVIDED",
        # Explain this line: },...
        # Line: },
        },
        # Explain this line: "step_3_and_7_derivatives": {"surface_pa...
        # Line: "step_3_and_7_derivatives": {"surface_parameters":
        "step_3_and_7_derivatives": {"surface_parameters": {"underlyingPrice": 102.0}},
    # Explain this line: }...
    # Line: }
    }
    # Explain this line: return raw, _price_history(), _options(s...
    # Line: return raw, _price_history(), _options(spot=102.0)
    return raw, _price_history(), _options(spot=102.0), {}


# Explain this line: def _nan_aware_equal(a, b):...
# Line: def _nan_aware_equal(a, b):
def _nan_aware_equal(a, b):
    """Deep equality that treats NaN == NaN and keeps numeric type fidelity."""
    # Explain this line: import math...
    # Line: import math
    import math
    # Explain this line: if isinstance(a, dict) and isinstance(b,...
    # Line: if isinstance(a, dict) and isinstance(b, dict):
    if isinstance(a, dict) and isinstance(b, dict):
        # Explain this line: if set(a.keys()) != set(b.keys()):...
        # Line: if set(a.keys()) != set(b.keys()):
        if set(a.keys()) != set(b.keys()):
            # Explain this line: return False...
            # Line: return False
            return False
        # Explain this line: return all(_nan_aware_equal(a[k], b[k]) ...
        # Line: return all(_nan_aware_equal(a[k], b[k]) for k in a
        return all(_nan_aware_equal(a[k], b[k]) for k in a)
    # Explain this line: if isinstance(a, list) and isinstance(b,...
    # Line: if isinstance(a, list) and isinstance(b, list):
    if isinstance(a, list) and isinstance(b, list):
        # Explain this line: if len(a) != len(b):...
        # Line: if len(a) != len(b):
        if len(a) != len(b):
            # Explain this line: return False...
            # Line: return False
            return False
        # Explain this line: return all(_nan_aware_equal(x, y) for x,...
        # Line: return all(_nan_aware_equal(x, y) for x, y in zip(
        return all(_nan_aware_equal(x, y) for x, y in zip(a, b))
    # Explain this line: if isinstance(a, float) and isinstance(b...
    # Line: if isinstance(a, float) and isinstance(b, float):
    if isinstance(a, float) and isinstance(b, float):
        # Explain this line: if math.isnan(a) and math.isnan(b):...
        # Line: if math.isnan(a) and math.isnan(b):
        if math.isnan(a) and math.isnan(b):
            # Explain this line: return True...
            # Line: return True
            return True
    # Explain this line: return a == b...
    # Line: return a == b
    return a == b


# Explain this line: def test_calculator_golden():...
# Line: def test_calculator_golden():
def test_calculator_golden():
    # Explain this line: raw, ph, opt, params = _build_inputs()...
    # Line: raw, ph, opt, params = _build_inputs()
    raw, ph, opt, params = _build_inputs()
    # Explain this line: result = MasterThesisCalculator(raw, ph,...
    # Line: result = MasterThesisCalculator(raw, ph, opt, para
    result = MasterThesisCalculator(raw, ph, opt, params).calculate_metrics()

    # Explain this line: if not os.path.exists(_GOLDEN_PATH):...
    # Line: if not os.path.exists(_GOLDEN_PATH):
    if not os.path.exists(_GOLDEN_PATH):
        # Explain this line: with open(_GOLDEN_PATH, "w") as fh:...
        # Line: with open(_GOLDEN_PATH, "w") as fh:
        with open(_GOLDEN_PATH, "w") as fh:
            # Explain this line: json.dump(result, fh, indent=2, sort_key...
            # Line: json.dump(result, fh, indent=2, sort_keys=True, de
            json.dump(result, fh, indent=2, sort_keys=True, default=str)
        # Explain this line: pytest.skip(f"bootstrapped golden at {_G...
        # Line: pytest.skip(f"bootstrapped golden at {_GOLDEN_PATH
        pytest.skip(f"bootstrapped golden at {_GOLDEN_PATH}")

    # Explain this line: with open(_GOLDEN_PATH) as fh:...
    # Line: with open(_GOLDEN_PATH) as fh:
    with open(_GOLDEN_PATH) as fh:
        # Explain this line: expected = json.load(fh)...
        # Line: expected = json.load(fh)
        expected = json.load(fh)

    # Explain this line: assert _nan_aware_equal(result, expected...
    # Line: assert _nan_aware_equal(result, expected), (
    assert _nan_aware_equal(result, expected), (
        # Explain this line: "calculator output diverged from golden"...
        # Line: "calculator output diverged from golden"
        "calculator output diverged from golden"
    # Explain this line: )...
    # Line: )
    )
