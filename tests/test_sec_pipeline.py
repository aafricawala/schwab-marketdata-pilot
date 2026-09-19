"""
tests/test_sec_pipeline.py

Tests for sec_pipeline.py:

- Verifies pipeline executes end-to-end with mocked SECClient.
- Ensures missing tags are handled gracefully.
- Ensures structural errors are propagated as SECPipelineError.

Network calls are not performed; SECClient is monkeypatched.
"""

from typing import Any, Dict

import pandas as pd
import pytest

import sec_pipeline
from sec_pipeline import extract_metrics_for_ticker, SECPipelineError


class DummySECClient:
    """
    Dummy SECClient replacement for testing sec_pipeline.

    Provides:
    - get_company_facts_by_ticker(ticker) -> minimal CompanyFacts-like dict.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Identity args are ignored in tests
        pass

    def get_company_facts_by_ticker(self, ticker: str) -> Dict[str, Any]:
        # Minimal, structurally valid CompanyFacts-like payload
        return {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"end": "2023-12-31", "val": 100.0},
                                {"end": "2022-12-31", "val": 90.0},
                            ]
                        }
                    },
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                {"end": "2023-12-31", "val": 50.0},
                            ]
                        }
                    },
                },
                "dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "units": {
                            "shares": [
                                {"end": "2023-12-31", "val": 1_000_000},
                            ]
                        }
                    }
                },
            }
        }


def test_pipeline_runs_with_dummy_client(monkeypatch):
    """
    Ensure extract_metrics_for_ticker runs end-to-end with a dummy SECClient
    and returns the expected nested dict structure.
    """
    # Monkeypatch SECClient in sec_pipeline to use DummySECClient
    monkeypatch.setattr(sec_pipeline, "SECClient", DummySECClient)

    out = extract_metrics_for_ticker(
        ticker="MSFT",
        name="TestName",
        email="test@example.com",
        organization="TestOrg",
    )

    # Top-level keys should match ALL_METRIC_GROUPS
    assert isinstance(out, dict)
    assert "income_statement" in out
    assert "balance_sheet" in out
    assert "cash_flow" in out
    assert "etf" in out

    # Income statement should contain at least Revenues and NetIncomeLoss
    income = out["income_statement"]
    assert "Revenues" in income
    assert "NetIncomeLoss" in income

    # DataFrames should be well-formed
    revenues_df = income["Revenues"]
    assert isinstance(revenues_df, pd.DataFrame)
    assert "val" in revenues_df.columns
    assert len(revenues_df) == 2


def test_pipeline_handles_missing_tags_gracefully(monkeypatch):
    """
    Ensure missing tags do not cause failures and are simply omitted.
    """

    class DummySECClientMissing:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_company_facts_by_ticker(self, ticker: str) -> Dict[str, Any]:
            # Only Revenues present; other tags missing
            return {
                "facts": {
                    "us-gaap": {
                        "Revenues": {
                            "units": {
                                "USD": [
                                    {"end": "2023-12-31", "val": 100.0},
                                ]
                            }
                        }
                    }
                }
            }

    monkeypatch.setattr(sec_pipeline, "SECClient", DummySECClientMissing)

    out = extract_metrics_for_ticker(
        ticker="AAPL",
        name="TestName",
        email="test@example.com",
        organization="TestOrg",
    )

    income = out["income_statement"]
    # Revenues present, other metrics may be missing
    assert "Revenues" in income
    # NetIncomeLoss may be absent but should not cause errors
    assert "NetIncomeLoss" not in income or isinstance(income.get("NetIncomeLoss"), pd.DataFrame)


def test_pipeline_propagates_structure_errors(monkeypatch):
    """
    Ensure structural issues in CompanyFacts are propagated as SECPipelineError.
    """

    class DummySECClientBadStructure:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_company_facts_by_ticker(self, ticker: str) -> Dict[str, Any]:
            # Malformed 'facts' structure (not a dict)
            return {
                "facts": ["not", "a", "dict"],
            }

    monkeypatch.setattr(sec_pipeline, "SECClient", DummySECClientBadStructure)

    with pytest.raises(SECPipelineError):
        extract_metrics_for_ticker(
            ticker="MSFT",
            name="TestName",
            email="test@example.com",
            organization="TestOrg",
        )
