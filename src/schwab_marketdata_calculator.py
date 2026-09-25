"""
schwab_marketdata_calculator.py
========================================================================================
QUANTITATIVE DERIVATIVES, VOLATILITY & TECHNICAL RISK ANALYTICS ENGINE
Institutional Specification: Master Thesis & Risk Protocol (v16.20)
========================================================================================

REQUIRED UPSTREAM PARAMETERS & INTERFACE CONTRACT:
----------------------------------------------------------------------------------------
Parameter Name              | Responsible Source           | Default / Fallback Behavior
----------------------------------------------------------------------------------------
TOTAL_DEBT_TO_EQUITY_UNIT   | Upstream Fundamental / Config| If unset: gates imputed_total_debt
                            | ('PERCENTAGE' or 'RATIO')    | to Step 0.5 UNKNOWN.
includeUnderlyingQuote      | schwab_raw_marketdata.py     | Must be passed as True in
                            | (Option Chains Endpoint)     | get_option_chain() for low vintage risk.
MAX_RELATIVE_SPREAD         | params (Risk Model Config)   | Defaults to 0.25 (25% of mid).
MIN_DELTA_TOLERANCE         | params (Option Surface)      | Defaults to 0.20 (~25Δ band).
MAX_DELTA_TOLERANCE         | params (Option Surface)      | Defaults to 0.30 (~25Δ band).
MAX_30D_DTE_TOLERANCE       | params (Option Surface)      | Defaults to 7 (±7 days around 30 DTE).
MAX_EVENT_DTE_TOLERANCE     | params (Option Surface)      | Defaults to 14 (1 to 14 DTE event gate).
MAX_STRIKE_SEARCH_DEPTH     | params (Option Surface)      | Defaults to 2 (±2 strikes from ATM).
TRADING_DAYS_PER_YEAR       | params (Volatility Engine)   | Defaults to 252.0.
========================================================================================
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("MasterThesisEngine")


def safe_div(num: Any, den: Any) -> Optional[float]:
    """Safely divides two scalar numerical values with defensive casting."""
    try:
        if num is None or den is None:
            return None
        if not isinstance(num, (int, float, np.number)) or not isinstance(den, (int, float, np.number)):
            return None
        if pd.isna(num) or pd.isna(den):
            return None
        n, d = float(num), float(den)
        if math.isnan(n) or math.isnan(d) or math.isinf(n) or math.isinf(d):
            return None
        return n / d if d != 0.0 else None
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def safe_float(val: Any) -> Optional[float]:
    """
    Defensively coerces a scalar value or numeric string to float.
    Rejects non-scalars, booleans, NaNs, and infinities.
    Logs a warning if a currency-formatted string is encountered to preserve observability.
    """
    if val is None or isinstance(val, bool):
        return None

    if isinstance(val, str):
        stripped = val.strip()
        if stripped and stripped[0] in "$£€¥₹₩":
            logger.warning(
                "safe_float coerced currency-formatted string '%s'; "
                "check upstream extraction for type regression.",
                val,
            )
            stripped = stripped.lstrip("$£€¥₹₩").replace(",", "")
            try:
                f = float(stripped)
                return None if (math.isnan(f) or math.isinf(f)) else f
            except (ValueError, TypeError):
                return None

    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (ValueError, TypeError):
        return None


class MasterThesisCalculator:
    """Institutional quantitative engine under Master Thesis Protocol v16.20."""

    def __init__(
        self,
        raw_data: Optional[Dict[str, Any]],
        price_history_df: Optional[pd.DataFrame],
        options_df: Optional[pd.DataFrame],
        params: Optional[Dict[str, Any]] = None,
    ):
        self.raw: Dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        self.params: Dict[str, Any] = params if isinstance(params, dict) else {}
        self.price_history_df: pd.DataFrame = (
            price_history_df.copy() if isinstance(price_history_df, pd.DataFrame) else pd.DataFrame()
        )
        self.options_df: pd.DataFrame = (
            options_df.copy() if isinstance(options_df, pd.DataFrame) else pd.DataFrame()
        )

        # DEF-10: Observable Provenance Ledger (Step 0.4 Vintage Alignment)
        raw_chain_spot = (
            self.raw.get("step_3_and_7_derivatives", {})
            .get("surface_parameters", {})
            .get("underlyingPrice")
            if isinstance(self.raw.get("step_3_and_7_derivatives"), dict)
            else None
        )
        grounding_spot = (
            self.raw.get("phase_0_grounding", {}).get("lastPrice")
            if isinstance(self.raw.get("phase_0_grounding"), dict)
            else None
        )

        if raw_chain_spot is not None and safe_float(raw_chain_spot) is not None:
            self.spot: Optional[float] = safe_float(raw_chain_spot)
            self.spot_provenance = {
                "source": "options_payload_underlyingPrice",
                "vintage_risk": "LOW",
                "reason": "payload_embedded_underlying_price",
            }
        elif grounding_spot is not None and safe_float(grounding_spot) is not None:
            self.spot = safe_float(grounding_spot)
            self.spot_provenance = {
                "source": "phase_0_grounding_lastPrice",
                "vintage_risk": "MEDIUM",
                "reason": "fallback_to_phase_0_grounding",
            }
        else:
            self.spot = None
            self.spot_provenance = {
                "source": "UNRESOLVED",
                "vintage_risk": "UNKNOWN",
                "reason": "no_spot_price_located_in_payloads",
            }

        raw_fund = self.raw.get("step_1_fundamentals")
        self.fundamentals: Dict[str, Any] = raw_fund if isinstance(raw_fund, dict) else {}

        raw_liq = self.raw.get("step_8_and_9_liquidity_and_sizing")
        self.liquidity: Dict[str, Any] = raw_liq if isinstance(raw_liq, dict) else {}

        # Parameterized Institutional Calibration Defaults (Protocol v16.20)
        self.trading_days_per_year: float = safe_float(self.params.get("TRADING_DAYS_PER_YEAR")) or 252.0
        self.min_delta_tolerance: float = safe_float(self.params.get("MIN_DELTA_TOLERANCE")) or 0.20
        self.max_delta_tolerance: float = safe_float(self.params.get("MAX_DELTA_TOLERANCE")) or 0.30
        self.max_relative_spread: float = safe_float(self.params.get("MAX_RELATIVE_SPREAD")) or 0.25
        self.max_strike_search_depth: int = int(self.params.get("MAX_STRIKE_SEARCH_DEPTH", 2))
        self.max_30d_dte_tolerance: int = int(self.params.get("MAX_30D_DTE_TOLERANCE", 7))
        self.max_event_dte_tolerance: int = int(self.params.get("MAX_EVENT_DTE_TOLERANCE", 14))

    def calculate_metrics(self) -> Dict[str, Any]:
        """Orchestrates computational routines across all thesis phases."""
        return {
            "spot_provenance": self.spot_provenance,
            "step_0_grounding": self._calc_step_0(),
            "step_1_fundamentals_and_quality": self._calc_step_1(),
            "step_3_and_7_derivatives_and_surface": self._calc_step_3_and_7(),
            "step_5_technicals_and_flows": self._calc_step_5(),
        }

    # --------------------------------------------------------------------------
    # STEP 0: TEMPORAL GROUNDING & GAP DYNAMICS
    # --------------------------------------------------------------------------
    def _calc_step_0(self) -> Dict[str, Any]:
        """Calculates overnight session opening price gap percentage with strict schema uniformity."""
        try:
            grounding = self.raw.get("phase_0_grounding")
            if not isinstance(grounding, dict):
                return {
                    "session_gap_pct": {
                        "value": None,
                        "state": "UNKNOWN",
                        "reason": "phase_0_grounding_payload_missing_or_invalid",
                    }
                }

            prev_close = safe_float(grounding.get("closePrice"))
            df, error = self._clean_and_sort_price_history()

            if df.empty:
                return {
                    "session_gap_pct": {
                        "value": None,
                        "state": "UNKNOWN",
                        "reason": error or "price_history_empty_or_unparseable",
                    }
                }

            if prev_close is None or prev_close <= 0.0:
                return {
                    "session_gap_pct": {
                        "value": None,
                        "state": "UNKNOWN",
                        "reason": "non_positive_or_missing_prev_close",
                    }
                }

            latest = df.iloc[-1]
            open_price = safe_float(latest.get("open"))
            if open_price is None:
                return {
                    "session_gap_pct": {
                        "value": None,
                        "state": "UNKNOWN",
                        "reason": "latest_bar_open_price_missing",
                    }
                }

            gap_ratio = safe_div(open_price - prev_close, prev_close)
            if gap_ratio is None:
                return {
                    "session_gap_pct": {
                        "value": None,
                        "state": "UNKNOWN",
                        "reason": "session_gap_calculation_failed_zero_denominator",
                    }
                }

            return {
                "session_gap_pct": {
                    "value": gap_ratio * 100.0,
                    "state": "CALCULATED",
                }
            }

        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Step 0 computation error: %s", exc)
            return {
                "session_gap_pct": {
                    "value": None,
                    "state": "UNKNOWN",
                    "reason": f"step_0_execution_failed_{type(exc).__name__}",
                }
            }

    # --------------------------------------------------------------------------
    # STEP 1: VALUATION DENOMINATOR SAFETY & BALANCE SHEET QUALITY
    # --------------------------------------------------------------------------
    def _calc_step_1(self) -> Dict[str, Any]:
        """
        Derives valuation yields, cash flow dynamics, and balance-sheet estimates.
        Enforces schema envelope consistency across both success and failure paths.
        """
        try:
            pe = safe_float(self.fundamentals.get("peRatio"))
            eps = safe_float(self.fundamentals.get("eps"))
            div = safe_float(self.fundamentals.get("divAmount"))
            pcf = safe_float(self.fundamentals.get("pcfRatio"))
            shares_out = safe_float(self.fundamentals.get("sharesOutstanding"))
            pb = safe_float(self.fundamentals.get("pbRatio"))
            dteq = safe_float(self.fundamentals.get("totalDebtToEquity"))

            # Step 1 Denominator Safety: Suppress non-positive multiples
            earnings_yield: Any
            if pe is not None and pe > 0.0:
                ratio = safe_div(1.0, pe)
                earnings_yield = (ratio * 100.0) if ratio is not None else None
            elif (pe is not None and pe <= 0.0) or (eps is not None and eps <= 0.0):
                earnings_yield = {
                    "state": "N/A",
                    "reason": "earnings_negative_or_unstable_pe_ratio_non_positive",
                    "underlying_pe_ratio": pe,
                    "underlying_eps": eps,
                }
            elif eps is not None and self.spot is not None and eps > 0.0:
                ratio = safe_div(eps, self.spot)
                earnings_yield = (ratio * 100.0) if ratio is not None else None
            else:
                earnings_yield = {
                    "state": "UNKNOWN",
                    "reason": "missing_or_insufficient_earnings_data",
                }

            # Dividend Payout Ratio with Step 0.5 N/A conformance on negative EPS
            payout_ratio: Any
            if div is not None and eps is not None:
                if eps > 0.0:
                    pr = safe_div(div, eps)
                    payout_ratio = (pr * 100.0) if pr is not None else None
                else:
                    payout_ratio = {
                        "state": "N/A",
                        "reason": "eps_non_positive_dividend_coverage_undefined",
                        "underlying_divAmount": div,
                        "underlying_eps": eps,
                    }
            else:
                payout_ratio = {
                    "state": "UNKNOWN",
                    "reason": "missing_dividend_or_eps_data",
                }

            # PCF / CFO Derivations
            cfo_per_share: Any = {
                "state": "UNKNOWN",
                "reason": "pcf_ratio_denominator_dimension_unverified",
            }

            cfo_yield: Any
            if pcf is not None and pcf > 0.0:
                cfy = safe_div(1.0, pcf)
                cfo_yield = (cfy * 100.0) if cfy is not None else None
            elif pcf is not None and pcf <= 0.0:
                cfo_yield = {
                    "state": "N/A",
                    "reason": "cash_flow_negative_or_unstable",
                    "underlying_pcf_ratio": pcf,
                }
            else:
                cfo_yield = {
                    "state": "UNKNOWN",
                    "reason": "missing_or_insufficient_pcf_data",
                }

            # DEF-09: Pure market cap derivation without magnitude guessing
            mcap: Optional[float] = None
            if self.spot is not None and shares_out is not None and shares_out > 0.0:
                mcap = self.spot * shares_out

            # Imputed Book Value of Equity
            imputed_bv: Any
            if mcap is not None and pb is not None and pb > 0.0:
                imputed_bv = safe_div(mcap, pb)
            else:
                imputed_bv = {
                    "state": "UNKNOWN",
                    "reason": "market_cap_requires_verified_components" if mcap is None else "pb_ratio_unresolved_or_non_positive",
                }

            # DEF-02: Strict Unit Gating for Total Debt
            imputed_debt: Any
            declared_dteq_unit = str(self.params.get("TOTAL_DEBT_TO_EQUITY_UNIT", "")).strip().upper()
            bv_val = imputed_bv if isinstance(imputed_bv, (int, float)) else None

            if bv_val is not None and dteq is not None:
                if declared_dteq_unit in ("PERCENTAGE", "PCT"):
                    imputed_debt = bv_val * (dteq / 100.0)
                elif declared_dteq_unit in ("RATIO", "DECIMAL"):
                    imputed_debt = bv_val * dteq
                else:
                    imputed_debt = {
                        "state": "UNKNOWN",
                        "reason": "total_debt_to_equity_unit_unverified_scale_risk",
                        "underlying_totalDebtToEquity": dteq,
                    }
            else:
                imputed_debt = {
                    "state": "UNKNOWN",
                    "reason": "book_value_or_debt_to_equity_unavailable",
                }

            return {
                "earnings_yield_pct": earnings_yield,
                "imputed_dividend_payout_ratio_pct": payout_ratio,
                "cfo_per_share": cfo_per_share,
                "cfo_yield_pct": cfo_yield,
                "imputed_book_value_of_equity": imputed_bv,
                "imputed_total_debt": imputed_debt,
                "state": "CALCULATED",
            }

        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Step 1 computation error: %s", exc)
            return {
                "earnings_yield_pct": None,
                "imputed_dividend_payout_ratio_pct": None,
                "cfo_per_share": None,
                "cfo_yield_pct": None,
                "imputed_book_value_of_equity": None,
                "imputed_total_debt": None,
                "state": "UNKNOWN",
                "reason": f"step_1_execution_failed_{type(exc).__name__}",
            }

    # --------------------------------------------------------------------------
    # STEPS 3 & 7: DERIVATIVES, SURFACE, REALIZED VOLATILITY & FLOWS
    # --------------------------------------------------------------------------
    def _calc_step_3_and_7(self) -> Dict[str, Any]:
        """Dispatches and consolidates quantitative derivatives analytics."""
        calc: Dict[str, Any] = {}
        calc["realized_volatility"] = self._calc_realized_volatilities()
        calc["flow_ratios"] = self._calc_volume_and_oi_ratios()
        calc["skew_30d"] = self._calc_30d_skew()
        calc["event_implied_move"] = self._calc_atm_event_straddle()
        return calc

    def _calc_realized_volatilities(self) -> Dict[str, Any]:
        """Multi-horizon realized volatility estimates with guaranteed schema envelopes."""
        windows = {
            "10d_tactical": 10,
            "21d_tenor_match": 21,
            "252d_macro": 252,
        }

        results: Dict[str, Any] = {
            label: {
                "sample_bars": None,
                "return_observations": None,
                "close_to_close": None,
                "parkinson": None,
                "garman_klass": None,
                "estimator_methodology": "Zero-Drift Continuous GK Variant",
                "state": "INITIALIZED",
            }
            for label in windows
        }

        df, error = self._clean_and_sort_price_history()
        required_cols = {"open", "high", "low", "close"}

        if df.empty or not required_cols.issubset(set(df.columns)):
            err_reason = error or "price_history_missing_required_ohlc_columns"
            for label in results:
                results[label]["state"] = "UNKNOWN"
                results[label]["reason"] = err_reason
            return results

        ann_factor = self.trading_days_per_year

        for label, window_size in windows.items():
            sub_df = df.tail(window_size)
            n_bars = len(sub_df)
            n_returns = max(0, n_bars - 1)

            results[label]["sample_bars"] = n_bars
            results[label]["return_observations"] = n_returns

            if n_bars < 5 or n_returns < 4:
                results[label]["state"] = "UNKNOWN"
                results[label]["reason"] = f"insufficient_bars_for_window_{window_size}"
                continue

            try:
                log_rets = np.log(sub_df["close"] / sub_df["close"].shift(1)).dropna()
                c2c = float(np.sqrt(ann_factor) * log_rets.std(ddof=1) * 100.0)

                hl_log = np.log(sub_df["high"] / sub_df["low"])
                park_var = (1.0 / (4.0 * np.log(2.0))) * (hl_log ** 2).mean()
                parkinson = float(np.sqrt(ann_factor * park_var) * 100.0)

                co_log = np.log(sub_df["close"] / sub_df["open"])
                gk_var = (0.5 * (hl_log ** 2)) - ((2.0 * np.log(2.0) - 1.0) * (co_log ** 2))
                garman_klass = float(np.sqrt(ann_factor * max(0.0, gk_var.mean())) * 100.0)

                results[label].update(
                    {
                        "close_to_close": c2c,
                        "parkinson": parkinson,
                        "garman_klass": garman_klass,
                        "state": "CALCULATED",
                    }
                )
            except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
                logger.warning("Volatility calculation error on %s: %s", label, exc)
                results[label]["state"] = "UNKNOWN"
                results[label]["reason"] = f"volatility_math_error_{type(exc).__name__}"

        return results

    def _calc_volume_and_oi_ratios(self) -> Dict[str, Any]:
        """Computes Put/Call volume and open interest flow ratios with defensive guards."""
        res: Dict[str, Any] = {
            "put_call_volume_ratio": None,
            "put_call_open_interest_ratio": None,
            "state": "INITIALIZED",
        }
        df = self.options_df
        required_cols = {"putCallIndicator", "totalVolume", "openInterest"}

        if df.empty or not required_cols.issubset(set(df.columns)):
            res["state"] = "UNKNOWN"
            res["reason"] = "options_chain_empty_or_missing_columns"
            return res

        try:
            puts = df[df["putCallIndicator"].astype(str).str.upper() == "PUT"]
            calls = df[df["putCallIndicator"].astype(str).str.upper() == "CALL"]

            p_vol = pd.to_numeric(puts["totalVolume"], errors="coerce").fillna(0.0).sum()
            c_vol = pd.to_numeric(calls["totalVolume"], errors="coerce").fillna(0.0).sum()
            res["put_call_volume_ratio"] = safe_div(p_vol, c_vol)

            p_oi = pd.to_numeric(puts["openInterest"], errors="coerce").fillna(0.0).sum()
            c_oi = pd.to_numeric(calls["openInterest"], errors="coerce").fillna(0.0).sum()
            res["put_call_open_interest_ratio"] = safe_div(p_oi, c_oi)
            res["state"] = "CALCULATED"

        except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError) as exc:
            logger.warning("Volume/OI ratio computation error: %s", exc)
            res["state"] = "UNKNOWN"
            res["reason"] = f"flow_calculation_error_{type(exc).__name__}"

        return res

    def _calc_30d_skew(self) -> Dict[str, Any]:
        """Derives 30-day ~25Δ volatility skew under a strict envelope schema."""
        envelope: Dict[str, Any] = {
            "skew_tenor_dte": None,
            "skew_30d_iv_differential": None,
            "skew_30d_normalized_ratio": None,
            "skew_actual_put_delta": None,
            "skew_actual_call_delta": None,
            "state": "INITIALIZED",
        }

        df = self.options_df
        required_cols = {"daysToExpiration", "putCallIndicator", "delta", "volatility"}

        if df.empty or not required_cols.issubset(set(df.columns)):
            envelope["state"] = "UNKNOWN"
            envelope["reason"] = "options_chain_empty_or_missing_columns"
            return envelope

        try:
            dtes = pd.to_numeric(df["daysToExpiration"], errors="coerce").dropna()
            if dtes.empty:
                envelope["state"] = "UNKNOWN"
                envelope["reason"] = "no_valid_dtes_in_options_chain"
                return envelope

            min_dte_diff = (dtes - 30.0).abs().min()
            if min_dte_diff > self.max_30d_dte_tolerance:
                envelope["state"] = "UNKNOWN"
                envelope["reason"] = f"no_options_chain_near_30d_tenor_within_tolerance_{self.max_30d_dte_tolerance}"
                envelope["closest_observed_dte"] = int(dtes.loc[(dtes - 30.0).abs().idxmin()])
                return envelope

            target_dte = dtes.loc[(dtes - 30.0).abs().idxmin()]
            chain_30d = df[pd.to_numeric(df["daysToExpiration"], errors="coerce") == target_dte].copy()

            chain_30d["delta_clean"] = pd.to_numeric(chain_30d["delta"], errors="coerce")
            chain_30d["delta_abs"] = chain_30d["delta_clean"].abs()
            chain_30d["iv_clean"] = pd.to_numeric(chain_30d["volatility"], errors="coerce")

            puts = chain_30d[chain_30d["putCallIndicator"].astype(str).str.upper() == "PUT"].dropna(
                subset=["delta_abs", "iv_clean"]
            )
            calls = chain_30d[chain_30d["putCallIndicator"].astype(str).str.upper() == "CALL"].dropna(
                subset=["delta_abs", "iv_clean"]
            )

            if puts.empty or calls.empty:
                envelope["state"] = "UNKNOWN"
                envelope["reason"] = "missing_clean_puts_or_calls_for_target_tenor"
                envelope["skew_tenor_dte"] = int(target_dte)
                return envelope

            best_put = puts.loc[(puts["delta_abs"] - 0.25).abs().idxmin()]
            best_call = calls.loc[(calls["delta_abs"] - 0.25).abs().idxmin()]

            p_delta = float(best_put["delta_abs"])
            c_delta = float(best_call["delta_abs"])

            envelope["skew_tenor_dte"] = int(target_dte)
            envelope["skew_actual_put_delta"] = p_delta
            envelope["skew_actual_call_delta"] = c_delta

            lo, hi = self.min_delta_tolerance, self.max_delta_tolerance
            if not (lo <= p_delta <= hi) or not (lo <= c_delta <= hi):
                envelope["state"] = "UNKNOWN"
                envelope["reason"] = f"no_contract_within_delta_tolerance_[{lo:.2f},{hi:.2f}]"
                return envelope

            iv_p = float(best_put["iv_clean"])
            iv_c = float(best_call["iv_clean"])

            if iv_p <= 0.0 or iv_c <= 0.0:
                envelope["state"] = "UNKNOWN"
                envelope["reason"] = "non_positive_implied_volatility_observed"
                return envelope

            envelope["skew_30d_iv_differential"] = iv_p - iv_c
            envelope["skew_30d_normalized_ratio"] = safe_div(iv_p, iv_c)
            envelope["state"] = "CALCULATED"
            return envelope

        except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError) as exc:
            logger.warning("30-Day Skew calculation error: %s", exc)
            envelope["state"] = "UNKNOWN"
            envelope["reason"] = f"skew_calculation_failed_{type(exc).__name__}"
            return envelope

    def _calc_atm_event_straddle(self) -> Dict[str, Any]:
        """Derives front-month event implied move bounded by MAX_EVENT_DTE_TOLERANCE."""
        envelope: Dict[str, Any] = {
            "event_tenor_dte": None,
            "event_atm_strike": None,
            "event_straddle_breakeven_pct": None,
            "event_implied_expected_move_pct": None,
            "state": "INITIALIZED",
        }

        df = self.options_df
        required_cols = {"daysToExpiration", "strikePrice", "putCallIndicator", "mark", "bid", "ask"}

        if self.spot is None or df.empty or not required_cols.issubset(set(df.columns)):
            envelope["state"] = "UNKNOWN"
            envelope["reason"] = "missing_spot_or_options_chain_columns"
            return envelope

        try:
            dtes = pd.to_numeric(df["daysToExpiration"], errors="coerce").dropna()

            # Gated bounded search: 1 <= DTE <= MAX_EVENT_DTE_TOLERANCE
            valid_post_event_dtes = dtes[(dtes >= 1) & (dtes <= self.max_event_dte_tolerance)]
            if valid_post_event_dtes.empty:
                has_0dte = (dtes == 0).any()
                envelope["state"] = "UNKNOWN"
                envelope["reason"] = (
                    "only_0dte_expiration_available_insufficient_for_event_straddle"
                    if has_0dte
                    else f"no_expiration_within_event_dte_window_1_to_{self.max_event_dte_tolerance}"
                )
                return envelope

            front_dte = valid_post_event_dtes.min()
            front_chain = df[pd.to_numeric(df["daysToExpiration"], errors="coerce") == front_dte].copy()

            for col in ["strikePrice", "mark", "bid", "ask"]:
                front_chain[col] = pd.to_numeric(front_chain[col], errors="coerce")

            # DEF-OUT-06: Pre-flight quote check distinguishing empty broker feeds from depth exhaustion
            if front_chain["bid"].dropna().empty or front_chain["mark"].dropna().empty:
                envelope["event_tenor_dte"] = int(front_dte)
                envelope["state"] = "UNKNOWN"
                envelope["reason"] = "options_chain_bid_ask_mark_unpopulated_or_all_nan"
                return envelope

            available_strikes = sorted(front_chain["strikePrice"].dropna().unique())
            if not available_strikes:
                envelope["state"] = "UNKNOWN"
                envelope["reason"] = "no_strikes_available_for_front_dte"
                envelope["event_tenor_dte"] = int(front_dte)
                return envelope

            strikes_by_distance = sorted(available_strikes, key=lambda k: abs(k - self.spot))

            evaluated_depth = 0
            for candidate_strike in strikes_by_distance:
                if evaluated_depth >= self.max_strike_search_depth:
                    break
                evaluated_depth += 1

                put_match = front_chain[
                    (front_chain["strikePrice"] == candidate_strike)
                    & (front_chain["putCallIndicator"].astype(str).str.upper() == "PUT")
                ]
                call_match = front_chain[
                    (front_chain["strikePrice"] == candidate_strike)
                    & (front_chain["putCallIndicator"].astype(str).str.upper() == "CALL")
                ]

                if put_match.empty or call_match.empty:
                    continue

                p_row, c_row = put_match.iloc[0], call_match.iloc[0]
                p_bid, p_ask, p_mark = p_row["bid"], p_row["ask"], p_row["mark"]
                c_bid, c_ask, c_mark = c_row["bid"], c_row["ask"], c_row["mark"]

                if any(pd.isna(x) or x <= 0.0 for x in [p_bid, p_mark, p_ask]):
                    continue
                if any(pd.isna(x) or x <= 0.0 for x in [c_bid, c_mark, c_ask]):
                    continue

                p_rel_spread = (p_ask - p_bid) / p_mark
                c_rel_spread = (c_ask - c_bid) / c_mark

                if pd.isna(p_rel_spread) or pd.isna(c_rel_spread):
                    continue
                if p_rel_spread > self.max_relative_spread or c_rel_spread > self.max_relative_spread:
                    continue

                straddle_cost = float(p_mark + c_mark)
                ratio = safe_div(straddle_cost, self.spot)
                if ratio is None:
                    continue

                breakeven_pct = ratio * 100.0
                envelope.update(
                    {
                        "event_tenor_dte": int(front_dte),
                        "event_atm_strike": float(candidate_strike),
                        "event_straddle_breakeven_pct": breakeven_pct,
                        "event_implied_expected_move_pct": {
                            "value": breakeven_pct * 0.85,
                            "type": "ILLUSTRATIVE_CONVENTION",
                            "heuristic_factor": 0.85,
                        },
                        "state": "CALCULATED",
                    }
                )
                return envelope

            envelope["event_tenor_dte"] = int(front_dte)
            envelope["state"] = "UNKNOWN"
            envelope["reason"] = f"no_liquid_straddle_within_depth_{self.max_strike_search_depth}"
            return envelope

        except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError) as exc:
            logger.warning("Event straddle calculation error: %s", exc)
            envelope["state"] = "UNKNOWN"
            envelope["reason"] = f"straddle_calculation_failed_{type(exc).__name__}"
            return envelope

    # --------------------------------------------------------------------------
    # STEP 5: TECHNICALS, STRUCTURE & CLASSICAL FLOOR PIVOTS
    # --------------------------------------------------------------------------
    def _calc_step_5(self) -> Dict[str, Any]:
        """Calculates 3-tier Classical Floor Pivots (Pivot, R1-R3, S1-S3) on sorted bars."""
        try:
            df, error = self._clean_and_sort_price_history()
            if df.empty:
                return {
                    "classical_floor_pivots": {
                        "state": "UNKNOWN",
                        "reason": error or "price_history_empty_or_unparseable",
                    }
                }

            latest = df.iloc[-1]
            H = safe_float(latest.get("high"))
            L = safe_float(latest.get("low"))
            C = safe_float(latest.get("close"))

            if H is None or L is None or C is None or H < L:
                return {
                    "classical_floor_pivots": {
                        "state": "UNKNOWN",
                        "reason": "latest_bar_ohlc_invalid_or_inverted",
                    }
                }

            P = (H + L + C) / 3.0
            return {
                "classical_floor_pivots": {
                    "R3": float(H + 2.0 * (P - L)),
                    "R2": float(P + (H - L)),
                    "R1": float((2.0 * P) - L),
                    "Pivot": float(P),
                    "S1": float((2.0 * P) - H),
                    "S2": float(P - (H - L)),
                    "S3": float(L - 2.0 * (H - P)),
                    "state": "CALCULATED",
                }
            }

        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Step 5 calculation error: %s", exc)
            return {
                "classical_floor_pivots": {
                    "state": "UNKNOWN",
                    "reason": f"step_5_execution_failed_{type(exc).__name__}",
                }
            }

    # --------------------------------------------------------------------------
    # INTERNAL DEFENSIVE DATA SANITIZATION
    # --------------------------------------------------------------------------
    def _clean_and_sort_price_history(self) -> Tuple[pd.DataFrame, Optional[str]]:
        """
        Pure function enforcing chronological ordering, future-bar purge, and currency stripping.
        Interface contract assumes US-dollar-denominated series; extend strip set if non-US
        sourcing is introduced.
        Returns a tuple: (clean_df, error_reason_if_empty).
        """
        if self.price_history_df.empty:
            return pd.DataFrame(), "price_history_dataframe_empty"

        df = self.price_history_df.copy()

        time_col = None
        for col_name in ["datetime", "timestamp", "time", "date"]:
            if col_name in df.columns:
                time_col = col_name
                break

        if time_col is None:
            msg = "price_history_has_no_valid_timestamp_column"
            logger.warning("Sanitization failed: %s; rejecting time series.", msg)
            return pd.DataFrame(), msg

        df[time_col] = pd.to_numeric(df[time_col], errors="coerce")
        df = df.dropna(subset=[time_col]).sort_values(time_col, ascending=True)

        current_epoch_ms = int(datetime.now(timezone.utc).timestamp() * 1000.0)
        df = df[df[time_col] <= current_epoch_ms]

        # Defensive Currency & Comma Stripping (DEF-OUT-01 Defense-in-Depth)
        for ohlc in ["open", "high", "low", "close", "volume"]:
            if ohlc in df.columns:
                if df[ohlc].dtype == object:
                    df[ohlc] = (
                        df[ohlc]
                        .astype(str)
                        .str.replace("$", "", regex=False)
                        .str.replace(",", "", regex=False)
                        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
                        .str.strip()
                    )
                df[ohlc] = pd.to_numeric(df[ohlc], errors="coerce")

        required = {"high", "low", "close"}
        if not required.issubset(set(df.columns)):
            return pd.DataFrame(), "price_history_missing_required_ohlc_columns"

        valid_df = df.dropna(subset=list(required))
        if valid_df.empty:
            return pd.DataFrame(), "price_history_contains_only_nan_ohlc_bars"

        return valid_df, None