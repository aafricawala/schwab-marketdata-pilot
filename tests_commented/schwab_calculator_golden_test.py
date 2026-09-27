"""
schwab_calculator_golden_test.py

Calculator-layer golden harness for MasterThesisCalculator.calculate_metrics().

Complements tests/schwab_refactor_payload_mock_test.py (which covers the
grounding layer) by pinning the output of the calculator facade itself.

First run: if tests/schwab_calculator_golden.json is absent, the harness
          writes it and passes (self-bootstrap).
Later runs: the harness asserts byte-for-byte dict equality.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(os.path.dirname(_THIS_DIR), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from schwab_marketdata_calculator import MasterThesisCalculator  # noqa: E402

_GOLDEN_PATH = os.path.join(_THIS_DIR, "schwab_calculator_golden.json")


def _price_history(n=260, base=100.0, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    rets = rng.normal(0.0, 0.012, size=n)
    close = base * np.exp(np.cumsum(rets))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.004, size=n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.004, size=n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"datetime": idx, "open": open_, "high": high, "low": low, "close": close})


def _options(spot=100.0, dtes=(7, 21, 35, 60), seed=11):
    rng = np.random.default_rng(seed)
    rows = []
    for dte in dtes:
        for k_off in (-0.10, -0.05, 0.0, 0.05, 0.10):
            strike = round(spot * (1.0 + k_off), 2)
            for pc in ("PUT", "CALL"):
                delta = (-1 if pc == "PUT" else 1) * max(0.05, 0.5 - abs(k_off) * 3.0)
                iv = 0.25 + abs(k_off) * 1.2 + rng.normal(0.0, 0.005)
                mark = max(0.05, spot * 0.02 * (1.0 + abs(k_off) * 3.0))
                rows.append({
                    "putCallIndicator": pc,
                    "daysToExpiration": dte,
                    "strikePrice": strike,
                    "delta": delta,
                    "volatility": iv,
                    "mark": mark,
                    "bid": round(mark * 0.98, 2),
                    "ask": round(mark * 1.02, 2),
                    "totalVolume": int(rng.integers(10, 5000)),
                    "openInterest": int(rng.integers(50, 20000)),
                })
    return pd.DataFrame(rows)


def _build_inputs():
    raw = {
        "phase_0_grounding": {"lastPrice": 102.0, "closePrice": 101.5, "market_isOpen": True, "quote_age_seconds": 30.0},
        "step_1_fundamentals": {
            "peRatio": 22.5, "eps": 4.10, "divAmount": 1.20, "divYield": 1.18,
            "sharesOutstanding": 1_000_000_000.0, "marketCap": 102_500_000_000.0,
            "eps_state": "VENDOR_PROVIDED", "peRatio_state": "VENDOR_PROVIDED",
            "shares_outstanding_state": "VENDOR_PROVIDED",
        },
        "step_3_and_7_derivatives": {"surface_parameters": {"underlyingPrice": 102.0}},
    }
    return raw, _price_history(), _options(spot=102.0), {}


def _nan_aware_equal(a, b):
    """Deep equality that treats NaN == NaN and keeps numeric type fidelity."""
    import math
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_nan_aware_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_nan_aware_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a) and math.isnan(b):
            return True
    return a == b


def test_calculator_golden():
    raw, ph, opt, params = _build_inputs()
    result = MasterThesisCalculator(raw, ph, opt, params).calculate_metrics()

    if not os.path.exists(_GOLDEN_PATH):
        with open(_GOLDEN_PATH, "w") as fh:
            json.dump(result, fh, indent=2, sort_keys=True, default=str)
        pytest.skip(f"bootstrapped golden at {_GOLDEN_PATH}")

    with open(_GOLDEN_PATH) as fh:
        expected = json.load(fh)

    assert _nan_aware_equal(result, expected), (
        "calculator output diverged from golden"
    )
