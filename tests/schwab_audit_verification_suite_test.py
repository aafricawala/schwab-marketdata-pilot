"""
test_schwab_audit_verification_suite.py
========================================================================================
Comprehensive Verification Harness: Protocols v16.20 & v16.21 Audit Tests
========================================================================================
Validates:
  - NEG-SAFE-01: Proves missing broker reference keys route strictly to Step 0.5 UNKNOWN.
  - NEG-ADD-03 (PAY-18 / PAY-22): Proves bad contracts increment rejection counters
    and are discarded while exactly N valid contracts pass through.
  - PAY-24 / PAY-36: Proves resolve_optimal_expirations returns a 3-tenor bracket
    with max(DTE) > 30 and front DTE >= 4.
  - PAY-29 / PAY-39: Proves options wings with relative spread > 0.50 gate skew to UNKNOWN.
  - PAY-32 / PAY-40 / PAY-46: Proves SPCX 7-zero swarm sanitizes via the 5-state margin table.
  - PAY-28 / PAY-42 / PAY-48: Proves 252d macro volatility gates to INSUFFICIENT_HISTORY on 54 bars.
  - PAY-26 / PAY-43: Proves divergence > 20% and > $50B triggers INTEGRITY_FAILURE_REQUIRES_REVIEW
    and gates all MARKET_CAP_DEPENDENT_METRICS to UNRELIABLE.
"""

from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

from schwab_raw_marketdata import (
    extract_strict_underlying_data,
    extract_in_memory_option_chains,
    resolve_optimal_expirations,
)
from schwab_marketdata_calculator import MasterThesisCalculator

EASTERN = ZoneInfo("America/New_York")


class MockSchwabClientMissingRef:
    """Upstream broker feed missing all short reference keys (NEG-SAFE-01)."""
    def get_quote(self, symbol: str, fields: str):
        return {
            symbol: {
                "quote": {"lastPrice": 100.0, "closePrice": 100.0, "totalVolume": 5000000.0},
                "fundamental": {"peRatio": 20.0, "sharesOutstanding": 1000000.0},
                "reference": {},
            }
        }


class MockSchwabClientDirtyOptions:
    """Option chain containing invalid and valid contracts (NEG-ADD-03)."""
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

    assert telemetry["rejected_zero_strike_count"] == 1
    assert telemetry["rejected_expired_contract_count"] == 1
    assert telemetry["rejected_negative_mark_count"] == 1
    assert len(records) == 10, f"Expected 10 valid records, got {len(records)}"

    emitted_strikes = [r["strikePrice"] for r in records]
    assert 0.0 not in emitted_strikes
    assert 105.0 not in emitted_strikes
    print("[PASS] NEG-ADD-03 / PAY-18 / PAY-22: Telemetry verified and strict pass-through invariance confirmed.")


def test_pay_24_and_pay_36_cmi_3tenor_bracketing():
    """Validates PAY-24, PAY-35, PAY-36, and PAY-47."""
    mock_expirations = [
        {"expirationDate": "2026-09-26", "daysToExpiration": 1},  # Skipped (< 4 DTE)
        {"expirationDate": "2026-10-02", "daysToExpiration": 7},  # Front
        {"expirationDate": "2026-10-23", "daysToExpiration": 28}, # Near Sub (<= 30)
        {"expirationDate": "2026-10-30", "daysToExpiration": 35}, # Near Sup (> 30)
        {"expirationDate": "2026-11-20", "daysToExpiration": 56},
    ]
    res = resolve_optimal_expirations(mock_expirations)

    assert len(res["target_expirations"]) == 3, f"Expected 3 target dates, got {len(res['target_expirations'])}"
    assert res["front_tenor_selection"]["selected_dte"] == 7
    assert res["front_tenor_selection"]["skipped_expirations_count"] == 1
    assert res["near_30_sub"]["daysToExpiration"] == 28
    assert res["near_30_sup"]["daysToExpiration"] == 35
    assert res["near_30_sup"]["daysToExpiration"] > 30
    print("[PASS] PAY-24 / PAY-36: 3-tenor bracketing engine successfully verified.")


def test_pay_29_and_pay_39_bp_skew_spread_filter():
    """Validates PAY-29, PAY-39, and PAY-45 (BP Skew illiquidity rejection)."""
    mock_payload = {
        "phase_0_grounding": {"lastPrice": 44.40, "closePrice": 44.42},
        "step_3_and_7_derivatives": {"surface_parameters": {"underlyingPrice": 44.40}},
    }
    # Create options chain where Put is liquid but Call spread is 1.84 (> 0.50)
    options_data = [
        # OTM Put (Kp < 44.40, Delta ~ -0.25)
        {"putCallIndicator": "PUT", "daysToExpiration": 28, "strikePrice": 40.0, "delta": -0.25, "bid": 0.40, "ask": 0.45, "mark": 0.425, "volatility": 28.25},
        # OTM Call with wide illiquid spread (Kc > 44.40, Delta ~ 0.25, bid=0.05, ask=1.20, mark=0.625 => rel_spread = 1.84)
        {"putCallIndicator": "CALL", "daysToExpiration": 28, "strikePrice": 50.0, "delta": 0.25, "bid": 0.05, "ask": 1.20, "mark": 0.625, "volatility": 64.80},
    ]
    calc = MasterThesisCalculator(mock_payload, None, pd.DataFrame(options_data))
    skew = calc._calc_30d_skew()

    assert skew["skew_30d_state"] == "UNKNOWN"
    assert skew["skew_30d_reason"] == "skew_wing_liquidity_insufficient_relative_spread_exceeds_tolerance"
    assert skew["rejected_wing"] == "CALL"
    assert skew["observed_wing_relative_spread"] == 1.84
    print("[PASS] PAY-29 / PAY-39 / PAY-45: Microstructure relative spread filter successfully gated anomalous skew.")


def test_pay_32_and_pay_46_spcx_zero_swarm_sanitization():
    """Validates PAY-32, PAY-40, PAY-41, PAY-46, PAY-51, PAY-52, and PAY-53."""
    class MockClientSPCX:
        def get_quote(self, symbol: str, fields: str):
            return {
                symbol: {
                    "quote": {"lastPrice": 200.0, "closePrice": 200.5, "totalVolume": 1000000.0},
                    "fundamental": {
                        "beta": 0.0,
                        "pegRatio": 0.0,
                        "pcfRatio": 0.0,
                        "returnOnEquity": 0.0,
                        "returnOnAssets": 0.0,
                        "revChangeYear": 0.0,
                        "netProfitMarginTTM": -35.66,
                        "operatingMarginTTM": -25.0,
                        "divYield": 0.0,
                        "marketCap": 2061032963756.0,
                    },
                    "reference": {"isShortable": True, "isHardToBorrow": False, "htbRate": 0.25},
                }
            }

    payload = extract_strict_underlying_data(MockClientSPCX(), "SPCX", EASTERN)
    f = payload["step_1_fundamentals"]

    # Verify no bare zeros remain
    assert f["beta"] is None and f["beta_state"] == "VENDOR_UNAVAILABLE_OR_ZERO"
    assert f["pegRatio"] is None and f["pegRatio_state"] == "VENDOR_ZERO_NON_MEANINGFUL"
    assert f["pcfRatio"] is None and f["pcfRatio_state"] == "NON_POSITIVE_OR_UNAVAILABLE"
    assert f["returnOnEquity"] is None and f["returnOnEquity_state"] == "VENDOR_UNAVAILABLE_NEGATIVE_EARNINGS"
    assert f["returnOnAssets"] is None and f["returnOnAssets_state"] == "VENDOR_UNAVAILABLE_NEGATIVE_EARNINGS"
    assert f["revChangeYear"] is None and f["revChangeYear_state"] == "VENDOR_ZERO_UNVERIFIED"
    print("[PASS] PAY-32 / PAY-46: SPCX zero swarm sanitized through 5-state margin table.")


def test_pay_28_and_pay_48_realized_volatility_insufficient_history():
    """Validates PAY-28, PAY-42, and PAY-48."""
    # Synthesize 54 bars of price history
    np.random.seed(42)
    dates = pd.date_range("2026-06-01", periods=54, freq="B")
    close = 100.0 * np.exp(np.cumsum(np.random.normal(0, 0.02, 54)))
    high = close * 1.01
    low = close * 0.99
    open_p = close * 1.00
    df = pd.DataFrame({"open": open_p, "high": high, "low": low, "close": close, "volume": 1000000})

    calc = MasterThesisCalculator({}, df, None)
    rv = calc._calc_step_5()["realized_volatility"]

    macro_win = rv["252d_macro"]
    assert macro_win["state"] == "INSUFFICIENT_HISTORY"
    assert macro_win["actual_sample_bars"] == 54
    assert macro_win["return_observations"] == 53
    assert macro_win["computed_realized_vol"] is not None
    assert macro_win["reason"] == "sample_bars_below_minimum_macro_threshold_180"
    print("[PASS] PAY-28 / PAY-48: Macro RV correctly gated to INSUFFICIENT_HISTORY.")


def test_pay_26_and_pay_43_integrity_failure_requires_review():
    """Validates PAY-26, PAY-43, PAY-49, and PAY-55."""
    mock_payload = {
        "phase_0_grounding": {"lastPrice": 100.0, "closePrice": 100.0},
        "step_1_fundamentals": {
            "sharesOutstanding": 12000000000.0,  # Derived = 100 * 12B = $1.20T
            "marketCap": 2061032963756.0,         # Reported = $2.06T (Divergence = 41.77% / $861B)
            "pbRatio": 30.5,
            "totalDebtToEquity": 50.0,
            "shares_outstanding_state": "CONFIRMED",
        },
    }
    calc = MasterThesisCalculator(mock_payload, None, None)
    s1 = calc._calc_step_1()

    # Divergence Classification
    assert s1["market_cap_divergence"]["market_cap_divergence_state"] == "INTEGRITY_FAILURE_REQUIRES_REVIEW"
    assert s1["market_cap_divergence_state"] == "INTEGRITY_FAILURE_REQUIRES_REVIEW"

    # Universal Metric Registry Gating (PAY-49)
    assert s1["imputed_book_value_of_equity"]["state"] == "UNRELIABLE"
    assert s1["imputed_total_debt"]["state"] == "UNRELIABLE"
    assert s1["imputed_book_value_of_equity"]["reason"] == "upstream_market_cap_divergence_integrity_failure"
    print("[PASS] PAY-26 / PAY-43 / PAY-49: Universal integrity failure gate verified.")


if __name__ == "__main__":
    test_neg_safe_01_missing_reference_keys()
    test_neg_add_03_options_rejection_and_invariance()
    test_pay_24_and_pay_36_cmi_3tenor_bracketing()
    test_pay_29_and_pay_39_bp_skew_spread_filter()
    test_pay_32_and_pay_46_spcx_zero_swarm_sanitization()
    test_pay_28_and_pay_48_realized_volatility_insufficient_history()
    test_pay_26_and_pay_43_integrity_failure_requires_review()
    print("\n=================================================================================")
    print("ALL 7 AUDIT & VERIFICATION FIXTURES PASSED UNCONDITIONALLY (ZERO REGRESSIONS).")
    print("=================================================================================")