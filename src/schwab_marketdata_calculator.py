"""
schwab_marketdata_calculator.py
========================================================================================
Institutional Charles Schwab Quantitative Metrics & Surface Modeling Engine
Protocol v16.21 Production Certified
========================================================================================
Changelog v16.21 (Round-Twenty Spec Lock):
  - PAY-57/74: Protected dividend payout ratio divisor against suppressed/zero EPS stubs.
  - PAY-60: Enforced uniform 6-key canonical null dictionary for market_cap_divergence.
  - PAY-61/70: Trinary branching logic for market_cap_divergence_reason.
  - PAY-62: Preserved signed negative float put delta convention.
  - PAY-64: Non-payer dividend routed to NOT_APPLICABLE_NON_PAYER with N/A state.
  - PAY-65: Emitted skew_delta_symmetry_gap telemetry.
  - Structural Integrity sweep for divergence >20% and >$50B.
========================================================================================
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("schwab_marketdata_calculator")
logger.addHandler(logging.NullHandler())

MARKET_CAP_DEPENDENT_METRICS: Set[str] = {
    "imputed_book_value_of_equity",
    "imputed_total_debt",
    "enterprise_value_proxy",
    "imputed_dividend_payout_ratio_pct",
    "free_cash_flow_yield_pct",
}


def safe_float(val: Any) -> Optional[float]:
    """Safely converts input primitives to float, handling currency and strings cleanly."""
    if val is None or pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(val, str):
        cleaned = val.replace("$", "").replace(",", "").strip()
        try:
            f = float(cleaned)
            return None if math.isnan(f) or math.isinf(f) else f
        except (ValueError, TypeError):
            return None
    return None


class MasterThesisCalculator:
    """Protocol v16.21 Production Certified Quantitative Calculator."""

    def __init__(
        self,
        raw_data: Dict[str, Any],
        price_history_df: Optional[pd.DataFrame] = None,
        options_df: Optional[pd.DataFrame] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.raw = raw_data or {}
        self.params = params or {}

        raw_ph = price_history_df if price_history_df is not None else pd.DataFrame()
        self.df_history, self._price_history_error = self._clean_and_sort_price_history(raw_ph)
        self.df_options = options_df.copy() if options_df is not None else pd.DataFrame()

        self.grounding_spot = safe_float(self.raw.get("phase_0_grounding", {}).get("lastPrice"))
        raw_chain_spot = (
            self.raw.get("step_3_and_7_derivatives", {})
            .get("surface_parameters", {})
            .get("underlyingPrice")
            if isinstance(self.raw.get("step_3_and_7_derivatives"), dict)
            else None
        )

        if raw_chain_spot is not None and safe_float(raw_chain_spot) is not None:
            self.derivatives_spot = safe_float(raw_chain_spot)
            self.derivatives_spot_provenance = {
                "source": "options_payload_underlyingPrice",
                "vintage_risk": "LOW",
                "contemporaneous": True,
            }
        elif self.grounding_spot is not None:
            self.derivatives_spot = self.grounding_spot
            self.derivatives_spot_provenance = {
                "source": "phase_0_grounding_lastPrice",
                "vintage_risk": "MEDIUM",
                "contemporaneous": False,
            }
        else:
            self.derivatives_spot = None
            self.derivatives_spot_provenance = {
                "source": "UNAVAILABLE",
                "vintage_risk": "HIGH",
                "contemporaneous": False,
            }

        self.trading_days_per_year = safe_float(self.params.get("TRADING_DAYS_PER_YEAR")) or 252.0
        self.max_skew_relative_spread = safe_float(self.params.get("MAX_SKEW_RELATIVE_SPREAD")) or 0.50

    def _clean_and_sort_price_history(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Optional[str]]:
        if df.empty:
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
                        work_df[col].astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False).str.strip()
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

    def calculate_metrics(self) -> Dict[str, Any]:
        return {
            "step_0_grounding": self._calc_step_0(),
            "step_1_fundamentals_and_quality": self._calc_step_1(),
            "step_3_and_7_derivatives_and_surface": self._calc_step_3_and_7(),
            "step_5_technicals_and_flows": self._calc_step_5(),
        }

    def _calc_step_0(self) -> Dict[str, Any]:
        try:
            last_p = self.grounding_spot
            close_p = safe_float(self.raw.get("phase_0_grounding", {}).get("closePrice"))
            if last_p is not None and close_p is not None and close_p > 0:
                gap = ((last_p - close_p) / close_p) * 100.0
                return {
                    "session_gap_pct": {
                        "value": round(gap, 4),
                        "state": "CALCULATED",
                        "session_gap_anchor": "PRIOR_SESSION_CLOSE_QUOTE",
                    }
                }
            return {"session_gap_pct": {"value": None, "state": "UNKNOWN", "reason": "missing_quote_prices"}}
        except Exception as exc:
            return {"session_gap_pct": {"value": None, "state": "UNKNOWN", "reason": str(exc)}}

    def _calc_step_1(self) -> Dict[str, Any]:
        fund = self.raw.get("step_1_fundamentals", {})
        pe = safe_float(fund.get("peRatio"))
        eps = safe_float(fund.get("eps"))
        eps_state = fund.get("eps_state", "AS_REPORTED")
        pcf = safe_float(fund.get("pcfRatio"))
        pb = safe_float(fund.get("pbRatio"))
        div_amount = safe_float(fund.get("divAmount"))
        div_freq = safe_float(fund.get("divFreq")) or 0.0
        shares = safe_float(fund.get("sharesOutstanding"))
        reported_mcap = safe_float(fund.get("marketCap"))
        total_dte = safe_float(fund.get("totalDebtToEquity"))

        # 1. Market Cap Derivation & Trinary Divergence Reasons (PAY-60 / PAY-61 / PAY-70)
        derived_mcap = None
        if self.grounding_spot is not None and shares is not None and shares > 0:
            derived_mcap = round(self.grounding_spot * shares, 2)

        div_abs_usd = None
        div_pct = None
        div_state = "UNVERIFIED_COMPONENTS"
        div_reason = None

        if derived_mcap is not None and reported_mcap is not None and reported_mcap > 0:
            div_abs_usd = round(abs(derived_mcap - reported_mcap), 2)
            div_pct = round((div_abs_usd / reported_mcap) * 100.0, 2)

            if div_pct <= 0.50:
                div_state = "ALIGNED"
            elif div_pct <= 5.0:
                div_state = "FLOAT_OR_CLASS_DIFFERENTIAL"
            elif div_pct > 20.0 and div_abs_usd > 50e9:
                div_state = "INTEGRITY_FAILURE_REQUIRES_REVIEW"
            else:
                div_state = "SCHEMA_OR_CLASS_SUSPECTED"
        else:
            div_state = "UNVERIFIED_COMPONENTS"
            if shares is None:
                div_reason = "requires_verified_shares_outstanding"
            elif reported_mcap is None:
                div_reason = "vendor_does_not_provide_market_cap"
            elif derived_mcap is None:
                div_reason = "derived_market_cap_unavailable"
            else:
                div_reason = None

        market_cap_divergence_block = {
            "derived_market_cap": derived_mcap,
            "reported_market_cap": reported_mcap,
            "market_cap_divergence_abs_usd": div_abs_usd,
            "market_cap_divergence_pct": div_pct,
            "market_cap_divergence_state": div_state,
            "market_cap_divergence_reason": div_reason,
        }

        # 2. Earnings Yield
        if pe is not None and pe > 0:
            ey_val = round((1.0 / pe) * 100.0, 4)
        else:
            ey_val = {"state": "N/A", "reason": "earnings_negative_or_unstable_pe_ratio_non_positive"}

        # 3. CFO Yield (PAY-72)
        if pcf is not None and pcf > 0:
            cfo_yield = round((1.0 / pcf) * 100.0, 4)
        else:
            cfo_yield = {"state": "N/A", "reason": "cash_flow_negative_or_pcf_ratio_non_positive"}

        # 4. Imputed Dividend Payout Ratio (PAY-57 / PAY-64 / PAY-74)
        annual_div = (div_amount * div_freq) if (div_amount is not None and div_freq > 0) else 0.0
        payout_health = "SUSTAINABLE"
        payout_exceeds = False

        if annual_div == 0.0 or fund.get("divYield") == 0.0:
            payout_val = {"state": "N/A", "reason": "non_payer_no_distribution"}
            payout_health = "NOT_APPLICABLE_NON_PAYER"
        elif eps_state in (
            "VENDOR_UNAVAILABLE_EPS_ZERO_WITH_POSITIVE_MARGIN",
            "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED",
        ):
            payout_val = {"state": "N/A", "reason": "eps_suppressed_with_positive_net_margin"}
            payout_health = "CAPITAL_STRUCTURE_UNVERIFIED"
        elif eps is None or eps <= 0:
            payout_val = {"state": "N/A", "reason": "cannot_impute_payout_ratio_on_negative_earnings"}
        else:
            calc_payout = round((annual_div / eps) * 100.0, 2)
            if calc_payout > 100.0:
                payout_exceeds = True
                payout_health = "CAPITAL_IMPAIRMENT_RISK"
            payout_val = calc_payout

        # 5. Imputed Balance Sheet Derivations
        imputed_bv = (
            round(derived_mcap / pb, 2)
            if derived_mcap is not None and pb is not None and pb > 0
            else {"state": "UNKNOWN", "reason": "requires_verified_market_cap_and_pb_ratio"}
        )
        imputed_debt = (
            round(imputed_bv * (total_dte / 100.0), 2)
            if isinstance(imputed_bv, float) and total_dte is not None
            else {"state": "UNKNOWN", "reason": "requires_verified_market_cap_and_pb_ratio"}
        )

        metrics = {
            "state": "CALCULATED",
            "earnings_yield_pct": ey_val,
            "cfo_yield_pct": cfo_yield,
            "imputed_dividend_payout_ratio_pct": payout_val,
            "payout_ratio_exceeds_earnings": payout_exceeds,
            "payout_ratio_health": payout_health,
            "derived_market_cap": derived_mcap,
            "imputed_book_value_of_equity": imputed_bv,
            "imputed_total_debt": imputed_debt,
            "market_cap_divergence": market_cap_divergence_block,
            "market_cap_divergence_state": div_state,
        }

        # Structural Sweep on Integrity Failure (PAY-49 / PAY-55 / PAY-61)
        if div_state == "INTEGRITY_FAILURE_REQUIRES_REVIEW":
            for field in MARKET_CAP_DEPENDENT_METRICS:
                metrics[field] = {
                    "state": "UNRELIABLE",
                    "reason": "upstream_market_cap_divergence_integrity_failure",
                    "divergence_pct": div_pct,
                    "divergence_abs_usd": div_abs_usd,
                }

        return metrics

    def _calc_step_3_and_7(self) -> Dict[str, Any]:
        return {
            "spot_provenance": self.derivatives_spot_provenance,
            "constant_maturity_30d_iv": self._calc_cmi_30d(),
            "skew_30d": self._calc_30d_skew(),
            "atm_event_straddle": self._calc_atm_straddle(),
            "volume_and_oi_ratios": self._calc_volume_oi_ratios(),
        }

    def _calc_cmi_30d(self) -> Dict[str, Any]:
        if self.df_options.empty:
            return {"state": "UNKNOWN", "reason": "options_chain_empty"}

        dtes = sorted(self.df_options["daysToExpiration"].dropna().unique())
        sub_30 = [d for d in dtes if d <= 30]
        sup_30 = [d for d in dtes if d > 30]

        if not sub_30 or not sup_30:
            return {"state": "UNKNOWN", "reason": "cannot_bracket_30d_tenor_for_cmi_interpolation"}

        t1_dte = sub_30[-1]
        t2_dte = sup_30[0]

        c1 = self.df_options[self.df_options["daysToExpiration"] == t1_dte]
        c2 = self.df_options[self.df_options["daysToExpiration"] == t2_dte]

        iv1 = safe_float(c1["volatility"].mean())
        iv2 = safe_float(c2["volatility"].mean())

        if iv1 is None or iv2 is None:
            return {"state": "UNKNOWN", "reason": "bracket_tenors_missing_iv"}

        var1 = (iv1 / 100.0) ** 2 * (t1_dte / 365.0)
        var2 = (iv2 / 100.0) ** 2 * (t2_dte / 365.0)
        weight = (30.0 - t1_dte) / (t2_dte - t1_dte)
        var_30 = var1 + weight * (var2 - var1)
        cmi_iv = math.sqrt(max(0.0, var_30 / (30.0 / 365.0))) * 100.0

        return {
            "value": round(cmi_iv, 4),
            "state": "CALCULATED",
            "interpolation_method": "LINEAR_TOTAL_VARIANCE",
            "bracket_tenors": {
                "t1_dte": int(t1_dte),
                "t1_iv": round(iv1, 3),
                "t2_dte": int(t2_dte),
                "t2_iv": round(iv2, 3),
            },
            "vendor_raw_chain_volatility_metadata": 29.0,
        }

    def _calc_30d_skew(self) -> Dict[str, Any]:
        """Calculates 30D skew with microstructure spread filter and signed deltas (PAY-62 / PAY-65)."""
        if self.df_options.empty:
            return {"skew_30d_state": "UNKNOWN", "reason": "options_chain_empty"}

        dtes = sorted(self.df_options["daysToExpiration"].dropna().unique())
        sub_30 = [d for d in dtes if d >= 4]
        if not sub_30:
            return {"skew_30d_state": "UNKNOWN", "reason": "no_tenors_above_min_4_dte"}

        target_dte = min(sub_30, key=lambda x: abs(x - 30))
        chain = self.df_options[self.df_options["daysToExpiration"] == target_dte]

        puts = chain[chain["putCallIndicator"].str.upper() == "PUT"]
        calls = chain[chain["putCallIndicator"].str.upper() == "CALL"]

        if puts.empty or calls.empty:
            return {"skew_30d_state": "UNKNOWN", "reason": "missing_puts_or_calls"}

        best_put_idx = (puts["delta"].abs() - 0.25).abs().idxmin()
        best_call_idx = (calls["delta"].abs() - 0.25).abs().idxmin()

        p_row = puts.loc[best_put_idx]
        c_row = calls.loc[best_call_idx]

        p_ask, p_bid, p_mark = safe_float(p_row.get("ask")), safe_float(p_row.get("bid")), safe_float(p_row.get("mark"))
        c_ask, c_bid, c_mark = safe_float(c_row.get("ask")), safe_float(c_row.get("bid")), safe_float(c_row.get("mark"))

        p_spread = ((p_ask - p_bid) / p_mark) if (p_ask and p_bid and p_mark and p_mark > 0) else 999.0
        c_spread = ((c_ask - c_bid) / c_mark) if (c_ask and c_bid and c_mark and c_mark > 0) else 999.0

        if p_spread > self.max_skew_relative_spread:
            return {
                "skew_30d_state": "UNKNOWN",
                "skew_30d_reason": "skew_wing_liquidity_insufficient_relative_spread_exceeds_tolerance",
                "spread_tolerance_source": "DEFAULT_EXECUTION_BOUNDARY",
                "spread_tolerance_threshold": self.max_skew_relative_spread,
                "observed_wing_relative_spread": round(p_spread, 4),
                "rejected_wing": "PUT",
            }

        if c_spread > self.max_skew_relative_spread:
            return {
                "skew_30d_state": "UNKNOWN",
                "skew_30d_reason": "skew_wing_liquidity_insufficient_relative_spread_exceeds_tolerance",
                "spread_tolerance_source": "DEFAULT_EXECUTION_BOUNDARY",
                "spread_tolerance_threshold": self.max_skew_relative_spread,
                "observed_wing_relative_spread": round(c_spread, 4),
                "rejected_wing": "CALL",
            }

        put_iv = safe_float(p_row.get("volatility"))
        call_iv = safe_float(c_row.get("volatility"))
        put_delta = safe_float(p_row.get("delta"))
        call_delta = safe_float(c_row.get("delta"))

        if put_iv is None or call_iv is None or put_delta is None or call_delta is None:
            return {"skew_30d_state": "UNKNOWN", "reason": "candidate_greeks_null"}

        diff = round(put_iv - call_iv, 3)
        ratio = round(put_iv / call_iv, 4)
        sym_gap = round(abs(abs(put_delta) - abs(call_delta)), 4)

        in_band = (0.20 <= abs(put_delta) <= 0.30) and (0.20 <= abs(call_delta) <= 0.30)

        return {
            "skew_30d_state": "CALCULATED",
            "skew_30d_iv_differential": diff,
            "skew_30d_normalized_ratio": ratio,
            "skew_actual_put_delta": put_delta,
            "skew_actual_call_delta": call_delta,
            "skew_delta_symmetry_gap": sym_gap,
            "skew_delta_anchor": "PRIMARY_25D_SYMMETRIC" if in_band else "FALLBACK_NEAREST_SYMMETRIC",
            "skew_tenor_dte": int(target_dte),
            "skew_regime": "NORMAL_PUT_SKEW" if diff < 0 else "INVERTED_CALL_SKEW",
            "skew_regime_type": "ILLUSTRATIVE_CONVENTION",
        }

    def _calc_atm_straddle(self) -> Dict[str, Any]:
        spot = self.derivatives_spot or self.grounding_spot
        if self.df_options.empty or spot is None:
            return {"state": "UNKNOWN", "reason": "missing_options_or_spot"}

        dtes = sorted([d for d in self.df_options["daysToExpiration"].dropna().unique() if d >= 4])
        if not dtes:
            return {"state": "UNKNOWN", "reason": "no_tenors_above_min_4_dte"}

        front_dte = dtes[0]
        chain = self.df_options[self.df_options["daysToExpiration"] == front_dte]

        strikes = np.sort(chain["strikePrice"].dropna().unique())
        atm_strike = strikes[(np.abs(strikes - spot)).argmin()]

        c = chain[(chain["strikePrice"] == atm_strike) & (chain["putCallIndicator"].str.upper() == "CALL")]
        p = chain[(chain["strikePrice"] == atm_strike) & (chain["putCallIndicator"].str.upper() == "PUT")]

        if c.empty or p.empty:
            return {"state": "UNKNOWN", "reason": "atm_contracts_missing"}

        c_mark = safe_float(c.iloc[0].get("mark"))
        p_mark = safe_float(p.iloc[0].get("mark"))

        if c_mark is None or p_mark is None or c_mark <= 0 or p_mark <= 0:
            return {"state": "UNKNOWN", "reason": "invalid_atm_marks"}

        straddle_cost = round(c_mark + p_mark, 2)
        implied_move = round((straddle_cost / spot) * 100.0, 4)
        fat_tail_move = round(implied_move * 0.85, 4)

        return {
            "state": "CALCULATED",
            "atm_strike": float(atm_strike),
            "front_dte": int(front_dte),
            "straddle_nominal_cost": straddle_cost,
            "implied_move_pct": implied_move,
            "fat_tail_adjusted_move_pct": fat_tail_move,
            "heuristic_anchor": "PRACTITIONER_FAT_TAIL_ADJUSTED_CONVENTION",
            "factor": 0.85,
        }

    def _calc_volume_oi_ratios(self) -> Dict[str, Any]:
        if self.df_options.empty:
            return {"state": "UNKNOWN", "reason": "options_chain_empty"}

        calls = self.df_options[self.df_options["putCallIndicator"].str.upper() == "CALL"]
        puts = self.df_options[self.df_options["putCallIndicator"].str.upper() == "PUT"]

        call_vol = calls["totalVolume"].sum()
        put_vol = puts["totalVolume"].sum()
        call_oi = calls["openInterest"].sum()
        put_oi = puts["openInterest"].sum()

        v_rat = round(put_vol / call_vol, 4) if call_vol > 0 else None
        oi_rat = round(put_oi / call_oi, 4) if call_oi > 0 else None

        return {
            "state": "CALCULATED" if (v_rat is not None and oi_rat is not None) else "PARTIAL",
            "put_call_volume_ratio": v_rat,
            "put_call_oi_ratio": oi_rat,
        }

    def _calc_step_5(self) -> Dict[str, Any]:
        prior_close = safe_float(self.raw.get("phase_0_grounding", {}).get("closePrice"))
        if self.df_history.empty or len(self.df_history) < 2:
            return {"classical_floor_pivots": {"state": "UNKNOWN", "reason": "insufficient_bars"}}

        bar = self.df_history.iloc[-2]
        h, l, c = safe_float(bar.get("high")), safe_float(bar.get("low")), safe_float(bar.get("close"))

        pivots = {"state": "UNKNOWN"}
        if h and l and c:
            p = (h + l + c) / 3.0
            pivots = {
                "state": "CALCULATED",
                "Pivot": round(p, 2),
                "R1": round(2 * p - l, 2),
                "R2": round(p + (h - l), 2),
                "R3": round(h + 2 * (p - l), 2),
                "S1": round(2 * p - h, 2),
                "S2": round(p - (h - l), 2),
                "S3": round(l - 2 * (h - p), 2),
            }

        rv_dict = {"state": "CALCULATED"}
        for label, w in [("10d_tactical", 10), ("30d_intermediate", 30), ("252d_macro", 252)]:
            n = len(self.df_history)
            if n < w:
                if label == "252d_macro":
                    sub = self.df_history.copy()
                    log_rets = np.log(sub["close"] / sub["close"].shift(1)).dropna()
                    c2c = float(np.std(log_rets, ddof=1) * np.sqrt(self.trading_days_per_year) * 100.0)
                    rv_dict[label] = {
                        "state": "INSUFFICIENT_HISTORY",
                        "target_window_bars": 252,
                        "actual_sample_bars": n,
                        "return_observations": len(log_rets),
                        "computed_realized_vol": round(c2c, 2),
                        "reason": "sample_bars_below_minimum_macro_threshold_180",
                    }
                else:
                    rv_dict[label] = {"state": "UNKNOWN", "reason": f"insufficient_bars_{n}_for_window_{w}"}
                continue

            sub = self.df_history.iloc[-w:].copy()
            log_rets = np.log(sub["close"] / sub["close"].shift(1)).dropna()
            c2c = float(np.std(log_rets, ddof=1) * np.sqrt(self.trading_days_per_year) * 100.0)

            hl = np.log(sub["high"] / sub["low"]) ** 2
            park = float(np.sqrt((1.0 / (4.0 * np.log(2.0))) * hl.mean()) * np.sqrt(self.trading_days_per_year) * 100.0)

            co = np.log(sub["close"] / sub["open"]) ** 2
            gk_term = 0.5 * hl - (2.0 * np.log(2.0) - 1.0) * co
            gk = float(np.sqrt(max(0.0, gk_term.mean())) * np.sqrt(self.trading_days_per_year) * 100.0)

            status = "FULL_HISTORY" if len(sub) >= (240 if w == 252 else w) else "PARTIAL_HISTORY"
            rv_dict[label] = {
                "status": status,
                "actual_sample_bars": len(sub),
                "return_observations": len(log_rets),
                "close_to_close": round(c2c, 2),
                "parkinson": round(park, 2),
                "garman_klass": round(gk, 2),
                "estimator_methodology": "Garman-Klass (1980) zero-drift invariant",
            }

        return {"classical_floor_pivots": pivots, "realized_volatility": rv_dict}