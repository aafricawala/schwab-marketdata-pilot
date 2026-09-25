"""
test_audit_verification_suite.py
========================================================================================
Synthetic Verification Fixtures for Production Protocol Compliance
========================================================================================
Validates negative failure paths, zero-dropping invariants, and telemetry tracking:
  - NEG-SAFE-01: Proves missing broker reference keys route strictly to Step 0.5 UNKNOWN.
  - NEG-ADD-03 (PAY-18 / PAY-22): Proves bad contracts increment telemetry counters
    and are discarded while exactly N valid contracts pass through.
"""

from zoneinfo import ZoneInfo
from schwab_raw_marketdata import extract_strict_underlying_data, extract_in_memory_option_chains

EASTERN = ZoneInfo("America/New_York")


class MockSchwabClientMissingRef:
    """Simulates an upstream broker feed with absent reference borrow keys."""
    def get_quote(self, symbol: str, fields: str):
        return {
            symbol: {
                "quote": {"lastPrice": 100.0, "closePrice": 100.0, "totalVolume": 5000000.0},
                "fundamental": {"peRatio": 20.0, "sharesOutstanding": 1000000.0},
                "reference": {},  # Missing isShortable, isHardToBorrow, htbRate
            }
        }


class MockSchwabClientDirtyOptions:
    """Simulates an options chain containing invalid and valid contracts."""
    def get_option_chain(self, **kwargs):
        return {
            "volatility": 29.0,
            "underlyingPrice": 100.0,
            "callExpDateMap": {
                "2026-10-16:21": {
                    "0.0": [{"strikePrice": 0.0, "daysToExpiration": 21, "mark": 1.0, "bid": 0.9, "ask": 1.1, "contractId": "BAD_ZERO_STRIKE"}],
                    "100.0": [{"strikePrice": 100.0, "daysToExpiration": 0, "mark": 1.0, "bid": 0.9, "ask": 1.1, "contractId": "BAD_EXPIRED"}],
                    "105.0": [{"strikePrice": 105.0, "daysToExpiration": 21, "mark": -0.5, "bid": 0.0, "ask": 1.1, "contractId": "BAD_NEG_MARK"}],
                    # 10 Strictly Valid Contracts
                    "110.0": [{"strikePrice": 110.0 + i, "daysToExpiration": 21, "mark": 2.0, "bid": 1.9, "ask": 2.1, "contractId": f"VALID_{i}"} for i in range(10)]
                }
            },
            "putExpDateMap": {}
        }


def test_neg_safe_01_missing_reference_keys():
    """Validates NEG-SAFE-01."""
    client = MockSchwabClientMissingRef()
    payload = extract_strict_underlying_data(client, "MOCK", EASTERN)
    short_status = payload["step_3_short_reference"]

    assert short_status["state"] == "UNKNOWN", f"Expected UNKNOWN state, got {short_status['state']}"
    assert short_status["isShortable"] is None
    assert short_status["isHardToBorrow"] is None
    assert short_status["htbRate"] is None
    print("[PASS] NEG-SAFE-01: Missing reference keys safely emitted Step 0.5 UNKNOWN envelope.")


def test_neg_add_03_options_rejection_and_invariance():
    """Validates NEG-ADD-03, PAY-18, and PAY-22."""
    client = MockSchwabClientDirtyOptions()
    raw_iv, spot, records, telemetry = extract_in_memory_option_chains(
        client, "MOCK", ["2026-10-16"], 14, "SINGLE", True
    )

    # 1. Assert rejection telemetry counters incremented by exactly 1
    assert telemetry["rejected_zero_strike_count"] == 1
    assert telemetry["rejected_expired_contract_count"] == 1
    assert telemetry["rejected_negative_mark_count"] == 1

    # 2. PAY-18: Assert exactly N=10 valid contracts passed through
    assert len(records) == 10, f"Expected 10 valid records, got {len(records)}"

    # 3. PAY-22: Assert none of the invalid contract IDs leaked into the records
    emitted_strikes = [r["strikePrice"] for r in records]
    assert 0.0 not in emitted_strikes
    assert 105.0 not in emitted_strikes
    print("[PASS] NEG-ADD-03 / PAY-18 / PAY-22: Telemetry verified and strict pass-through invariance confirmed.")


if __name__ == "__main__":
    test_neg_safe_01_missing_reference_keys()
    test_neg_add_03_options_rejection_and_invariance()
    print("\nAll synthetic regression fixtures PASSED successfully.")