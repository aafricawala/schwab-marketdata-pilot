# Filename.py: schwab_refactor_payload_mock_test.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

# Filename.py: schwab_refactor_payload_mock_test.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

"""
# Execute this line of logic to process the data
schwab_refactor_payload_mock_test.py

# Execute this line of logic to process the data
Stub-driven payload-stability test for the schwab_* refactor.
# Execute this line of logic to process the data
No unittest.mock, no network. Uses a hand-rolled FakeClient.
"""
# Import specific components from a module
from __future__ import annotations

# Import the required external module
import json
# Import the required external module
import os
# Import specific components from a module
from datetime import datetime, timezone
# Import specific components from a module
from pathlib import Path
# Import specific components from a module
from typing import Any, Dict, List, Optional
# Import specific components from a module
from zoneinfo import ZoneInfo

# Import the required external module
import pytest

# Import the required external module
import schwab_raw_marketdata as facade


# Assign a value or initialize a variable
GOLDEN_PATH = Path(__file__).with_name("schwab_refactor_golden.json")
# Assign a value or initialize a variable
REGENERATE = os.environ.get("REGENERATE") == "1"
# Assign a value or initialize a variable
TZ_ET = ZoneInfo("America/New_York")


# Define a new data structure or class
class FakeResponse:
    # Define a new function or method
    def __init__(self, status_code: int, payload: Optional[dict] = None):
        # Assign a value or initialize a variable
        self.status_code = status_code
        # Assign a value or initialize a variable
        self._payload = payload or {}

    # Define a new function or method
    def json(self) -> dict:
        # Return the final computed result to the caller
        return self._payload


# Define a new data structure or class
class FakeClient:
    # Define a new function or method
    def __init__(
        # Execute this line of logic to process the data
        self,
        # Assign a value or initialize a variable
        quotes: Optional[Dict[str, Dict[str, Any]]] = None,
        # Assign a value or initialize a variable
        market_hours: Optional[Dict[str, Any]] = None,
        # Assign a value or initialize a variable
        price_history: Optional[Dict[str, Any]] = None,
        # Assign a value or initialize a variable
        expirations: Optional[Dict[str, Any]] = None,
        # Assign a value or initialize a variable
        option_chains: Optional[Dict[str, Dict[str, Any]]] = None,
    # Execute this line of logic to process the data
    ):
        # Assign a value or initialize a variable
        self._quotes = quotes or {}
        # Assign a value or initialize a variable
        self._market_hours = market_hours or {"equity": {"EQ": {"isOpen": True}}}
        # Assign a value or initialize a variable
        self._price_history = price_history or {"candles": []}
        # Assign a value or initialize a variable
        self._expirations = expirations or {"expirationList": []}
        # Assign a value or initialize a variable
        self._option_chains = option_chains or {}

    # Define a new function or method
    def get_market_hours(self, product: str) -> Any:
        # Return the final computed result to the caller
        return FakeResponse(200, self._market_hours)

    # Define a new function or method
    def get_quote(self, symbol: str) -> Any:
        # Assign a value or initialize a variable
        inner = self._quotes.get(symbol)
        # Check a conditional statement
        if inner is None:
            # Return the final computed result to the caller
            return FakeResponse(200, {})
        # Return the final computed result to the caller
        return FakeResponse(200, {symbol: inner})

    # Define a new function or method
    def get_price_history(self, symbol: str, **kwargs: Any) -> Any:
        # Return the final computed result to the caller
        return FakeResponse(200, self._price_history)

    # Define a new function or method
    def get_option_expirations(self, symbol: str) -> Any:
        # Return the final computed result to the caller
        return FakeResponse(200, self._expirations)

    # Define a new function or method
    def get_option_chain(self, symbol: str, **kwargs: Any) -> Any:
        # Check a conditional statement
        if "from_date" in kwargs and "to_date" in kwargs:
            # Return the final computed result to the caller
            return FakeResponse(200, self._option_chains.get("targeted", {}))
        # Return the final computed result to the caller
        return FakeResponse(200, self._option_chains.get("default", {}))


# Define a new function or method
def _now_ms() -> int:
    # Return the final computed result to the caller
    return 1735689600000  # frozen: 2025-01-01T00:00:00Z


# Assign a value or initialize a variable
FIXTURES: List[Dict[str, Any]] = [
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "name": "equity_us_live",
        # Execute this line of logic to process the data
        "client": {
            # Execute this line of logic to process the data
            "quotes": {
                # Execute this line of logic to process the data
                "AAPL": {
                    # Execute this line of logic to process the data
                    "reference": {
                        # Execute this line of logic to process the data
                        "assetSubType": "COMMON_STOCK",
                        # Execute this line of logic to process the data
                        "assetMainType": "EQUITY",
                        # Execute this line of logic to process the data
                        "description": "APPLE INC",
                        # Execute this line of logic to process the data
                        "country": "US",
                    # Execute this line of logic to process the data
                    },
                    # Execute this line of logic to process the data
                    "quote": {
                        # Execute this line of logic to process the data
                        "lastPrice": 187.45,
                        # Execute this line of logic to process the data
                        "closePrice": 186.10,
                        # Execute this line of logic to process the data
                        "quoteTime": _now_ms() - 5_000,
                        # Execute this line of logic to process the data
                        "bidPrice": 187.40,
                        # Execute this line of logic to process the data
                        "askPrice": 187.50,
                        # Execute this line of logic to process the data
                        "bidSize": 300.0,
                        # Execute this line of logic to process the data
                        "askSize": 200.0,
                        # Execute this line of logic to process the data
                        "totalVolume": 12_345_678.0,
                    # Execute this line of logic to process the data
                    },
                    # Execute this line of logic to process the data
                    "fundamental": {
                        # Execute this line of logic to process the data
                        "peRatio": 29.8,
                        # Execute this line of logic to process the data
                        "eps": 6.29,
                        # Execute this line of logic to process the data
                        "divYield": 0.0055,
                        # Execute this line of logic to process the data
                        "divAmount": 1.03,
                        # Execute this line of logic to process the data
                        "divFreq": 4.0,
                        # Execute this line of logic to process the data
                        "beta": 1.28,
                        # Execute this line of logic to process the data
                        "sharesOutstanding": 15_500_000_000.0,
                        # Execute this line of logic to process the data
                        "netProfitMarginTTM": 0.25,
                        # Execute this line of logic to process the data
                        "operatingMarginTTM": 0.30,
                        # Execute this line of logic to process the data
                        "grossMarginTTM": 0.44,
                        # Execute this line of logic to process the data
                        "vol10DayAvg": 55_000_000.0,
                        # Execute this line of logic to process the data
                        "vol1YearAvg": 60_000_000.0,
                    # Execute this line of logic to process the data
                    },
                # Execute this line of logic to process the data
                }
            # Execute this line of logic to process the data
            }
        # Execute this line of logic to process the data
        },
        # Execute this line of logic to process the data
        "call": {"fn": "extract_strict_underlying_data", "args": ("AAPL",)},
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "name": "warrant",
        # Execute this line of logic to process the data
        "client": {
            # Execute this line of logic to process the data
            "quotes": {
                # Execute this line of logic to process the data
                "ABCD.WS": {
                    # Execute this line of logic to process the data
                    "reference": {
                        # Execute this line of logic to process the data
                        "assetSubType": "WARRANT",
                        # Execute this line of logic to process the data
                        "assetMainType": "WARRANT",
                        # Execute this line of logic to process the data
                        "description": "ABCD ACQUISITION WARRANT",
                    # Execute this line of logic to process the data
                    },
                    # Execute this line of logic to process the data
                    "quote": {
                        # Execute this line of logic to process the data
                        "lastPrice": 0.75,
                        # Execute this line of logic to process the data
                        "closePrice": 0.74,
                        # Execute this line of logic to process the data
                        "quoteTime": _now_ms() - 5_000,
                        # Execute this line of logic to process the data
                        "bidPrice": 0.70,
                        # Execute this line of logic to process the data
                        "askPrice": 0.80,
                        # Execute this line of logic to process the data
                        "bidSize": 100.0,
                        # Execute this line of logic to process the data
                        "askSize": 100.0,
                        # Execute this line of logic to process the data
                        "totalVolume": 5_000.0,
                    # Execute this line of logic to process the data
                    },
                    # Execute this line of logic to process the data
                    "fundamental": {"sharesOutstanding": None},
                # Execute this line of logic to process the data
                }
            # Execute this line of logic to process the data
            }
        # Execute this line of logic to process the data
        },
        # Execute this line of logic to process the data
        "call": {"fn": "extract_strict_underlying_data", "args": ("ABCD.WS",)},
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "name": "etf",
        # Execute this line of logic to process the data
        "client": {
            # Execute this line of logic to process the data
            "quotes": {
                # Execute this line of logic to process the data
                "SPY": {
                    # Execute this line of logic to process the data
                    "reference": {
                        # Execute this line of logic to process the data
                        "assetSubType": "ETF",
                        # Execute this line of logic to process the data
                        "assetMainType": "ETF",
                        # Execute this line of logic to process the data
                        "description": "SPDR S&P 500 ETF TRUST",
                    # Execute this line of logic to process the data
                    },
                    # Execute this line of logic to process the data
                    "quote": {
                        # Execute this line of logic to process the data
                        "lastPrice": 512.30,
                        # Execute this line of logic to process the data
                        "closePrice": 511.00,
                        # Execute this line of logic to process the data
                        "quoteTime": _now_ms() - 5_000,
                        # Execute this line of logic to process the data
                        "bidPrice": 512.25,
                        # Execute this line of logic to process the data
                        "askPrice": 512.35,
                        # Execute this line of logic to process the data
                        "bidSize": 1000.0,
                        # Execute this line of logic to process the data
                        "askSize": 800.0,
                        # Execute this line of logic to process the data
                        "totalVolume": 80_000_000.0,
                    # Execute this line of logic to process the data
                    },
                    # Execute this line of logic to process the data
                    "fundamental": {
                        # Execute this line of logic to process the data
                        "divYield": 0.013,
                        # Execute this line of logic to process the data
                        "divAmount": 6.60,
                        # Execute this line of logic to process the data
                        "vol10DayAvg": 75_000_000.0,
                    # Execute this line of logic to process the data
                    },
                # Execute this line of logic to process the data
                }
            # Execute this line of logic to process the data
            }
        # Execute this line of logic to process the data
        },
        # Execute this line of logic to process the data
        "call": {"fn": "extract_strict_underlying_data", "args": ("SPY",)},
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "name": "adr_foreign",
        # Execute this line of logic to process the data
        "client": {
            # Execute this line of logic to process the data
            "quotes": {
                # Execute this line of logic to process the data
                "TSM": {
                    # Execute this line of logic to process the data
                    "reference": {
                        # Execute this line of logic to process the data
                        "assetSubType": "ADR",
                        # Execute this line of logic to process the data
                        "assetMainType": "EQUITY",
                        # Execute this line of logic to process the data
                        "description": "TAIWAN SEMICONDUCTOR ADR",
                        # Execute this line of logic to process the data
                        "country": "TW",
                    # Execute this line of logic to process the data
                    },
                    # Execute this line of logic to process the data
                    "quote": {
                        # Execute this line of logic to process the data
                        "lastPrice": 145.20,
                        # Execute this line of logic to process the data
                        "closePrice": 144.00,
                        # Execute this line of logic to process the data
                        "quoteTime": _now_ms() - 5_000,
                        # Execute this line of logic to process the data
                        "bidPrice": 145.15,
                        # Execute this line of logic to process the data
                        "askPrice": 145.25,
                        # Execute this line of logic to process the data
                        "bidSize": 400.0,
                        # Execute this line of logic to process the data
                        "askSize": 400.0,
                        # Execute this line of logic to process the data
                        "totalVolume": 8_000_000.0,
                    # Execute this line of logic to process the data
                    },
                    # Execute this line of logic to process the data
                    "fundamental": {
                        # Execute this line of logic to process the data
                        "peRatio": 22.1,
                        # Execute this line of logic to process the data
                        "eps": None,
                        # Execute this line of logic to process the data
                        "sharesOutstanding": 5_000_000_000.0,
                    # Execute this line of logic to process the data
                    },
                # Execute this line of logic to process the data
                }
            # Execute this line of logic to process the data
            }
        # Execute this line of logic to process the data
        },
        # Execute this line of logic to process the data
        "call": {"fn": "extract_strict_underlying_data", "args": ("TSM",)},
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "name": "halted_unquoted",
        # Execute this line of logic to process the data
        "client": {
            # Execute this line of logic to process the data
            "quotes": {
                # Execute this line of logic to process the data
                "HALT": {
                    # Execute this line of logic to process the data
                    "reference": {
                        # Execute this line of logic to process the data
                        "assetSubType": "COMMON_STOCK",
                        # Execute this line of logic to process the data
                        "assetMainType": "EQUITY",
                        # Execute this line of logic to process the data
                        "description": "HALTED CO",
                    # Execute this line of logic to process the data
                    },
                    # Execute this line of logic to process the data
                    "quote": {
                        # Execute this line of logic to process the data
                        "lastPrice": 0.0,
                        # Execute this line of logic to process the data
                        "closePrice": 0.0,
                        # Execute this line of logic to process the data
                        "quoteTime": 0,
                    # Execute this line of logic to process the data
                    },
                    # Execute this line of logic to process the data
                    "fundamental": {},
                # Execute this line of logic to process the data
                }
            # Execute this line of logic to process the data
            }
        # Execute this line of logic to process the data
        },
        # Execute this line of logic to process the data
        "call": {"fn": "extract_strict_underlying_data", "args": ("HALT",)},
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "name": "empty_envelope",
        # Execute this line of logic to process the data
        "client": {"quotes": {}},
        # Execute this line of logic to process the data
        "call": {"fn": "extract_strict_underlying_data", "args": ("ZZZZ",)},
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "name": "option_expirations",
        # Execute this line of logic to process the data
        "client": {
            # Execute this line of logic to process the data
            "expirations": {
                # Execute this line of logic to process the data
                "expirationList": [
                    # Execute this line of logic to process the data
                    {"expirationDate": "2025-01-17", "daysToExpiration": 5},
                    # Execute this line of logic to process the data
                    {"expirationDate": "2025-02-21", "daysToExpiration": 40},
                    # Execute this line of logic to process the data
                    {"expirationDate": "2025-06-20", "daysToExpiration": 160},
                    # Execute this line of logic to process the data
                    {"expirationDate": "2025-01-10", "daysToExpiration": -2},
                # Execute this line of logic to process the data
                ]
            # Execute this line of logic to process the data
            }
        # Execute this line of logic to process the data
        },
        # Execute this line of logic to process the data
        "call": {"fn": "extract_in_memory_option_expirations", "args": ("AAPL",)},
    # Execute this line of logic to process the data
    },
# Execute this line of logic to process the data
]


# Define a new function or method
def _build_client(spec: Dict[str, Any]) -> FakeClient:
    # Return the final computed result to the caller
    return FakeClient(**spec)


# Define a new function or method
def _invoke(spec: Dict[str, Any], client: FakeClient) -> Any:
    # Assign a value or initialize a variable
    fn_name = spec["call"]["fn"]
    # Assign a value or initialize a variable
    args = spec["call"].get("args", ())
    # Assign a value or initialize a variable
    kwargs = spec["call"].get("kwargs", {})
    # Assign a value or initialize a variable
    fn = getattr(facade, fn_name)
    # Check a conditional statement
    if fn_name == "extract_strict_underlying_data":
        # Return the final computed result to the caller
        return fn(client, *args, TZ_ET, **kwargs)
    # Return the final computed result to the caller
    return fn(client, *args, **kwargs)


# Assign a value or initialize a variable
_TIME_DERIVED_KEYS = {"quote_age_seconds", "quoteTime_ISO_ET"}


# Define a new function or method
def _scrub_time_fields(obj):
    """Recursively drop time-derived fields that change between runs."""
    # Check a conditional statement
    if isinstance(obj, dict):
        # Return the final computed result to the caller
        return {k: _scrub_time_fields(v) for k, v in obj.items() if k not in _TIME_DERIVED_KEYS}
    # Check a conditional statement
    if isinstance(obj, list):
        # Return the final computed result to the caller
        return [_scrub_time_fields(x) for x in obj]
    # Return the final computed result to the caller
    return obj


# Define a new function or method
def _load_goldens() -> Dict[str, Any]:
    # Check a conditional statement
    if not GOLDEN_PATH.exists():
        # Return the final computed result to the caller
        return {}
    # Return the final computed result to the caller
    return json.loads(GOLDEN_PATH.read_text())


# Define a new function or method
def _save_goldens(goldens: Dict[str, Any]) -> None:
    # Assign a value or initialize a variable
    GOLDEN_PATH.write_text(json.dumps(goldens, indent=2, sort_keys=True, default=str))


# Assign a value or initialize a variable
@pytest.mark.parametrize("spec", FIXTURES, ids=[f["name"] for f in FIXTURES])
# Define a new function or method
def test_payload_matches_golden(spec: Dict[str, Any]) -> None:
    # Assign a value or initialize a variable
    client = _build_client(spec["client"])
    # Assign a value or initialize a variable
    actual = _invoke(spec, client)
    # Assign a value or initialize a variable
    goldens = _load_goldens()
    # Check a conditional statement
    if REGENERATE or spec["name"] not in goldens:
        # Assign a value or initialize a variable
        goldens[spec["name"]] = actual
        # Execute this line of logic to process the data
        _save_goldens(goldens)
        # Execute this line of logic to process the data
        pytest.skip(f"Golden for '{spec['name']}' written; re-run to assert.")
    # Assign a value or initialize a variable
    expected = goldens[spec["name"]]
    # Assign a value or initialize a variable
    assert _scrub_time_fields(actual) == _scrub_time_fields(expected), (
        # Execute this line of logic to process the data
        f"Payload drift in fixture '{spec['name']}'. "
        # Assign a value or initialize a variable
        f"If intentional, regenerate with REGENERATE=1."
    # Execute this line of logic to process the data
    )


# Define a new function or method
def test_private_aliases_resolve() -> None:
    # Execute this line of logic to process the data
    assert callable(getattr(facade, "_parse_client_response"))
    # Execute this line of logic to process the data
    assert callable(getattr(facade, "_build_halted_grounding"))


# Define a new function or method
def test_facade_public_surface_complete() -> None:
    # Assign a value or initialize a variable
    expected = {
        # Execute this line of logic to process the data
        "retry_vendor_call",
        # Execute this line of logic to process the data
        "parse_client_response",
        # Execute this line of logic to process the data
        "extract_market_open_status",
        # Execute this line of logic to process the data
        "build_halted_grounding",
        # Execute this line of logic to process the data
        "extract_strict_underlying_data",
        # Execute this line of logic to process the data
        "extract_in_memory_price_history",
        # Execute this line of logic to process the data
        "extract_in_memory_option_expirations",
        # Execute this line of logic to process the data
        "resolve_optimal_expirations",
        # Execute this line of logic to process the data
        "extract_in_memory_option_chains",
        # Execute this line of logic to process the data
        "_parse_client_response",
        # Execute this line of logic to process the data
        "_build_halted_grounding",
    # Execute this line of logic to process the data
    }
    # Assign a value or initialize a variable
    missing = {n for n in expected if not hasattr(facade, n)}
    # Execute this line of logic to process the data
    assert not missing, f"Facade missing re-exports: {sorted(missing)}"
