"""
schwab_refactor_payload_mock_test.py

Stub-driven payload-stability test for the schwab_* refactor.
No unittest.mock, no network. Uses a hand-rolled FakeClient.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pytest

import schwab_raw_marketdata as facade


GOLDEN_PATH = Path(__file__).with_name("schwab_refactor_golden.json")
REGENERATE = os.environ.get("REGENERATE") == "1"
TZ_ET = ZoneInfo("America/New_York")


class FakeResponse:
    def __init__(self, status_code: int, payload: Optional[dict] = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(
        self,
        quotes: Optional[Dict[str, Dict[str, Any]]] = None,
        market_hours: Optional[Dict[str, Any]] = None,
        price_history: Optional[Dict[str, Any]] = None,
        expirations: Optional[Dict[str, Any]] = None,
        option_chains: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self._quotes = quotes or {}
        self._market_hours = market_hours or {"equity": {"EQ": {"isOpen": True}}}
        self._price_history = price_history or {"candles": []}
        self._expirations = expirations or {"expirationList": []}
        self._option_chains = option_chains or {}

    def get_market_hours(self, product: str) -> Any:
        return FakeResponse(200, self._market_hours)

    def get_quote(self, symbol: str) -> Any:
        inner = self._quotes.get(symbol)
        if inner is None:
            return FakeResponse(200, {})
        return FakeResponse(200, {symbol: inner})

    def get_price_history(self, symbol: str, **kwargs: Any) -> Any:
        return FakeResponse(200, self._price_history)

    def get_option_expirations(self, symbol: str) -> Any:
        return FakeResponse(200, self._expirations)

    def get_option_chain(self, symbol: str, **kwargs: Any) -> Any:
        if "from_date" in kwargs and "to_date" in kwargs:
            return FakeResponse(200, self._option_chains.get("targeted", {}))
        return FakeResponse(200, self._option_chains.get("default", {}))


def _now_ms() -> int:
    return 1735689600000  # frozen: 2025-01-01T00:00:00Z


FIXTURES: List[Dict[str, Any]] = [
    {
        "name": "equity_us_live",
        "client": {
            "quotes": {
                "AAPL": {
                    "reference": {
                        "assetSubType": "COMMON_STOCK",
                        "assetMainType": "EQUITY",
                        "description": "APPLE INC",
                        "country": "US",
                    },
                    "quote": {
                        "lastPrice": 187.45,
                        "closePrice": 186.10,
                        "quoteTime": _now_ms() - 5_000,
                        "bidPrice": 187.40,
                        "askPrice": 187.50,
                        "bidSize": 300.0,
                        "askSize": 200.0,
                        "totalVolume": 12_345_678.0,
                    },
                    "fundamental": {
                        "peRatio": 29.8,
                        "eps": 6.29,
                        "divYield": 0.0055,
                        "divAmount": 1.03,
                        "divFreq": 4.0,
                        "beta": 1.28,
                        "sharesOutstanding": 15_500_000_000.0,
                        "netProfitMarginTTM": 0.25,
                        "operatingMarginTTM": 0.30,
                        "grossMarginTTM": 0.44,
                        "vol10DayAvg": 55_000_000.0,
                        "vol1YearAvg": 60_000_000.0,
                    },
                }
            }
        },
        "call": {"fn": "extract_strict_underlying_data", "args": ("AAPL",)},
    },
    {
        "name": "warrant",
        "client": {
            "quotes": {
                "ABCD.WS": {
                    "reference": {
                        "assetSubType": "WARRANT",
                        "assetMainType": "WARRANT",
                        "description": "ABCD ACQUISITION WARRANT",
                    },
                    "quote": {
                        "lastPrice": 0.75,
                        "closePrice": 0.74,
                        "quoteTime": _now_ms() - 5_000,
                        "bidPrice": 0.70,
                        "askPrice": 0.80,
                        "bidSize": 100.0,
                        "askSize": 100.0,
                        "totalVolume": 5_000.0,
                    },
                    "fundamental": {"sharesOutstanding": None},
                }
            }
        },
        "call": {"fn": "extract_strict_underlying_data", "args": ("ABCD.WS",)},
    },
    {
        "name": "etf",
        "client": {
            "quotes": {
                "SPY": {
                    "reference": {
                        "assetSubType": "ETF",
                        "assetMainType": "ETF",
                        "description": "SPDR S&P 500 ETF TRUST",
                    },
                    "quote": {
                        "lastPrice": 512.30,
                        "closePrice": 511.00,
                        "quoteTime": _now_ms() - 5_000,
                        "bidPrice": 512.25,
                        "askPrice": 512.35,
                        "bidSize": 1000.0,
                        "askSize": 800.0,
                        "totalVolume": 80_000_000.0,
                    },
                    "fundamental": {
                        "divYield": 0.013,
                        "divAmount": 6.60,
                        "vol10DayAvg": 75_000_000.0,
                    },
                }
            }
        },
        "call": {"fn": "extract_strict_underlying_data", "args": ("SPY",)},
    },
    {
        "name": "adr_foreign",
        "client": {
            "quotes": {
                "TSM": {
                    "reference": {
                        "assetSubType": "ADR",
                        "assetMainType": "EQUITY",
                        "description": "TAIWAN SEMICONDUCTOR ADR",
                        "country": "TW",
                    },
                    "quote": {
                        "lastPrice": 145.20,
                        "closePrice": 144.00,
                        "quoteTime": _now_ms() - 5_000,
                        "bidPrice": 145.15,
                        "askPrice": 145.25,
                        "bidSize": 400.0,
                        "askSize": 400.0,
                        "totalVolume": 8_000_000.0,
                    },
                    "fundamental": {
                        "peRatio": 22.1,
                        "eps": None,
                        "sharesOutstanding": 5_000_000_000.0,
                    },
                }
            }
        },
        "call": {"fn": "extract_strict_underlying_data", "args": ("TSM",)},
    },
    {
        "name": "halted_unquoted",
        "client": {
            "quotes": {
                "HALT": {
                    "reference": {
                        "assetSubType": "COMMON_STOCK",
                        "assetMainType": "EQUITY",
                        "description": "HALTED CO",
                    },
                    "quote": {
                        "lastPrice": 0.0,
                        "closePrice": 0.0,
                        "quoteTime": 0,
                    },
                    "fundamental": {},
                }
            }
        },
        "call": {"fn": "extract_strict_underlying_data", "args": ("HALT",)},
    },
    {
        "name": "empty_envelope",
        "client": {"quotes": {}},
        "call": {"fn": "extract_strict_underlying_data", "args": ("ZZZZ",)},
    },
    {
        "name": "option_expirations",
        "client": {
            "expirations": {
                "expirationList": [
                    {"expirationDate": "2025-01-17", "daysToExpiration": 5},
                    {"expirationDate": "2025-02-21", "daysToExpiration": 40},
                    {"expirationDate": "2025-06-20", "daysToExpiration": 160},
                    {"expirationDate": "2025-01-10", "daysToExpiration": -2},
                ]
            }
        },
        "call": {"fn": "extract_in_memory_option_expirations", "args": ("AAPL",)},
    },
]


def _build_client(spec: Dict[str, Any]) -> FakeClient:
    return FakeClient(**spec)


def _invoke(spec: Dict[str, Any], client: FakeClient) -> Any:
    fn_name = spec["call"]["fn"]
    args = spec["call"].get("args", ())
    kwargs = spec["call"].get("kwargs", {})
    fn = getattr(facade, fn_name)
    if fn_name == "extract_strict_underlying_data":
        return fn(client, *args, TZ_ET, **kwargs)
    return fn(client, *args, **kwargs)


_TIME_DERIVED_KEYS = {"quote_age_seconds", "quoteTime_ISO_ET"}


def _scrub_time_fields(obj):
    """Recursively drop time-derived fields that change between runs."""
    if isinstance(obj, dict):
        return {k: _scrub_time_fields(v) for k, v in obj.items() if k not in _TIME_DERIVED_KEYS}
    if isinstance(obj, list):
        return [_scrub_time_fields(x) for x in obj]
    return obj


def _load_goldens() -> Dict[str, Any]:
    if not GOLDEN_PATH.exists():
        return {}
    return json.loads(GOLDEN_PATH.read_text())


def _save_goldens(goldens: Dict[str, Any]) -> None:
    GOLDEN_PATH.write_text(json.dumps(goldens, indent=2, sort_keys=True, default=str))


@pytest.mark.parametrize("spec", FIXTURES, ids=[f["name"] for f in FIXTURES])
def test_payload_matches_golden(spec: Dict[str, Any]) -> None:
    client = _build_client(spec["client"])
    actual = _invoke(spec, client)
    goldens = _load_goldens()
    if REGENERATE or spec["name"] not in goldens:
        goldens[spec["name"]] = actual
        _save_goldens(goldens)
        pytest.skip(f"Golden for '{spec['name']}' written; re-run to assert.")
    expected = goldens[spec["name"]]
    assert _scrub_time_fields(actual) == _scrub_time_fields(expected), (
        f"Payload drift in fixture '{spec['name']}'. "
        f"If intentional, regenerate with REGENERATE=1."
    )


def test_private_aliases_resolve() -> None:
    assert callable(getattr(facade, "_parse_client_response"))
    assert callable(getattr(facade, "_build_halted_grounding"))


def test_facade_public_surface_complete() -> None:
    expected = {
        "retry_vendor_call",
        "parse_client_response",
        "extract_market_open_status",
        "build_halted_grounding",
        "extract_strict_underlying_data",
        "extract_in_memory_price_history",
        "extract_in_memory_option_expirations",
        "resolve_optimal_expirations",
        "extract_in_memory_option_chains",
        "_parse_client_response",
        "_build_halted_grounding",
    }
    missing = {n for n in expected if not hasattr(facade, n)}
    assert not missing, f"Facade missing re-exports: {sorted(missing)}"
