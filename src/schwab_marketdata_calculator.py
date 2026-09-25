"""
schwab_marketdata_calculator.py
========================================================================================
CHARLES SCHWAB INSTITUTIONAL QUANTITATIVE CALCULATOR & RISK ENGINE (v16.21)
========================================================================================
Implements:
  - PAY-01 / PAY-19: Re-anchored session gap with quote cash-close provenance.
  - PAY-02 / PAY-12: ATM Constant Maturity Implied Volatility (CMI) via linear variance
    interpolation; isolates vendor_raw_chain_volatility_metadata.
  - PAY-03 / PAY-11 / PAY-16 / PAY-21 / PAY-26 / PAY-43: Tier 4 market cap divergence
    classification (INTEGRITY_FAILURE_REQUIRES_REVIEW) and universal registry gating.
  - PAY-05 / PAY-15 / PAY-20: OTM moneyness gating, primary 25D symmetric skew, and
    bounded fallback with strike-symmetry regularization.
  - PAY-07 / PAY-17: 0.85x straddle tagged PRACTITIONER_FAT_TAIL_ADJUSTED_CONVENTION.
  - PAY-09: Capital impairment risk flag when payout ratio > 100%.
  - PAY-28 / PAY-42 / PAY-48: 3-tier Realized Volatility sample-window governance:
    FULL_HISTORY (>=240), PARTIAL_HISTORY (180-239), and INSUFFICIENT_HISTORY (<180).
  - PAY-29 / PAY-39 / PAY-45: Microstructure relative-spread gate on skew wings
    (MAX_SKEW_RELATIVE_SPREAD = 0.50) with diagnostic telemetry.
  - PAY-34 / PAY-44 / PAY-50 / PAY-56: Canonical nested market_cap_divergence block
    with schema version 16.21 and backwards-compatible flat key emission.
  - PAY-49 / PAY-55: Structural registry (MARKET_CAP_DEPENDENT_METRICS) loop.
========================================================================================
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("schwab_marketdata_calculator")
logger.addHandler(logging.NullHandler())

# ------------------------------------------------------------------------------
# PROTOCOL CONSTANTS & METRIC REGISTRIES (PAY-49, PAY-54)
# ------------------------------------------------------------------------------
DATA_SCHEMA_VERSION = "16.21"
PROTOCOL_VERSION = "v16.21"

REASON_SKEW_SPREAD_TOLERANCE_EXCEEDED = "skew_wing_liquidity_insufficient_relative_spread_exceeds_tolerance"
REASON_MARKET_CAP_INTEGRITY_FAILURE = "upstream_market_cap_divergence_integrity_failure"

# Structural Registry for Universal Market Cap Gating (PAY-49, PAY-55)
MARKET_CAP_DEPENDENT_METRICS: Set[str] = {
    "imputed_book_value_of_equity",
    "imputed_total_debt",
    "enterprise_value_proxy",
    "imputed_dividend_payout_ratio_pct",
    "free_cash_flow_yield_pct",
}


def safe_div(num: Any, den: Any) -> Optional[float]:
    """Production division preventing zero-division, NaNs, and infinities."""
    try:
        if num is None or den is None or pd.isna(num) or pd.isna(den):
            return None
        n, d = float(num), float(den)
        if abs(d) < 1e-12:
            return None
        res = n / d
        return None if math.isnan(res) or math.isinf(res) else res
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def safe_float(val: Any) -> Optional[float]:
    """Safe float extraction."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


class MasterThesisCalculator:
    """
    Pure in-memory quantitative engine. Executes Step 0 Grounding, Step 1 Fundamentals,
    Step 3/7 Surface & Locate, Step 5 Technicals, and Step 8/9 Liquidity constraints.
    """

    def __init__(
        self,
        raw_payload: Dict[str, Any],
        price_history_df: Optional[pd.DataFrame] = None,
        options_df: Optional[pd.DataFrame] = None,
        calc_params: Optional[Dict[str, Any]] = None,
    ):
        self.raw = raw_payload or {}
        self.params = calc_params or {}

        # Parameterization
        self.trading_days_per_year = int(self.params.get("TRADING_DAYS_PER_YEAR", 252))
        self.min_delta_tolerance = float(self.params.get("MIN_DELTA_TOLERANCE", 0.20))
        self.max_delta_tolerance = float(self.params.get("MAX_DELTA_TOLERANCE", 0.30))
        self.max_skew_relative_spread = float(self.params.get("MAX_SKEW_RELATIVE_SPREAD", 0.50))
        self.debt_to_equity_unit = self.params.get("TOTAL_DEBT_TO_EQUITY_UNIT", None)

        # Contemporaneous Spot Resolution (DEF-10)
        derivatives_surface = (
            self.raw.get("step_3_and_7_derivatives", {}).get("surface_parameters", {})
        )
        chain_spot = safe_float(derivatives_surface.get("underlyingPrice"))
        grounding_spot = safe_float(
            self.raw.get("phase_0_grounding", {}).get("lastPrice")
        )

        if chain_spot is not None and chain_spot > 0:
            self.spot = chain_spot
            self.spot_provenance = {
                "source": "options_payload_underlyingPrice",
                "vintage_risk": "LOW",
                "contemporaneous": True,
            }
        elif grounding_spot is not None and grounding_spot > 0:
            self.spot = grounding_spot
            self.spot_provenance = {
                "source": "phase_0_grounding_lastPrice",
                "vintage_risk": "MEDIUM",
                "contemporaneous": False,
            }
        else:
            self.spot = None
            self.spot_provenance = {
                "source": "UNRESOLVED",
                "vintage_risk": "HIGH",
                "contemporaneous": False,
            }

        self.price_history_df = (
            price_history_df.copy()
            if price_history_df is not None and not price_history_df.empty
            else pd.DataFrame()
        )
        self.options_df = (
            options_df.copy()
            if options_df is not None and not options_df.empty
            else pd.DataFrame()
        )

    def calculate_metrics(self) -> Dict[str, Any]:
        """Calculates all phase-aligned quantitative metrics."""
        return {
            "step_0_grounding": self._calc_step_0(),
            "step_1_fundamentals_and_quality": self._calc_step_1(),
            "step_3_and_7_derivatives_and_surface": self._calc_step_3_and_7(),
            "step_5_technicals_and_flows": self._calc_step_5(),
        }

    # --------------------------------------------------------------------------
    # STEP 0: GROUNDING & CONTINUITY
    # --------------------------------------------------------------------------
    def _calc_step_0(self) -> Dict[str, Any]:
        """PAY-01 / PAY-19: Re-anchored session gap with quote cash-close provenance."""
        try:
            grounding = self.raw.get("phase_0_grounding", {})
            last_p = safe_float(grounding.get("lastPrice"))
            cash_close = safe_float(grounding.get("closePrice"))

            if last_p is not None and cash_close is not None and cash_close > 0:
                gap = ((last_p - cash_close) / cash_close) * 100.0
                return {
                    "session_gap_pct": {
                        "value": round(gap, 4),
                        "state": "CALCULATED",
                        "session_gap_anchor": "PRIOR_SESSION_CLOSE_QUOTE",
                    }
                }

            # Fallback to historical candle
            df, _ = self._clean_price_history()
            if not df.empty and len(df) >= 2:
                latest_open = safe_float(df["open"].iloc[-1])
                prev_close = safe_float(df["close"].iloc[-2])
                if latest_open is not None and prev_close is not None and prev_close > 0:
                    gap = ((latest_open - prev_close) / prev_close) * 100.0
                    return {
                        "session_gap_pct": {
                            "value": round(gap, 4),
                            "state": "CALCULATED",
                            "session_gap_anchor": "HISTORICAL_BAR_FALLBACK",
                        }
                    }

            return {
                "session_gap_pct": {
                    "value": None,
                    "state": "UNKNOWN",
                    "reason": "missing_cash_close_and_insufficient_history",
                }
            }
        except Exception as exc:
            return {
                "session_gap_pct": {
                    "value": None,
                    "state": "UNKNOWN",
                    "reason": f"step_0_failed_{type(exc).__name__}",
                }
            }

    # --------------------------------------------------------------------------
    # STEP 1: FUNDAMENTALS, QUALITY & VALUATION
    # --------------------------------------------------------------------------
    def _calc_step_1(self) -> Dict[str, Any]:
        """Calculates Step 1 with Tier 4 market cap divergence gating (PAY-26, PAY-43)."""
        fund = self.raw.get("step_1_fundamentals", {})
        pe = safe_float(fund.get("peRatio"))
        eps = safe_float(fund.get("eps"))
        pb = safe_float(fund.get("pbRatio"))
        pcf = safe_float(fund.get("pcfRatio"))
        div_amt = safe_float(fund.get("divAmount"))
        div_freq = safe_float(fund.get("divFreq"))
        shares_out = safe_float(fund.get("sharesOutstanding"))
        shares_st = fund.get("shares_outstanding_state", "UNVERIFIED")
        reported_mcap = safe_float(fund.get("marketCap"))
        dteq = safe_float(fund.get("totalDebtToEquity"))

        res: Dict[str, Any] = {
            "state": "CALCULATED",
            "earnings_yield_pct": None,
            "cfo_yield_pct": None,
            "cfo_per_share": None,
            "cfo_yield_derivation_basis": None,
            "imputed_dividend_payout_ratio_pct": None,
            "payout_ratio_exceeds_earnings": False,
            "payout_ratio_health": "SUSTAINABLE",
            "derived_market_cap": None,
            "reported_market_cap": reported_mcap,
            "imputed_book_value_of_equity": None,
            "imputed_total_debt": None,
            "enterprise_value_proxy": None,
            "free_cash_flow_yield_pct": None,
        }

        # 1. Earnings Yield (DEF-15 / DEF-04)
        if pe is not None and pe > 0:
            res["earnings_yield_pct"] = round((1.0 / pe) * 100.0, 4)
        elif pe is not None and pe <= 0:
            res["earnings_yield_pct"] = {
                "value": None,
                "state": "N/A",
                "reason": "earnings_negative_or_unstable_pe_ratio_non_positive",
            }
        elif eps is not None and self.spot is not None and self.spot > 0:
            ey = (eps / self.spot) * 100.0
            res["earnings_yield_pct"] = round(ey, 4) if ey > 0 else {
                "value": None,
                "state": "N/A",
                "reason": "earnings_negative_eps_non_positive",
            }

        # 2. Cash Flow Yield (PAY-06, PAY-13)
        if pcf is not None and pcf > 0:
            res["cfo_yield_pct"] = round((1.0 / pcf) * 100.0, 4)
            res["cfo_yield_derivation_basis"] = "inverse_pcf_ratio_scale_invariant"
            res["cfo_per_share"] = {
                "value": None,
                "state": "UNKNOWN",
                "reason": "operating_cash_flow_currency_units_unverified",
            }
        else:
            res["cfo_yield_pct"] = {
                "value": None,
                "state": "N/A",
                "reason": "cash_flow_negative_or_pcf_ratio_non_positive",
            }

        # 3. Dividend Payout Ratio & Capital Impairment (PAY-09)
        if eps is not None and eps > 0 and div_amt is not None:
            freq = div_freq if div_freq is not None and div_freq in {1.0, 2.0, 4.0, 12.0} else 1.0
            # If divAmount matches annualized yield or periodic
            annual_div = div_amt * freq if freq > 1.0 and abs(div_amt * freq - (eps * 2.0)) > abs(div_amt - eps) else div_amt
            payout = (annual_div / eps) * 100.0
            res["imputed_dividend_payout_ratio_pct"] = round(payout, 2)
            if payout > 100.0:
                res["payout_ratio_exceeds_earnings"] = True
                res["payout_ratio_health"] = "CAPITAL_IMPAIRMENT_RISK"
        elif eps is not None and eps <= 0:
            res["imputed_dividend_payout_ratio_pct"] = {
                "value": None,
                "state": "N/A",
                "reason": "cannot_impute_payout_ratio_on_negative_earnings",
            }

        # 4. Market Cap Divergence Engine (PAY-03, PAY-21, PAY-26, PAY-34, PAY-44, PAY-50, PAY-56)
        div_state = "UNVERIFIED_COMPONENTS"
        div_reason = None
        derived_mcap = None
        div_abs = None
        div_pct = None

        if shares_st == "UNAVAILABLE_FOR_FOREIGN_ADR" or shares_out is None or shares_out <= 0:
            div_state = "UNVERIFIED_COMPONENTS"
            div_reason = "requires_verified_shares_outstanding"
        elif self.spot is not None and self.spot > 0:
            derived_mcap = self.spot * shares_out
            res["derived_market_cap"] = derived_mcap

            if reported_mcap is not None and reported_mcap > 0:
                div_abs = abs(derived_mcap - reported_mcap)
                div_pct = (div_abs / reported_mcap) * 100.0

                # 4-Tier Divergence Classification (PAY-26)
                if div_pct > 20.0 and div_abs > 50e9:
                    div_state = "INTEGRITY_FAILURE_REQUIRES_REVIEW"
                    div_reason = "upstream_market_cap_divergence_integrity_failure"
                elif div_pct > 5.0 and div_abs > 5e9:
                    div_state = "SCHEMA_OR_CLASS_SUSPECTED"
                    div_reason = "multi_class_or_vintage_drift_suspected"
                elif div_pct > 0.50:
                    div_state = "FLOAT_OR_CLASS_DIFFERENTIAL"
                else:
                    div_state = "ALIGNED"

        # Canonical Nested Divergence Block (PAY-50)
        res["market_cap_divergence"] = {
            "derived_market_cap": derived_mcap,
            "reported_market_cap": reported_mcap,
            "market_cap_divergence_abs_usd": div_abs,
            "market_cap_divergence_pct": round(div_pct, 4) if div_pct is not None else None,
            "market_cap_divergence_state": div_state,
            "market_cap_divergence_reason": div_reason,
        }

        # Backwards-Compatibility Flat Keys (PAY-56)
        res["market_cap_divergence_state"] = div_state
        res["market_cap_divergence_pct"] = round(div_pct, 4) if div_pct is not None else None
        res["market_cap_divergence_abs_usd"] = div_abs

        # 5. Balance Sheet Derivations (BV, Debt)
        active_mcap = derived_mcap if derived_mcap is not None else reported_mcap
        if active_mcap is not None and pb is not None and pb > 0:
            bv = active_mcap / pb
            res["imputed_book_value_of_equity"] = round(bv, 2)
            if dteq is not None and self.debt_to_equity_unit == "PERCENTAGE":
                res["imputed_total_debt"] = round(bv * (dteq / 100.0), 2)
            elif dteq is not None and self.debt_to_equity_unit == "RATIO":
                res["imputed_total_debt"] = round(bv * dteq, 2)
            else:
                res["imputed_total_debt"] = {
                    "value": None,
                    "state": "UNKNOWN",
                    "reason": "total_debt_to_equity_unit_unverified",
                }
        else:
            res["imputed_book_value_of_equity"] = {
                "value": None,
                "state": "UNKNOWN",
                "reason": "requires_verified_market_cap_and_pb_ratio",
            }
            res["imputed_total_debt"] = {
                "value": None,
                "state": "UNKNOWN",
                "reason": "requires_verified_market_cap_and_pb_ratio",
            }

        # 6. UNIVERSAL INTEGRITY FAILURE GATE (PAY-43, PAY-49, PAY-55)
        if div_state == "INTEGRITY_FAILURE_REQUIRES_REVIEW":
            for field in MARKET_CAP_DEPENDENT_METRICS:
                res[field] = {
                    "state": "UNRELIABLE",
                    "reason": REASON_MARKET_CAP_INTEGRITY_FAILURE,
                    "market_cap_divergence_pct": round(div_pct, 2) if div_pct else None,
                    "market_cap_divergence_abs_usd": div_abs,
                }

        return res

    # --------------------------------------------------------------------------
    # STEP 3 & 7: DERIVATIVES, VOLATILITY & LOCATE
    # --------------------------------------------------------------------------
    def _calc_step_3_and_7(self) -> Dict[str, Any]:
        """Calculates Surface, CMI, Skew, and Event Straddle metrics."""
        return {
            "spot_provenance": self.spot_provenance,
            "constant_maturity_30d_iv": self._calc_cmi_30d(),
            "skew_30d": self._calc_30d_skew(),
            "atm_event_straddle": self._calc_atm_event_straddle(),
            "volume_and_oi_ratios": self._calc_volume_and_oi_ratios(),
        }

    def _calc_cmi_30d(self) -> Dict[str, Any]:
        """
        PAY-02 / PAY-12 / PAY-24: Linear variance interpolation across 3-tenor bracket.
        """
        raw_surface = self.raw.get("step_3_and_7_derivatives", {}).get("surface_parameters", {})
        vendor_iv = safe_float(raw_surface.get("volatility_30d_surface"))

        if self.options_df.empty or self.spot is None or self.spot <= 0:
            return {
                "value": None,
                "state": "UNKNOWN",
                "reason": "options_chain_empty_or_spot_unresolved",
                "vendor_raw_chain_volatility_metadata": vendor_iv,
            }

        df = self.options_df.copy()
        tenors = sorted(df["daysToExpiration"].dropna().unique())
        sub_tenors = [t for t in tenors if 4 <= t <= 30]
        sup_tenors = [t for t in tenors if t >= 30]

        if not sub_tenors or not sup_tenors:
            return {
                "value": None,
                "state": "UNKNOWN",
                "reason": "cannot_bracket_30d_tenor_for_cmi_interpolation",
                "vendor_raw_chain_volatility_metadata": vendor_iv,
            }

        t1 = max(sub_tenors)
        t2 = min(sup_tenors)

        def get_atm_iv(tenor: int) -> Optional[float]:
            chain = df[df["daysToExpiration"] == tenor].copy()
            if chain.empty:
                return None
            chain["strike_diff"] = (chain["strikePrice"] - self.spot).abs()
            min_diff = chain["strike_diff"].min()
            atm = chain[chain["strike_diff"] == min_diff]
            ivs = atm["volatility"].dropna()
            return float(ivs.mean()) if not ivs.empty else None

        iv1 = get_atm_iv(t1)
        iv2 = get_atm_iv(t2)

        if iv1 is None or iv2 is None:
            return {
                "value": None,
                "state": "UNKNOWN",
                "reason": "atm_volatility_unavailable_in_bracket_tenors",
                "vendor_raw_chain_volatility_metadata": vendor_iv,
            }

        if t1 == t2:
            cmi = iv1
        else:
            var1 = (iv1 / 100.0) ** 2 * (t1 / 365.0)
            var2 = (iv2 / 100.0) ** 2 * (t2 / 365.0)
            w = (30.0 - t1) / (t2 - t1)
            var30 = var1 + w * (var2 - var1)
            cmi = math.sqrt(max(0.0, var30 * (365.0 / 30.0))) * 100.0

        return {
            "value": round(cmi, 4),
            "state": "CALCULATED",
            "interpolation_method": "LINEAR_TOTAL_VARIANCE",
            "bracket_tenors": {"t1_dte": t1, "t1_iv": iv1, "t2_dte": t2, "t2_iv": iv2},
            "vendor_raw_chain_volatility_metadata": vendor_iv,
        }

    def _calc_30d_skew(self) -> Dict[str, Any]:
        """
        PAY-05 / PAY-20 / PAY-29 / PAY-39 / PAY-45: Hardened 25D skew with
        microstructure spread filter and bounded nearest-symmetric fallback.
        """
        if self.options_df.empty or self.spot is None or self.spot <= 0:
            return {
                "skew_30d_state": "UNKNOWN",
                "reason": "options_chain_empty_or_spot_unresolved",
            }

        df = self.options_df.copy()
        tenors = sorted(df["daysToExpiration"].dropna().unique())
        eligible_tenors = [t for t in tenors if t >= 4]
        if not eligible_tenors:
            return {
                "skew_30d_state": "UNKNOWN",
                "reason": "no_tenors_above_minimum_4_dte",
            }

        target_dte = min(eligible_tenors, key=lambda t: abs(t - 30))
        chain = df[df["daysToExpiration"] == target_dte].copy()

        # OTM Moneyness Gate (Kp < S < Kc)
        puts = chain[(chain["putCallIndicator"] == "PUT") & (chain["strikePrice"] < self.spot)].copy()
        calls = chain[(chain["putCallIndicator"] == "CALL") & (chain["strikePrice"] > self.spot)].copy()

        if puts.empty or calls.empty:
            return {
                "skew_30d_state": "UNKNOWN",
                "reason": "missing_otm_wings_in_selected_tenor",
                "selected_dte": target_dte,
            }

        # Calculate absolute deltas
        puts["delta_abs"] = puts["delta"].abs()
        calls["delta_abs"] = calls["delta"].abs()

        # Microstructure Relative Spread Filter (PAY-29, PAY-39, PAY-45)
        def evaluate_leg(leg_row: pd.Series, wing_name: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
            bid = safe_float(leg_row.get("bid"))
            ask = safe_float(leg_row.get("ask"))
            mark = safe_float(leg_row.get("mark"))
            if mark is None or mark <= 0.0 or bid is None or bid <= 0.0 or ask is None:
                return False, {
                    "rejected_wing": wing_name,
                    "observed_wing_relative_spread": None,
                    "reason": "zero_bid_or_non_positive_mark",
                }
            rel_spread = (ask - bid) / mark
            if rel_spread > self.max_skew_relative_spread:
                return False, {
                    "rejected_wing": wing_name,
                    "observed_wing_relative_spread": round(rel_spread, 4),
                    "reason": REASON_SKEW_SPREAD_TOLERANCE_EXCEEDED,
                }
            return True, None

        # Primary Search: 0.20 <= |delta| <= 0.30
        primary_puts = puts[(puts["delta_abs"] >= self.min_delta_tolerance) & (puts["delta_abs"] <= self.max_delta_tolerance)]
        primary_calls = calls[(calls["delta_abs"] >= self.min_delta_tolerance) & (calls["delta_abs"] <= self.max_delta_tolerance)]

        anchor = "PRIMARY_25D_SYMMETRIC"
        if not primary_puts.empty and not primary_calls.empty:
            put_row = primary_puts.iloc[(primary_puts["delta_abs"] - 0.25).abs().argmin()]
            call_row = primary_calls.iloc[(primary_calls["delta_abs"] - 0.25).abs().argmin()]
        else:
            # Bounded nearest-symmetric fallback (0.15 <= |delta| <= 0.45)
            anchor = "FALLBACK_NEAREST_SYMMETRIC"
            fallback_puts = puts[(puts["delta_abs"] >= 0.15) & (puts["delta_abs"] <= 0.45)]
            fallback_calls = calls[(calls["delta_abs"] >= 0.15) & (calls["delta_abs"] <= 0.45)]
            if fallback_puts.empty or fallback_calls.empty:
                return {
                    "skew_30d_state": "UNKNOWN",
                    "reason": "no_option_contracts_within_delta_tolerance_0.15_0.45",
                    "selected_dte": target_dte,
                }
            put_row = fallback_puts.iloc[(fallback_puts["delta_abs"] - 0.25).abs().argmin()]
            call_row = fallback_calls.iloc[(fallback_calls["delta_abs"] - 0.25).abs().argmin()]

        # Apply Microstructure Gate
        put_valid, put_diag = evaluate_leg(put_row, "PUT")
        call_valid, call_diag = evaluate_leg(call_row, "CALL")

        if not put_valid or not call_valid:
            failed_diag = put_diag if not put_valid else call_diag
            return {
                "skew_30d_state": "UNKNOWN",
                "skew_30d_reason": REASON_SKEW_SPREAD_TOLERANCE_EXCEEDED,
                "spread_tolerance_source": "DEFAULT_EXECUTION_BOUNDARY",
                "spread_tolerance_threshold": self.max_skew_relative_spread,
                "observed_wing_relative_spread": failed_diag["observed_wing_relative_spread"],
                "rejected_wing": failed_diag["rejected_wing"],
            }

        p_iv = safe_float(put_row.get("volatility"))
        c_iv = safe_float(call_row.get("volatility"))

        if p_iv is None or c_iv is None or c_iv <= 0:
            return {
                "skew_30d_state": "UNKNOWN",
                "reason": "implied_volatility_missing_on_selected_legs",
            }

        diff = p_iv - c_iv
        ratio = p_iv / c_iv
        regime = "NORMAL_PUT_SKEW" if ratio >= 0.70 else "INVERTED_CALL_SKEW_REGIME"

        return {
            "skew_30d_state": "CALCULATED",
            "skew_30d_iv_differential": round(diff, 4),
            "skew_30d_normalized_ratio": round(ratio, 4),
            "skew_actual_put_delta": round(float(put_row["delta"]), 4),
            "skew_actual_call_delta": round(float(call_row["delta"]), 4),
            "skew_delta_anchor": anchor,
            "skew_tenor_dte": target_dte,
            "skew_regime": regime,
            "skew_regime_type": "ILLUSTRATIVE_CONVENTION",
        }

    def _calc_atm_event_straddle(self) -> Dict[str, Any]:
        """PAY-07 / PAY-17: Event straddle with fat-tail adjusted convention."""
        if self.options_df.empty or self.spot is None or self.spot <= 0:
            return {
                "state": "UNKNOWN",
                "reason": "options_chain_empty_or_spot_unresolved",
            }

        df = self.options_df.copy()
        tenors = sorted(df["daysToExpiration"].dropna().unique())
        front_tenors = [t for t in tenors if t >= 1]
        if not front_tenors:
            return {
                "state": "UNKNOWN",
                "reason": "only_0dte_expiration_available_insufficient_for_event_straddle",
            }

        front_dte = min(front_tenors)
        chain = df[df["daysToExpiration"] == front_dte].copy()

        chain["strike_diff"] = (chain["strikePrice"] - self.spot).abs()
        atm_strike = chain.loc[chain["strike_diff"].idxmin(), "strikePrice"]

        put_match = chain[(chain["strikePrice"] == atm_strike) & (chain["putCallIndicator"] == "PUT")]
        call_match = chain[(chain["strikePrice"] == atm_strike) & (chain["putCallIndicator"] == "CALL")]

        if put_match.empty or call_match.empty:
            return {
                "state": "UNKNOWN",
                "reason": "atm_put_or_call_missing",
            }

        p_mark = safe_float(put_match["mark"].values[0])
        c_mark = safe_float(call_match["mark"].values[0])

        if p_mark is None or c_mark is None:
            return {
                "state": "UNKNOWN",
                "reason": "atm_mark_unavailable",
            }

        straddle_cost = p_mark + c_mark
        implied_move_pct = (straddle_cost / self.spot) * 100.0
        rule_of_thumb_move = implied_move_pct * 0.85

        return {
            "state": "CALCULATED",
            "atm_strike": float(atm_strike),
            "front_dte": int(front_dte),
            "straddle_nominal_cost": round(straddle_cost, 2),
            "implied_move_pct": round(implied_move_pct, 4),
            "fat_tail_adjusted_move_pct": round(rule_of_thumb_move, 4),
            "heuristic_anchor": "PRACTITIONER_FAT_TAIL_ADJUSTED_CONVENTION",
            "factor": 0.85,
        }

    def _calc_volume_and_oi_ratios(self) -> Dict[str, Any]:
        """Put/Call volume and Open Interest ratios."""
        if self.options_df.empty:
            return {
                "state": "UNKNOWN",
                "put_call_volume_ratio": None,
                "put_call_oi_ratio": None,
            }
        df = self.options_df
        puts = df[df["putCallIndicator"] == "PUT"]
        calls = df[df["putCallIndicator"] == "CALL"]

        put_vol = puts["totalVolume"].dropna().sum()
        call_vol = calls["totalVolume"].dropna().sum()
        put_oi = puts["openInterest"].dropna().sum()
        call_oi = calls["openInterest"].dropna().sum()

        return {
            "state": "CALCULATED",
            "put_call_volume_ratio": round(put_vol / call_vol, 4) if call_vol > 0 else None,
            "put_call_oi_ratio": round(put_oi / call_oi, 4) if call_oi > 0 else None,
        }

    # --------------------------------------------------------------------------
    # STEP 5: TECHNICALS & REALIZED VOLATILITY
    # --------------------------------------------------------------------------
    def _clean_price_history(self) -> Tuple[pd.DataFrame, Optional[str]]:
        """Cleans and validates historical OHLCV data."""
        if self.price_history_df.empty:
            return pd.DataFrame(), "price_history_dataframe_empty"
        df = self.price_history_df.copy()
        cols = ["open", "high", "low", "close", "volume"]
        for c in cols:
            if c not in df.columns:
                return pd.DataFrame(), f"missing_required_column_{c}"
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=cols)
        df = df[(df["high"] >= df["low"]) & (df["low"] > 0) & (df["close"] > 0)]
        if len(df) < 2:
            return pd.DataFrame(), "insufficient_valid_price_history_bars"
        return df, None

    def _calc_step_5(self) -> Dict[str, Any]:
        """Calculates Realized Volatilities and Floor Pivots."""
        df, err = self._clean_price_history()
        if not df.empty:
            latest = df.iloc[-1]
            H, L, C = latest["high"], latest["low"], latest["close"]
            P = (H + L + C) / 3.0
            pivots = {
                "state": "CALCULATED",
                "Pivot": round(P, 2),
                "R1": round((2 * P) - L, 2),
                "R2": round(P + (H - L), 2),
                "R3": round(H + 2 * (P - L), 2),
                "S1": round((2 * P) - H, 2),
                "S2": round(P - (H - L), 2),
                "S3": round(L - 2 * (H - P), 2),
            }
        else:
            pivots = {"state": "UNKNOWN", "reason": err}

        return {
            "classical_floor_pivots": pivots,
            "realized_volatility": self._calc_realized_volatility(df, err),
        }

    def _calc_realized_volatility(
        self, df: pd.DataFrame, err: Optional[str]
    ) -> Dict[str, Any]:
        """
        PAY-28 / PAY-42 / PAY-48: 3-tier sample window governance:
          FULL_HISTORY (>=240), PARTIAL_HISTORY (180-239), INSUFFICIENT_HISTORY (<180).
        """
        if df.empty:
            return {"state": "UNKNOWN", "reason": err}

        windows = {"10d_tactical": 10, "30d_intermediate": 30, "252d_macro": 252}
        results: Dict[str, Any] = {"state": "CALCULATED"}

        for win_name, target_bars in windows.items():
            sample_df = df.tail(target_bars + 1)
            actual_bars = len(sample_df)
            n_obs = actual_bars - 1

            if n_obs < 2:
                results[win_name] = {
                    "state": "UNKNOWN",
                    "reason": "insufficient_observations_for_window",
                    "actual_sample_bars": actual_bars,
                }
                continue

            log_rets = np.log(sample_df["close"] / sample_df["close"].shift(1)).dropna()
            c2c = float(np.sqrt(self.trading_days_per_year) * log_rets.std() * 100.0)

            hl_log = np.log(sample_df["high"] / sample_df["low"])
            park_var = (1.0 / (4.0 * np.log(2.0))) * (hl_log ** 2).mean()
            park = float(np.sqrt(self.trading_days_per_year * park_var) * 100.0)

            co_log = np.log(sample_df["close"] / sample_df["open"])
            gk_var = (0.5 * (hl_log ** 2)) - ((2.0 * np.log(2.0) - 1.0) * (co_log ** 2))
            gk = float(np.sqrt(self.trading_days_per_year * max(0.0, gk_var.mean())) * 100.0)

            # Sample Window Governance (PAY-48)
            if win_name == "252d_macro":
                if actual_bars < 180:
                    results[win_name] = {
                        "state": "INSUFFICIENT_HISTORY",
                        "target_window_bars": 252,
                        "actual_sample_bars": actual_bars,
                        "return_observations": n_obs,
                        "computed_realized_vol": round(c2c, 2),
                        "reason": "sample_bars_below_minimum_macro_threshold_180",
                    }
                    continue
                tier = "FULL_HISTORY" if actual_bars >= 240 else "PARTIAL_HISTORY"
            else:
                tier = "FULL_HISTORY" if actual_bars >= target_bars else "PARTIAL_HISTORY"

            results[win_name] = {
                "status": tier,
                "actual_sample_bars": actual_bars,
                "return_observations": n_obs,
                "close_to_close": round(c2c, 2),
                "parkinson": round(park, 2),
                "garman_klass": round(gk, 2),
                "estimator_methodology": "Garman-Klass (1980) zero-drift invariant",
            }

        return results