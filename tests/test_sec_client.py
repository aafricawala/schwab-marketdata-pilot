# tests/test_sec_client.py
"""
Unit tests for sec_client.py.

These tests focus on:
- Identity / User-Agent construction
- Ticker → CIK conversion logic
- CIK → CIK10 formatting
- Robust handling of malformed data

Network calls are mocked to avoid hitting live SEC endpoints.
"""

import os
import json
from typing import Any, Dict

import pytest
from requests import Response

from sec_client import (
    SECClient,
    SECRateLimitedSession,
    SECConfigurationError,
    SECDataError,
    SECRequestError,
    SECRateLimitError,
    build_user_agent,
)


# ---------------------------------------------------------------------------
# Helpers for mocking
# ---------------------------------------------------------------------------


class DummyResponse(Response):
    """Simple Response subclass with convenient JSON injection."""

    def __init__(self, status_code: int = 200, json_data: Any = None) -> None:
        super().__init__()
        self.status_code = status_code
        self._json_data = json_data
        self._content = b""
        if json_data is not None:
            self._content = json.dumps(json_data).encode("utf-8")

    def json(self) -> Any:  # type: ignore[override]
        if self._json_data is None:
            raise ValueError("No JSON data set")
        return self._json_data


class DummySession:
    """Minimal session-like object for SECRateLimitedSession tests."""

    def __init__(self, response: Response) -> None:
        self.response = response
        self.headers: Dict[str, str] = {}

    def get(self, url: str, timeout: int = 10, **kwargs: Any) -> Response:
        return self.response


# ---------------------------------------------------------------------------
# build_user_agent tests
# ---------------------------------------------------------------------------


def test_build_user_agent_explicit_ok():
    ua = build_user_agent(name="Ankit", email="ankit@example.com", organization="MacroLab")
    assert "MacroLab" in ua
    assert "ankit@example.com" in ua


def test_build_user_agent_env_fallback(monkeypatch):
    monkeypatch.setenv("EDGAR_NAME", "EnvName")
    monkeypatch.setenv("EDGAR_EMAIL", "env@example.com")
    ua = build_user_agent()
    assert "EnvName" not in ua  # org not set, so name not used as prefix
    assert "env@example.com" in ua


def test_build_user_agent_missing_raises(monkeypatch):
    monkeypatch.delenv("EDGAR_NAME", raising=False)
    monkeypatch.delenv("EDGAR_EMAIL", raising=False)
    with pytest.raises(SECConfigurationError):
        build_user_agent()


# ---------------------------------------------------------------------------
# SECRateLimitedSession tests
# ---------------------------------------------------------------------------


def test_rate_limited_session_sets_user_agent(monkeypatch):
    monkeypatch.setenv("EDGAR_NAME", "TestName")
    monkeypatch.setenv("EDGAR_EMAIL", "test@example.com")

    dummy_resp = DummyResponse(status_code=200, json_data={"ok": True})
    session = DummySession(dummy_resp)

    client = SECRateLimitedSession(
        max_requests_per_second=5,
        session=session,
    )

    assert "User-Agent" in client.session.headers
    assert "test@example.com" in client.session.headers["User-Agent"]


def test_rate_limited_session_429_raises(monkeypatch):
    monkeypatch.setenv("EDGAR_NAME", "TestName")
    monkeypatch.setenv("EDGAR_EMAIL", "test@example.com")

    dummy_resp = DummyResponse(status_code=429, json_data={"error": "Too Many Requests"})
    session = DummySession(dummy_resp)

    client = SECRateLimitedSession(
        max_requests_per_second=5,
        session=session,
    )

    with pytest.raises(SECRateLimitError):
        client.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000000000.json")


def test_rate_limited_session_403_raises(monkeypatch):
    monkeypatch.setenv("EDGAR_NAME", "TestName")
    monkeypatch.setenv("EDGAR_EMAIL", "test@example.com")

    dummy_resp = DummyResponse(status_code=403, json_data={"error": "Forbidden"})
    session = DummySession(dummy_resp)

    client = SECRateLimitedSession(
        max_requests_per_second=5,
        session=session,
    )

    with pytest.raises(SECRequestError):
        client.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000000000.json")


# ---------------------------------------------------------------------------
# SECClient ticker / CIK tests
# ---------------------------------------------------------------------------


def test_cik_to_cik10_valid():
    assert SECClient.cik_to_cik10(320193) == "0000320193"


def test_cik_to_cik10_invalid():
    with pytest.raises(SECDataError):
        SECClient.cik_to_cik10(0)


def test_ticker_to_cik_found(monkeypatch):
    # Mock ticker table with a single entry
    mock_table = {
        "0": {"ticker": "MSFT", "title": "Microsoft Corp", "cik_str": 789019},
    }

    monkeypatch.setenv("EDGAR_NAME", "TestName")
    monkeypatch.setenv("EDGAR_EMAIL", "test@example.com")

    client = SECClient(max_requests_per_second=5)

    # Inject mock ticker table directly
    client._ticker_table = mock_table

    cik = client.ticker_to_cik("MSFT")
    assert cik == 789019


def test_ticker_to_cik_not_found(monkeypatch):
    mock_table = {
        "0": {"ticker": "AAPL", "title": "Apple Inc", "cik_str": 320193},
    }

    monkeypatch.setenv("EDGAR_NAME", "TestName")
    monkeypatch.setenv("EDGAR_EMAIL", "test@example.com")

    client = SECClient(max_requests_per_second=5)
    client._ticker_table = mock_table

    with pytest.raises(SECDataError):
        client.ticker_to_cik("MSFT")


def test_ticker_to_cik_empty(monkeypatch):
    monkeypatch.setenv("EDGAR_NAME", "TestName")
    monkeypatch.setenv("EDGAR_EMAIL", "test@example.com")

    client = SECClient(max_requests_per_second=5)
    client._ticker_table = {}

    with pytest.raises(SECDataError):
        client.ticker_to_cik("")


# ---------------------------------------------------------------------------
# SECClient CompanyFacts tests
# ---------------------------------------------------------------------------


def test_get_company_facts_by_cik_ok(monkeypatch):
    # Prepare dummy JSON payload
    dummy_json = {"facts": {"us-gaap": {}}}
    dummy_resp = DummyResponse(status_code=200, json_data=dummy_json)
    session = DummySession(dummy_resp)

    monkeypatch.setenv("EDGAR_NAME", "TestName")
    monkeypatch.setenv("EDGAR_EMAIL", "test@example.com")

    client = SECClient(
        max_requests_per_second=5,
        session=session,
    )

    data = client.get_company_facts_by_cik(320193)
    assert "facts" in data
    assert isinstance(data["facts"], dict)


def test_get_company_facts_by_cik_malformed_json(monkeypatch):
    # Response with invalid JSON (json() raises)
    resp = DummyResponse(status_code=200)
    session = DummySession(resp)

    monkeypatch.setenv("EDGAR_NAME", "TestName")
    monkeypatch.setenv("EDGAR_EMAIL", "test@example.com")

    client = SECClient(
        max_requests_per_second=5,
        session=session,
    )

    with pytest.raises(SECDataError):
        client.get_company_facts_by_cik(320193)


def test_get_company_facts_by_ticker_uses_ticker_to_cik(monkeypatch):
    dummy_json = {"facts": {"us-gaap": {}}}
    dummy_resp = DummyResponse(status_code=200, json_data=dummy_json)
    session = DummySession(dummy_resp)

    monkeypatch.setenv("EDGAR_NAME", "TestName")
    monkeypatch.setenv("EDGAR_EMAIL", "test@example.com")

    client = SECClient(
        max_requests_per_second=5,
        session=session,
    )

    # Inject a simple ticker table
    client._ticker_table = {
        "0": {"ticker": "MSFT", "title": "Microsoft Corp", "cik_str": 789019},
    }

    data = client.get_company_facts_by_ticker("MSFT")
    assert "facts" in data
