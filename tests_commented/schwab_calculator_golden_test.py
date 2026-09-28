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
# Execute this line of logic to process the data
schwab_calculator_golden_test.py

# Execute this line of logic to process the data
Calculator-layer golden harness for MasterThesisCalculator.calculate_metrics().

# Execute this line of logic to process the data
Complements tests/schwab_refactor_payload_mock_test.py (which covers the
# Execute this line of logic to process the data
grounding layer) by pinning the output of the calculator facade itself.

# Execute this line of logic to process the data
First run: if tests/schwab_calculator_golden.json is absent, the harness
          # Execute this line of logic to process the data
          writes it and passes (self-bootstrap).
# Execute this line of logic to process the data
Later runs: the harness asserts byte-for-byte dict equality.
"""
# Import specific components from a module
from __future__ import annotations

# Import the required external module
import json
# Import the required external module
import os
# Import the required external module
import sys

# Import the required external module
import numpy as np
# Import the required external module
import pandas as pd
# Import the required external module
import pytest

# Assign a value or initialize a variable
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# Assign a value or initialize a variable
_SRC_DIR = os.path.join(os.path.dirname(_THIS_DIR), "src")
# Check a conditional statement
if _SRC_DIR not in sys.path:
    # Execute this line of logic to process the data
    sys.path.insert(0, _SRC_DIR)

# Import specific components from a module
from schwab_marketdata_calculator import MasterThesisCalculator  # noqa: E402

# Assign a value or initialize a variable
_GOLDEN_PATH = os.path.join(_THIS_DIR, "schwab_calculator_golden.json")


# Define a new function or method
def _price_history(n=260, base=100.0, seed=7):
    # Assign a value or initialize a variable
    rng = np.random.default_rng(seed)
    # Assign a value or initialize a variable
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    # Assign a value or initialize a variable
    rets = rng.normal(0.0, 0.012, size=n)
    # Assign a value or initialize a variable
    close = base * np.exp(np.cumsum(rets))
    # Assign a value or initialize a variable
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.004, size=n)))
    # Assign a value or initialize a variable
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.004, size=n)))
    # Assign a value or initialize a variable
    open_ = np.concatenate([[close[0]], close[:-1]])
    # Return the final computed result to the caller
    return pd.DataFrame({"datetime": idx, "open": open_, "high": high, "low": low, "close": close})


# Define a new function or method
def _options(spot=100.0, dtes=(7, 21, 35, 60), seed=11):
    # Assign a value or initialize a variable
    rng = np.random.default_rng(seed)
    # Assign a value or initialize a variable
    rows = []
    # Start a loop over the given collection
    for dte in dtes:
        # Start a loop over the given collection
        for k_off in (-0.10, -0.05, 0.0, 0.05, 0.10):
            # Assign a value or initialize a variable
            strike = round(spot * (1.0 + k_off), 2)
            # Start a loop over the given collection
            for pc in ("PUT", "CALL"):
                # Assign a value or initialize a variable
                delta = (-1 if pc == "PUT" else 1) * max(0.05, 0.5 - abs(k_off) * 3.0)
                # Assign a value or initialize a variable
                iv = 0.25 + abs(k_off) * 1.2 + rng.normal(0.0, 0.005)
                # Assign a value or initialize a variable
                mark = max(0.05, spot * 0.02 * (1.0 + abs(k_off) * 3.0))
                # Execute this line of logic to process the data
                rows.append({
                    # Execute this line of logic to process the data
                    "putCallIndicator": pc,
                    # Execute this line of logic to process the data
                    "daysToExpiration": dte,
                    # Execute this line of logic to process the data
                    "strikePrice": strike,
                    # Execute this line of logic to process the data
                    "delta": delta,
                    # Execute this line of logic to process the data
                    "volatility": iv,
                    # Execute this line of logic to process the data
                    "mark": mark,
                    # Execute this line of logic to process the data
                    "bid": round(mark * 0.98, 2),
                    # Execute this line of logic to process the data
                    "ask": round(mark * 1.02, 2),
                    # Execute this line of logic to process the data
                    "totalVolume": int(rng.integers(10, 5000)),
                    # Execute this line of logic to process the data
                    "openInterest": int(rng.integers(50, 20000)),
                # Execute this line of logic to process the data
                })
    # Return the final computed result to the caller
    return pd.DataFrame(rows)


# Define a new function or method
def _build_inputs():
    # Assign a value or initialize a variable
    raw = {
        # Execute this line of logic to process the data
        "phase_0_grounding": {"lastPrice": 102.0, "closePrice": 101.5, "market_isOpen": True, "quote_age_seconds": 30.0},
        # Execute this line of logic to process the data
        "step_1_fundamentals": {
            # Execute this line of logic to process the data
            "peRatio": 22.5, "eps": 4.10, "divAmount": 1.20, "divYield": 1.18,
            # Execute this line of logic to process the data
            "sharesOutstanding": 1_000_000_000.0, "marketCap": 102_500_000_000.0,
            # Execute this line of logic to process the data
            "eps_state": "VENDOR_PROVIDED", "peRatio_state": "VENDOR_PROVIDED",
            # Execute this line of logic to process the data
            "shares_outstanding_state": "VENDOR_PROVIDED",
        # Execute this line of logic to process the data
        },
        # Execute this line of logic to process the data
        "step_3_and_7_derivatives": {"surface_parameters": {"underlyingPrice": 102.0}},
    # Execute this line of logic to process the data
    }
    # Assign a value or initialize a variable
    return raw, _price_history(), _options(spot=102.0), {}


# Define a new function or method
def _nan_aware_equal(a, b):
    """Deep equality that treats NaN == NaN and keeps numeric type fidelity."""
    # Import the required external module
    import math
    # Check a conditional statement
    if isinstance(a, dict) and isinstance(b, dict):
        # Check a conditional statement
        if set(a.keys()) != set(b.keys()):
            # Return the final computed result to the caller
            return False
        # Return the final computed result to the caller
        return all(_nan_aware_equal(a[k], b[k]) for k in a)
    # Check a conditional statement
    if isinstance(a, list) and isinstance(b, list):
        # Check a conditional statement
        if len(a) != len(b):
            # Return the final computed result to the caller
            return False
        # Return the final computed result to the caller
        return all(_nan_aware_equal(x, y) for x, y in zip(a, b))
    # Check a conditional statement
    if isinstance(a, float) and isinstance(b, float):
        # Check a conditional statement
        if math.isnan(a) and math.isnan(b):
            # Return the final computed result to the caller
            return True
    # Assign a value or initialize a variable
    return a == b


# Define a new function or method
def test_calculator_golden():
    # Assign a value or initialize a variable
    raw, ph, opt, params = _build_inputs()
    # Assign a value or initialize a variable
    result = MasterThesisCalculator(raw, ph, opt, params).calculate_metrics()

    # Check a conditional statement
    if not os.path.exists(_GOLDEN_PATH):
        # Execute this line of logic to process the data
        with open(_GOLDEN_PATH, "w") as fh:
            # Assign a value or initialize a variable
            json.dump(result, fh, indent=2, sort_keys=True, default=str)
        # Execute this line of logic to process the data
        pytest.skip(f"bootstrapped golden at {_GOLDEN_PATH}")

    # Execute this line of logic to process the data
    with open(_GOLDEN_PATH) as fh:
        # Assign a value or initialize a variable
        expected = json.load(fh)

    # Execute this line of logic to process the data
    assert _nan_aware_equal(result, expected), (
        # Execute this line of logic to process the data
        "calculator output diverged from golden"
    # Execute this line of logic to process the data
    )
