"""
schwab_marketdata_calculator.py
========================================================================================
Institutional Quantitative Mathematical Derivative & Surface Engine
========================================================================================
Calculates analytical valuation multiples, multi-horizon realized volatilities,
constant-maturity implied volatility surfaces, skew distributions, and event pricing.
Conforms strictly to Institutional Risk & Master Thesis Protocol (v16.20).

Key Mathematical & Architectural Guarantees:
  - PAY-01 / PAY-19: Re-anchors session_gap_pct to (lastPrice - closePrice) / closePrice,
    with explicit unconditional session_gap_anchor tracking ('PRIOR_SESSION_CLOSE_QUOTE'
    vs 'HISTORICAL_BAR_FALLBACK').
  - PAY-02 / PAY-12: Computes 30-Day Constant Maturity Implied Volatility (CMI) via linear
    variance interpolation between front and back ATM expiries; fences vendor metadata.
  - PAY-03 / PAY-11 / PAY-16 / PAY-21: Multi-tiered market_cap_divergence metrics and state
    envelopes (ALIGNED, FLOAT_OR_CLASS_DIFFERENTIAL, DIVERGENT_VINTAGE_OR_SCHEMA,
    SCHEMA_OR_CLASS_SUSPECTED).
  - PAY-05 / PAY-15 / PAY-20: 25-Delta skew engine with strict out-of-the-money moneyness
    validation (K_p < S < K_c) and nearest-symmetric delta/strike fallback.
  - PAY-06 / PAY-13: Scale-invariant cash-flow yield cross-referencing raw PCF inputs.
  - PAY-07 / PAY-17: Practitioner fat-tail adjusted expected move heuristic (0.85x).
  - PAY-09: Payout ratio health distress flag when distribution > 100% of EPS.
  - DEF-01 to DEF-16: Full protocol defect register compliance.
========================================================================================
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("schwab_marketdata_calculator")
logger.addHandler(logging.NullHandler())


def safe_float(val: Any) -> Optional[float]:
    """Defensive scalar float casting with NaN, Inf, and String safety."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (int, float, np.number)):
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(val, str):
        cleaned = val.replace("$", "").replace(",", "").strip()
        try:
            f = float(cleaned)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except (ValueError, TypeError):
            return None
    return None


def safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Guards arithmetic division against zero division and NaN propagation."""
    n = safe_float(num)
    d = safe_float(den)
    if n is None or d is None or abs(d) < 1e-12:
        return None
    res = n / d
    return None if (math.isnan(res) or math.isinf(res)) else res


class MasterThesisCalculator:
    """
    Core institutional analytics engine computing phase-aligned risk derivatives.
    """

    def __init__(
        self,
        raw_payload: Dict[str, Any],
        price_history_df: pd.DataFrame,
        options_df: pd.DataFrame,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.raw_payload = raw_payload or {}
        self.params = params or {}

        # Upstream Parameter Config
        self.trading_days_per_year = safe_float(self.params.get("TRADING_DAYS_PER_YEAR")) or 252.0
        self.min_delta_tolerance = safe_float(self.params.get("MIN_DELTA_TOLERANCE")) or 0.20
        self.max_delta_tolerance = safe_float(self.params.get("MAX_DELTA_TOLERANCE")) or 0.30
        self.max_30d_dte_tolerance = int(self.params.get("MAX_30D_DTE_TOLERANCE", 7))
        self.max_event_dte_tolerance = int(self.params.get("MAX_EVENT_DTE_TOLERANCE", 14))
        self.max_strike_search_depth = int(self.params.get("MAX_STRIKE_SEARCH_DEPTH", 2))
        self.max_relative_spread = safe_float(self.params.get("MAX_RELATIVE_SPREAD")) or 0.25

        # Clean Price History
        self.price_history_df, self.ph_clean_error = self._clean_and_sort_price_history(price_history_df)
        self.options_df = self._clean_options_df(options_df)

        # Architectural Dual-Spot Segregation
        phase_0 = self.raw_payload.get("phase_0_grounding", {})
        surface_params = (
            self.raw_payload.get("step_3_and_7_derivatives", {}).get("surface_parameters", {})
        )

        self.grounding_spot = safe_float(phase_0.get("lastPrice")) or safe_float(phase_0.get("closePrice"))

        raw_opt_spot = safe_float(surface_params.get("underlyingPrice"))
        if raw_opt_spot is not None and raw_opt_spot > 0.0:
            self.derivatives_spot = raw_opt_spot
            self.spot_provenance = {
                "source": "options_payload_underlyingPrice",
                "vintage_risk": "LOW",
                "reason": "payload_embedded_underlying_price",
            }
        elif self.grounding_spot is not None and self.grounding_spot > 0.0:
            self.derivatives_spot = self.grounding_spot
            self.spot_provenance = {
                "source": "phase_0_grounding_lastPrice",
                "vintage_risk": "MEDIUM",
                "reason": "fallback_to_phase_0_grounding",
            }
        else:
            self.derivatives_spot = None
            self.spot_provenance = {
                "source": "UNAVAILABLE",
                "vintage_risk": "HIGH",
                "reason": "zero_or_missing_spot_sources",
            }

    def _clean_and_sort_price_history(
        self, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, Optional[str]]:
        if df is None or df.empty:
            return pd.DataFrame(), "price_history_empty"

        time_cols = [c for c in ["datetime", "epoch", "time", "date"] if c in df.columns]
        if not time_cols:
            return pd.DataFrame(), "price_history_has_no_valid_timestamp_column"

        time_col = time_cols[0]
        work_df = df.copy()

        for col in ["open", "high", "low", "close", "volume"]:
            if col in work_df.columns:
                if work_df[col].dtype == object:
                    work_df[col] = (
                        work_df[col]
                        .astype(str)
                        .str.replace("$", "", regex=False)
                        .str.replace(",", "", regex=False)
                        .str.strip()
                    )
                work_df[col] = pd.to_numeric(work_df[col], errors="coerce")

        work_df[time_col] = pd.to_numeric(work_df[time_col], errors="coerce")
        work_df = work_df.dropna(subset=[time_col]).sort_values(by=time_col, ascending=True)

        now_ms = datetime.now(timezone.utc).timestamp() * 1000.0
        work_df = work_df[work_df[time_col] <= (now_ms + 86400000.0)]

        valid_df = work_df.dropna(subset=["high", "low", "close"])
        if valid_df.empty:
            return pd.DataFrame(), "price_history_contains_only_nan_ohlc_bars"

        return valid_df, None

    def _clean_options_df(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        work_df = df.copy()
        numeric_cols = [
            "strikePrice", "daysToExpiration", "bid", "ask", "mark",
            "volatility", "delta", "totalVolume", "openInterest"
        ]
        for c in numeric_cols:
            if c in work_df.columns:
                work_df[c] = pd.to_numeric(work_df[c], errors="coerce")
        return work_df

    def calculate_metrics(self) -> Dict[str, Any]:
        """Calculates all phase-aligned institutional metrics."""
        return {
            "step_0_grounding": self._calc_step_0(),
            "step_1_fundamentals_and_quality": self._calc_step_1(),
            "step_3_and_7_derivatives_and_surface": self._calc_step_3_and_7(),
            "step_5_technicals_and_flows": self._calc_step_5(),
        }

    def _calc_step_0(self) -> Dict[str, Any]:
        """PAY-01 & PAY-19: Discloses session gap anchored to prior close quote."""
        try:
            phase_0 = self.raw_payload.get("phase_0_grounding", {})
            last_p = safe_float(phase_0.get("lastPrice"))
            close_p = safe_float(phase_0.get("closePrice"))

            if last_p is not None and close_p is not None and close_p > 0.0:
                gap = ((last_p - close_p) / close_p) * 100.0
                return {
                    "session_gap_pct": {
                        "value": round(gap, 2),
                        "state": "CALCULATED",
                        "session_gap_anchor": "PRIOR_SESSION_CLOSE_QUOTE",
                    }
                }

            # Fallback path across sorted historical candles
            if not self.price_history_df.empty and len(self.price_history_df) >= 2:
                hist_close = safe_float(self.price_history_df.iloc[-2]["close"])
                hist_last = safe_float(self.price_history_df.iloc[-1]["close"])
                if hist_close is not None and hist_close > 0.0 and hist_last is not None:
                    gap = ((hist_last - hist_close) / hist_close) * 100.0
                    return {
                        "session_gap_pct": {
                            "value": round(gap, 2),
                            "state": "CALCULATED",
                            "session_gap_anchor": "HISTORICAL_BAR_FALLBACK",
                        }
                    }

            return {
                "session_gap_pct": {
                    "state": "UNKNOWN",
                    "reason": "insufficient_grounding_quote_or_historical_bars",
                }
            }
        except Exception as exc:
            return {"session_gap_pct": {"state": "UNKNOWN", "reason": f"calculation_exception_{type(exc).__name__}"}}

    def _calc_step_1(self) -> Dict[str, Any]:
        """
        Step 1 Fundamentals: Valuation denominator safety, market cap divergence, and equity imputation.
        """
        try:
            f = self.raw_payload.get("step_1_fundamentals", {})
            pe = safe_float(f.get("peRatio"))
            eps = safe_float(f.get("eps"))
            pb = safe_float(f.get("pbRatio"))
            pcf = safe_float(f.get("pcfRatio"))
            shares_out = safe_float(f.get("sharesOutstanding"))
            reported_mcap = safe_float(f.get("marketCap"))
            div_amount = safe_float(f.get("divAmount"))
            div_freq = safe_float(f.get("divFreq")) or 4.0
            div_yield_basis = f.get("divYield_basis")

            res: Dict[str, Any] = {}

            # 1. Earnings Yield
            if pe is not None and pe > 0.0 and (eps is None or eps > 0.0):
                res["earnings_yield_pct"] = round((1.0 / pe) * 100.0, 2)
            else:
                res["earnings_yield_pct"] = {
                    "state": "N/A",
                    "reason": "earnings_negative_or_unstable_pe_ratio_non_positive",
                    "underlying_pe_ratio": pe,
                    "underlying_eps": eps,
                }

            # 2. Imputed Dividend Payout Ratio & Capital Impairment Flag (PAY-09)
            if eps is not None and eps > 0.0 and div_amount is not None:
                # Annualize dividend unless already confirmed annual
                annual_div = div_amount if div_yield_basis == "DIRECT_CONFIRMED" else (div_amount * div_freq)
                payout = (annual_div / eps) * 100.0
                res["imputed_dividend_payout_ratio_pct"] = round(payout, 2)
                if payout > 100.0:
                    res["payout_ratio_exceeds_earnings"] = True
                    res["payout_ratio_health"] = "CAPITAL_IMPAIRMENT_RISK"
                else:
                    res["payout_ratio_exceeds_earnings"] = False
                    res["payout_ratio_health"] = "SUSTAINABLE"
            else:
                res["imputed_dividend_payout_ratio_pct"] = {
                    "state": "UNKNOWN",
                    "reason": "missing_dividend_or_eps_data",
                }

            # 3. CFO Yield & CFO Per Share (PAY-06 / PAY-13)
            res["pcf_ratio_raw"] = pcf
            res["cfo_per_share"] = {
                "state": "UNKNOWN",
                "reason": "pcf_ratio_denominator_dimension_unverified",
                "pcf_ratio_raw": pcf,
            }
            if pcf is not None and pcf > 0.0:
                res["cfo_yield_pct"] = round((1.0 / pcf) * 100.0, 2)
                res["cfo_yield_derivation_basis"] = "inverse_pcf_ratio_scale_invariant"
            else:
                res["cfo_yield_pct"] = {"state": "UNKNOWN", "reason": "non_positive_or_missing_pcf_ratio"}

            # 4. Market Cap Divergence & Imputed Book Value (PAY-03 / PAY-11 / PAY-16 / PAY-21)
            derived_mcap = None
            if self.grounding_spot is not None and self.grounding_spot > 0.0 and shares_out is not None and shares_out > 0.0:
                derived_mcap = self.grounding_spot * shares_out

            res["derived_market_cap"] = derived_mcap
            res["reported_market_cap"] = reported_mcap

            if derived_mcap is not None and reported_mcap is not None and reported_mcap > 0.0:
                diff_abs = abs(derived_mcap - reported_mcap)
                diff_pct = (diff_abs / reported_mcap) * 100.0
                res["market_cap_divergence_abs_usd"] = round(diff_abs, 2)
                res["market_cap_divergence_pct"] = round(diff_pct, 4)

                # PAY-21: 4-Tier Divergence Classification with Mega-Cap Materiality Check
                if diff_pct <= 0.50:
                    div_state = "ALIGNED"
                elif diff_pct <= 5.0:
                    div_state = "FLOAT_OR_CLASS_DIFFERENTIAL"
                elif diff_pct > 5.0 and diff_abs > 5_000_000_000.0:
                    div_state = "SCHEMA_OR_CLASS_SUSPECTED"
                else:
                    div_state = "DIVERGENT_VINTAGE_OR_SCHEMA"
                res["market_cap_divergence_state"] = div_state
            else:
                res["market_cap_divergence_state"] = "UNVERIFIED_COMPONENTS"

            # Imputed Book Value of Equity
            if derived_mcap is not None and pb is not None and pb > 0.0:
                res["imputed_book_value_of_equity"] = round(derived_mcap / pb, 2)
            else:
                res["imputed_book_value_of_equity"] = {
                    "state": "UNKNOWN",
                    "reason": "market_cap_requires_verified_components",
                }

            # 5. Imputed Total Debt
            raw_dte = safe_float(f.get("totalDebtToEquity"))
            dte_unit = self.params.get("TOTAL_DEBT_TO_EQUITY_UNIT")
            if dte_unit in ["PERCENTAGE", "RATIO"] and raw_dte is not None and isinstance(res.get("imputed_book_value_of_equity"), (int, float)):
                bv = float(res["imputed_book_value_of_equity"])
                scale = 0.01 if dte_unit == "PERCENTAGE" else 1.0
                res["imputed_total_debt"] = round(bv * raw_dte * scale, 2)
            else:
                res["imputed_total_debt"] = {
                    "state": "UNKNOWN",
                    "reason": "total_debt_to_equity_unit_unverified_scale_risk",
                    "underlying_totalDebtToEquity": raw_dte,
                }

            res["grounding_spot_used"] = self.grounding_spot
            res["state"] = "CALCULATED"
            return res
        except Exception as exc:
            return {"state": "UNKNOWN", "reason": f"step_1_execution_failed_{type(exc).__name__}"}

    def _calc_step_3_and_7(self) -> Dict[str, Any]:
        """Derivatives and surface models: Realized Volatilities, Skew, and Event Pricing."""
        res: Dict[str, Any] = {
            "spot_provenance": self.spot_provenance,
            "realized_volatility": self._calc_realized_volatilities(),
            "flow_ratios": self._calc_volume_and_oi_ratios(),
            "skew_30d": self._calc_30d_skew(),
            "event_implied_move": self._calc_atm_event_straddle(),
        }

        # PAY-02 / PAY-12: Constant Maturity ATM Implied Volatility Surface Computation
        cmi_30d, cmi_reason = self._compute_atm_cmi_30d()
        if cmi_30d is not None:
            res["constant_maturity_30d_atm_iv"] = round(cmi_30d, 2)
            res["constant_maturity_30d_state"] = "CALCULATED"
        else:
            res["constant_maturity_30d_atm_iv"] = None
            res["constant_maturity_30d_state"] = "UNKNOWN"
            res["constant_maturity_30d_reason"] = cmi_reason

        return res

    def _compute_atm_cmi_30d(self) -> Tuple[Optional[float], Optional[str]]:
        """PAY-02 / PAY-12: Linearly interpolates variance across front and back expiries to evaluate 30D CMI."""
        if self.options_df.empty or self.derivatives_spot is None:
            return None, "empty_options_chain_or_unresolved_spot"

        df = self.options_df[self.options_df["daysToExpiration"] > 0]
        if df.empty:
            return None, "no_positive_dte_options_available"

        dtes = np.sort(df["daysToExpiration"].unique())
        front_dtes = dtes[dtes <= 30]
        back_dtes = dtes[dtes >= 30]

        if len(front_dtes) == 0 or len(back_dtes) == 0:
            return None, "cannot_bracket_30d_tenor_for_cmi_interpolation"

        t1 = front_dtes[-1]
        t2 = back_dtes[0]

        def get_atm_iv(target_dte: int) -> Optional[float]:
            sub = df[df["daysToExpiration"] == target_dte].copy()
            if sub.empty:
                return None
            sub["dist"] = (sub["strikePrice"] - self.derivatives_spot).abs()
            nearest = sub.sort_values("dist").iloc[0]
            return safe_float(nearest.get("volatility"))

        iv1 = get_atm_iv(int(t1))
        iv2 = get_atm_iv(int(t2))

        if iv1 is None or iv2 is None:
            return None, "atm_iv_unpopulated_on_bracking_tenors"

        if t1 == t2:
            return iv1, None

        # Linear total variance interpolation
        var1 = (iv1 ** 2) * (t1 / 365.0)
        var2 = (iv2 ** 2) * (t2 / 365.0)
        w = (30.0 - t1) / (t2 - t1)
        var_30d = var1 + w * (var2 - var1)
        if var_30d < 0:
            return None, "negative_interpolated_variance"

        cmi_vol = math.sqrt(var_30d * (365.0 / 30.0))
        return cmi_vol, None

    def _calc_realized_volatilities(self) -> Dict[str, Any]:
        """Calculates 10D, 21D, and 252D Close-to-Close, Parkinson, and Garman-Klass RV."""
        windows = {
            "10d_tactical": 10,
            "21d_tenor_match": 21,
            "252d_macro": 252,
        }
        results: Dict[str, Any] = {}

        if self.price_history_df.empty or len(self.price_history_df) < 5:
            for label in windows:
                results[label] = {
                    "sample_bars": None,
                    "return_observations": None,
                    "close_to_close": None,
                    "parkinson": None,
                    "garman_klass": None,
                    "estimator_methodology": "Zero-Drift Continuous GK Variant",
                    "state": "UNKNOWN",
                    "reason": self.ph_clean_error or "insufficient_historical_bars",
                }
            return results

        df = self.price_history_df
        sqrt_ann = math.sqrt(self.trading_days_per_year)

        for label, win in windows.items():
            sub = df.tail(win).copy()
            n_bars = len(sub)
            n_returns = n_bars - 1

            if n_bars < min(win, 5):
                results[label] = {
                    "sample_bars": n_bars,
                    "return_observations": n_returns,
                    "state": "UNKNOWN",
                    "reason": f"insufficient_bars_for_window_{win}",
                }
                continue

            try:
                # 1. Close-to-Close
                log_rets = np.log(sub["close"] / sub["close"].shift(1)).dropna()
                c2c = float(log_rets.std(ddof=1) * sqrt_ann * 100.0)

                # 2. Parkinson
                hl_ratio = np.log(sub["high"] / sub["low"])
                park = float(math.sqrt((1.0 / (4.0 * math.log(2.0))) * (hl_ratio ** 2).mean()) * sqrt_ann * 100.0)

                # 3. Garman-Klass (Zero-Drift Continuous)
                co_ratio = np.log(sub["close"] / sub["open"])
                gk_term = 0.5 * (hl_ratio ** 2) - (2.0 * math.log(2.0) - 1.0) * (co_ratio ** 2)
                gk = float(math.sqrt(gk_term.mean()) * sqrt_ann * 100.0)

                results[label] = {
                    "sample_bars": n_bars,
                    "return_observations": n_returns,
                    "close_to_close": round(c2c, 2),
                    "parkinson": round(park, 2),
                    "garman_klass": round(gk, 2),
                    "estimator_methodology": "Zero-Drift Continuous GK Variant",
                    "state": "CALCULATED",
                }
            except Exception as exc:
                results[label] = {
                    "sample_bars": n_bars,
                    "return_observations": n_returns,
                    "state": "UNKNOWN",
                    "reason": f"rv_estimation_exception_{type(exc).__name__}",
                }

        return results

    def _calc_volume_and_oi_ratios(self) -> Dict[str, Any]:
        """Calculates Put/Call volume and open interest flow ratios."""
        if self.options_df.empty or not {"putCallIndicator", "totalVolume", "openInterest"}.issubset(self.options_df.columns):
            return {
                "put_call_volume_ratio": None,
                "put_call_open_interest_ratio": None,
                "state": "UNKNOWN",
                "reason": "options_chain_missing_required_flow_columns",
            }

        puts = self.options_df[self.options_df["putCallIndicator"].str.upper() == "PUT"]
        calls = self.options_df[self.options_df["putCallIndicator"].str.upper() == "CALL"]

        p_vol = puts["totalVolume"].sum(skipna=True)
        c_vol = calls["totalVolume"].sum(skipna=True)
        p_oi = puts["openInterest"].sum(skipna=True)
        c_oi = calls["openInterest"].sum(skipna=True)

        pcr_v = safe_div(p_vol, c_vol)
        pcr_oi = safe_div(p_oi, c_oi)

        res: Dict[str, Any] = {
            "put_call_volume_ratio": round(pcr_v, 2) if pcr_v is not None else None,
            "put_call_open_interest_ratio": round(pcr_oi, 2) if pcr_oi is not None else None,
        }

        if pcr_v is not None and pcr_oi is not None:
            res["state"] = "CALCULATED"
        elif pcr_v is not None or pcr_oi is not None:
            res["state"] = "PARTIAL"
        else:
            res["state"] = "UNKNOWN"
            res["reason"] = "zero_call_volume_and_open_interest_denominators"

        return res

    def _calc_30d_skew(self) -> Dict[str, Any]:
        """
        PAY-05 / PAY-15 / PAY-20: Evaluates 30D Skew with strict OTM moneyness and nearest-symmetric fallback.
        """
        res: Dict[str, Any] = {
            "skew_tenor_dte": None,
            "skew_30d_iv_differential": None,
            "skew_30d_normalized_ratio": None,
            "skew_actual_put_delta": None,
            "skew_actual_call_delta": None,
            "state": "UNKNOWN",
        }

        if self.options_df.empty or self.derivatives_spot is None:
            res["reason"] = "empty_options_chain_or_unresolved_spot"
            return res

        df = self.options_df[self.options_df["daysToExpiration"] > 0]
        if df.empty:
            res["reason"] = "no_positive_dte_options"
            return res

        dtes = df["daysToExpiration"].unique()
        valid_dtes = [d for d in dtes if abs(d - 30) <= self.max_30d_dte_tolerance]
        if not valid_dtes:
            res["reason"] = f"no_expiration_within_30d_tolerance_window_{self.max_30d_dte_tolerance}"
            return res

        chosen_dte = int(min(valid_dtes, key=lambda d: abs(d - 30)))
        res["skew_tenor_dte"] = chosen_dte

        chain = df[df["daysToExpiration"] == chosen_dte].copy()
        spot = self.derivatives_spot

        # PAY-05: Enforce strict OTM Moneyness
        puts = chain[(chain["putCallIndicator"].str.upper() == "PUT") & (chain["strikePrice"] < spot)].copy()
        calls = chain[(chain["putCallIndicator"].str.upper() == "CALL") & (chain["strikePrice"] > spot)].copy()

        if puts.empty or calls.empty:
            res["reason"] = "insufficient_otm_contracts_on_target_tenor"
            return res

        puts["abs_delta"] = puts["delta"].abs()
        calls["abs_delta"] = calls["delta"].abs()

        # Primary Search Gate: 0.20 <= |delta| <= 0.30
        in_band_puts = puts[(puts["abs_delta"] >= self.min_delta_tolerance) & (puts["abs_delta"] <= self.max_delta_tolerance)]
        in_band_calls = calls[(calls["abs_delta"] >= self.min_delta_tolerance) & (calls["abs_delta"] <= self.max_delta_tolerance)]

        best_put = None
        best_call = None
        anchor_type = "PRIMARY_25D_SYMMETRIC"

        if not in_band_puts.empty and not in_band_calls.empty:
            # Optimize for symmetric delta proximity to 0.25
            best_pair = None
            min_score = float("inf")
            for _, p in in_band_puts.iterrows():
                for _, c in in_band_calls.iterrows():
                    d_p = float(p["abs_delta"])
                    d_c = float(c["abs_delta"])
                    score = (d_p - d_c) ** 2 + ((d_p + d_c) / 2.0 - 0.25) ** 2
                    if score < min_score:
                        min_score = score
                        best_pair = (p, c)
            if best_pair:
                best_put, best_call = best_pair
        else:
            # PAY-15 & PAY-20: Nearest-Symmetric Fallback with Strike Symmetry Regularizer
            anchor_type = "FALLBACK_NEAREST_SYMMETRIC"
            exp_puts = puts[(puts["abs_delta"] >= 0.15) & (puts["abs_delta"] <= 0.45)]
            exp_calls = calls[(calls["abs_delta"] >= 0.15) & (calls["abs_delta"] <= 0.45)]

            if not exp_puts.empty and not exp_calls.empty:
                best_pair = None
                min_score = float("inf")
                for _, p in exp_puts.iterrows():
                    for _, c in exp_calls.iterrows():
                        d_p = float(p["abs_delta"])
                        d_c = float(c["abs_delta"])
                        k_p = float(p["strikePrice"])
                        k_c = float(c["strikePrice"])
                        # Delta symmetry + proximity to 0.25 + strike symmetry regularizer (lambda = 0.01)
                        score = (d_p - d_c) ** 2 + ((d_p + d_c) / 2.0 - 0.25) ** 2 + 0.01 * (((spot - k_p) - (k_c - spot)) / spot) ** 2
                        if score < min_score:
                            min_score = score
                            best_pair = (p, c)
                if best_pair:
                    best_put, best_call = best_pair

        if best_put is None or best_call is None:
            observed_p = float(puts["abs_delta"].min()) if not puts.empty else None
            observed_c = float(calls["abs_delta"].min()) if not calls.empty else None
            res["reason"] = f"observed_deltas_[{observed_p},{observed_c}]_outside_tolerance_[{self.min_delta_tolerance},{self.max_delta_tolerance}]"
            res["skew_actual_put_delta"] = observed_p
            res["skew_actual_call_delta"] = observed_c
            return res

        put_iv = safe_float(best_put.get("volatility"))
        call_iv = safe_float(best_call.get("volatility"))

        if put_iv is not None and call_iv is not None:
            diff = put_iv - call_iv
            ratio = safe_div(put_iv, call_iv)
            res["skew_30d_iv_differential"] = round(diff, 2)
            res["skew_30d_normalized_ratio"] = round(ratio, 2) if ratio else None
            res["skew_actual_put_delta"] = round(float(best_put["abs_delta"]), 2)
            res["skew_actual_call_delta"] = round(float(best_call["abs_delta"]), 2)
            res["skew_delta_anchor"] = anchor_type
            res["state"] = "CALCULATED"
        else:
            res["reason"] = "unpopulated_volatility_on_skew_wings"

        return res

    def _calc_atm_event_straddle(self) -> Dict[str, Any]:
        """
        Calculates ATM Event Straddle pricing and expected move convention (PAY-07 / PAY-17).
        """
        res: Dict[str, Any] = {
            "event_tenor_dte": None,
            "event_atm_strike": None,
            "event_straddle_breakeven_pct": None,
            "event_implied_expected_move_pct": None,
            "state": "UNKNOWN",
        }

        if self.options_df.empty or self.derivatives_spot is None:
            res["reason"] = "empty_options_chain_or_unresolved_spot"
            return res

        df = self.options_df[self.options_df["daysToExpiration"] >= 1].copy()
        if df.empty:
            res["reason"] = "only_0dte_expiration_available_insufficient_for_event_straddle"
            return res

        dtes = df["daysToExpiration"].unique()
        valid_dtes = [d for d in dtes if d <= self.max_event_dte_tolerance]
        if not valid_dtes:
            res["reason"] = f"no_liquid_expiration_within_event_window_1_to_{self.max_event_dte_tolerance}"
            return res

        event_dte = int(min(valid_dtes))
        res["event_tenor_dte"] = event_dte

        chain = df[df["daysToExpiration"] == event_dte].copy()
        spot = self.derivatives_spot

        # Bounded Strike Search around Spot
        strikes = np.sort(chain["strikePrice"].unique())
        atm_strike = float(min(strikes, key=lambda s: abs(s - spot)))
        res["event_atm_strike"] = atm_strike

        atm_c = chain[(chain["strikePrice"] == atm_strike) & (chain["putCallIndicator"].str.upper() == "CALL")]
        atm_p = chain[(chain["strikePrice"] == atm_strike) & (chain["putCallIndicator"].str.upper() == "PUT")]

        if atm_c.empty or atm_p.empty:
            res["reason"] = "missing_call_or_put_at_atm_strike"
            return res

        c_row = atm_c.iloc[0]
        p_row = atm_p.iloc[0]

        c_mark = safe_float(c_row.get("mark"))
        p_mark = safe_float(p_row.get("mark"))
        c_bid = safe_float(c_row.get("bid"))
        p_bid = safe_float(p_row.get("bid"))
        c_ask = safe_float(c_row.get("ask"))
        p_ask = safe_float(p_row.get("ask"))

        # Liquidity and Relative Spread Validation
        if any(x is None or x <= 0.0 for x in [c_mark, p_mark, c_bid, p_bid]):
            res["reason"] = "no_liquid_straddle_within_depth_2"
            return res

        c_spread = (c_ask - c_bid) / c_mark if (c_ask and c_bid and c_mark) else 1.0
        p_spread = (p_ask - p_bid) / p_mark if (p_ask and p_bid and p_mark) else 1.0

        if c_spread > self.max_relative_spread or p_spread > self.max_relative_spread:
            res["reason"] = f"bid_ask_spread_exceeds_tolerance_{self.max_relative_spread}"
            return res

        straddle_cost = c_mark + p_mark
        be_pct = (straddle_cost / spot) * 100.0
        res["event_straddle_breakeven_pct"] = round(be_pct, 2)

        # PAY-07 & PAY-17: Practitioner Convention Tagging
        res["event_implied_expected_move_pct"] = {
            "value": round(be_pct * 0.85, 2),
            "type": "ILLUSTRATIVE_CONVENTION",
            "heuristic_factor": 0.85,
            "heuristic_anchor": "PRACTITIONER_FAT_TAIL_ADJUSTED_CONVENTION",
            "reference_derivation": "breakeven_cost_scaled_by_expected_absolute_move_factor",
        }
        res["state"] = "CALCULATED"
        return res

    def _calc_step_5(self) -> Dict[str, Any]:
        """Calculates Classical Floor Pivots from the latest historical daily candle."""
        if self.price_history_df.empty or len(self.price_history_df) < 1:
            return {"classical_floor_pivots": {"state": "UNKNOWN", "reason": "price_history_empty"}}

        latest = self.price_history_df.iloc[-1]
        h = safe_float(latest.get("high"))
        l = safe_float(latest.get("low"))
        c = safe_float(latest.get("close"))

        if any(x is None or x <= 0.0 for x in [h, l, c]):
            return {"classical_floor_pivots": {"state": "UNKNOWN", "reason": "invalid_latest_candle_ohlc"}}

        p = (h + l + c) / 3.0
        r1 = (2.0 * p) - l
        s1 = (2.0 * p) - h
        r2 = p + (h - l)
        s2 = p - (h - l)
        r3 = h + 2.0 * (p - l)
        s3 = l - 2.0 * (h - p)

        return {
            "classical_floor_pivots": {
                "R3": round(r3, 2),
                "R2": round(r2, 2),
                "R1": round(r1, 2),
                "Pivot": round(p, 2),
                "S1": round(s1, 2),
                "S2": round(s2, 2),
                "S3": round(s3, 2),
                "state": "CALCULATED",
            }
        }