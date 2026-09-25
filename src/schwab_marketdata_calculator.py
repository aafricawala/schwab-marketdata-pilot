"""
schwab_marketdata_calculator.py
========================================================================================
QUANTITATIVE DERIVATIVES, VOLATILITY & TECHNICAL RISK ANALYTICS ENGINE
========================================================================================

WHAT THIS SCRIPT DOES:
----------------------
This module acts as the pure mathematical and quantitative modeling engine for the
Master Thesis data pipeline (Schema v16.20). It takes structured in-memory market
payloads (fundamental metrics, historical OHLCV bars, and option chains) and derives
key financial, volatility, flow, and technical indicators across four thesis phases:
  - Step 0 (Grounding): Overnight session opening gap percentage.
  - Step 1 (Fundamentals & Quality): Earnings yield, imputed dividend payout ratio,
    cash flow from operations (CFO) per share and yield, imputed book value of equity,
    and imputed total debt liabilities.
  - Step 3 & 7 (Derivatives, Surface & Flows): Realized volatility across three distinct
    estimators (Close-to-Close, Parkinson high-low, Garman-Klass OHLC), aggregate Put/Call
    volume and open interest ratios, 30-day ~25-delta volatility skew metrics, and front-month
    ATM straddle implied move calculations.
  - Step 5 (Technicals & Flows): Classical 3-tier Floor Pivots (Pivot, R1-R3, S1-S3).

WHEN AND HOW IT GETS CALLED:
----------------------------
This module is executed strictly in-memory during step 3 of the orchestration pipeline
(e.g., in Notebook Cell 2 or batch processing jobs):
  1. `schwab_raw_marketdata.py` extracts prices, fundamentals, historical candles,
     and targeted option chains into DataFrames.
  2. `MasterThesisCalculator` is instantiated with the raw payload, price DataFrame,
     options DataFrame, and runtime lookback parameters.
  3. `.calculate_metrics()` is executed to compute all mathematical derivatives.
  4. The returned metrics dictionary is attached to the master payload under the
     `calculated_metrics` key, which is then handed off to `schwab_serializer.py`
     for minified formatting and export.

KEY CLASSES & METHODS AND HIGH-LEVEL RESPONSIBILITIES:
------------------------------------------------------
1. safe_div(num, den):
   - A defensive numerical helper that divides two values without raising exceptions
     (ZeroDivisionError, ValueError, or TypeError), returning `None` if invalid or zero.

2. MasterThesisCalculator (Core Class):
   - Encapsulates mathematical modeling, isolating computational algorithms from API I/O
     and JSON serialization concerns.
   - Core Methods:
       * calculate_metrics(): Orchestrates execution across all thesis steps and returns
         a combined metrics dictionary.
       * _calc_step_0(): Computes the session gap percentage comparing the latest bar's
         open price to the previous official close.
       * _calc_step_1(): Derives valuation, equity, debt, and cash flow yields from
         fundamental inputs (P/E, EPS, dividends, P/CF, P/B, shares, total debt to equity).
       * _calc_step_3_and_7(): Dispatches and aggregates all derivative, options flow,
         and volatility indicators.
       * _calc_realized_volatilities(): Computes annualized (252 trading days) historical
         volatility using standard Close-to-Close standard deviation, Parkinson range variance,
         and Garman-Klass open-high-low-close variance.
       * _calc_volume_and_oi_ratios(): Aggregates Put-to-Call total volume and open interest
         ratios across the extracted options chain.
       * _calc_30d_skew(): Resolves contracts near 30 DTE, identifies ~25-delta Puts and
         Calls, and derives IV differential (Put IV - Call IV) and normalized skew ratios.
       * _calc_atm_event_straddle(): Identifies the front-month expiration and nearest
         At-The-Money (ATM) strike to compute the synthetic straddle cost and implied move %.
       * _calc_step_5(): Calculates Classical Floor Pivot levels (Pivot, R1, R2, R3,
         S1, S2, S3) from the most recent completed daily price candle.

IMPORTANT ARCHITECTURAL CONSIDERATIONS:
---------------------------------------
- Separation of Concerns: This module performs pure mathematical calculations on numeric
  data (floats, ints, DataFrames). It does not perform string formatting (like prepending '$'
  signs) or handle file saving; all serialization is decoupled into `schwab_serializer.py`.
- Granular Error Isolation: Mathematical sub-routines (skew calculation, straddle pricing,
  realized volatility) are isolated into dedicated private helper functions, preventing
  a data gap in one metric (e.g., missing Delta) from cascading and halting other indicators.
- In-Memory Efficiency: Computes heavy quantitative metrics directly from transient DataFrames
  without writing intermediate tables to disk.
========================================================================================
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("MasterThesisEngine")


def safe_div(num: Any, den: Any) -> Optional[float]:
    """Divides two numerical values defensively without raising exceptions."""
    try:
        if num is None or den is None or pd.isna(num) or pd.isna(den):
            return None
        n, d = float(num), float(den)
        return n / d if d != 0.0 else None
    except (ValueError, TypeError, ZeroDivisionError):
        return None


class MasterThesisCalculator:
    """Calculates phase-aligned mathematical derivatives and financial indicators."""

    def __init__(
        self,
        raw_data: Dict[str, Any],
        price_history_df: pd.DataFrame,
        options_df: pd.DataFrame,
        params: Dict[str, Any],
    ):
        self.raw = raw_data
        self.params = params
        self.price_history_df = price_history_df
        self.options_df = options_df

        self.spot: Optional[float] = self.raw.get("phase_0_grounding", {}).get("lastPrice")
        self.fundamentals: Dict[str, Any] = self.raw.get("step_1_fundamentals", {})
        self.liquidity: Dict[str, Any] = self.raw.get("step_8_and_9_liquidity_and_sizing", {})

    def calculate_metrics(self) -> Dict[str, Any]:
        """Calculates and aggregates all model metrics across thesis phases."""
        return {
            "step_0_grounding": self._calc_step_0(),
            "step_1_fundamentals_and_quality": self._calc_step_1(),
            "step_3_and_7_derivatives_and_surface": self._calc_step_3_and_7(),
            "step_5_technicals_and_flows": self._calc_step_5(),
        }

    def _calc_step_0(self) -> Dict[str, Any]:
        """Calculates overnight session open gap percentage."""
        calc: Dict[str, Optional[float]] = {"session_gap_pct": None}
        prev_close = self.raw.get("phase_0_grounding", {}).get("closePrice")
        df = self.price_history_df

        if not df.empty:
            latest = df.iloc[-1]
            latest_open = latest.get("open")
            if prev_close and pd.notna(latest_open):
                gap = safe_div(latest_open - prev_close, prev_close)
                calc["session_gap_pct"] = gap * 100 if gap is not None else None

        return calc

    def _calc_step_1(self) -> Dict[str, Any]:
        """Derives core valuation, cash flow, and debt metrics."""
        pe = self.fundamentals.get("peRatio")
        eps = self.fundamentals.get("eps")
        div = self.fundamentals.get("divAmount")
        pcf = self.fundamentals.get("pcfRatio")
        shares_out = self.fundamentals.get("sharesOutstanding")
        pb = self.fundamentals.get("pbRatio")
        dteq = self.fundamentals.get("totalDebtToEquity")

        mcap = (self.spot * shares_out) if (self.spot and shares_out) else None

        earnings_yield = None
        if pe:
            ey_ratio = safe_div(1, pe)
            earnings_yield = ey_ratio * 100 if ey_ratio is not None else None
        elif eps and self.spot:
            ey_ratio = safe_div(eps, self.spot)
            earnings_yield = ey_ratio * 100 if ey_ratio is not None else None

        payout_ratio = safe_div(div, eps)
        payout_ratio_pct = payout_ratio * 100 if payout_ratio is not None else None

        cfo_per_share = safe_div(self.spot, pcf) if pcf and self.spot else None

        cfo_yield = safe_div(1, pcf)
        cfo_yield_pct = cfo_yield * 100 if cfo_yield is not None else None

        imputed_bv = safe_div(mcap, pb) if mcap and pb else None
        imputed_debt = None
        if imputed_bv and dteq is not None:
            imputed_debt = imputed_bv * (dteq / 100.0)

        return {
            "earnings_yield_pct": earnings_yield,
            "imputed_dividend_payout_ratio_pct": payout_ratio_pct,
            "cfo_per_share": cfo_per_share,
            "cfo_yield_pct": cfo_yield_pct,
            "imputed_book_value_of_equity": imputed_bv,
            "imputed_total_debt": imputed_debt,
        }

    def _calc_step_3_and_7(self) -> Dict[str, Any]:
        """Orchestrates derivative, volume flow, and surface volatility indicators."""
        metrics: Dict[str, Any] = {
            "skew_tenor_dte": None,
            "skew_30d_iv_differential": None,
            "skew_30d_normalized_ratio": None,
            "put_call_volume_ratio": None,
            "put_call_open_interest_ratio": None,
            "realized_volatility_lookback_days": None,
            "realized_volatility_lookback_years": None,
            "realized_volatility_close_to_close": None,
            "realized_volatility_parkinson": None,
            "realized_volatility_garman_klass": None,
            "event_tenor_dte": None,
            "event_implied_move_pct": None,
        }

        # Realized Volatilities
        metrics.update(self._calc_realized_volatilities())

        # Options Flow & Surface Analytics
        if not self.options_df.empty:
            metrics.update(self._calc_volume_and_oi_ratios())
            metrics.update(self._calc_30d_skew())
            metrics.update(self._calc_atm_event_straddle())

        return metrics

    def _calc_realized_volatilities(self) -> Dict[str, Optional[float]]:
        """Calculates multi-estimator realized volatilities (Close-to-Close, Parkinson, Garman-Klass)."""
        rv_metrics: Dict[str, Optional[float]] = {
            "realized_volatility_lookback_days": None,
            "realized_volatility_lookback_years": None,
            "realized_volatility_close_to_close": None,
            "realized_volatility_parkinson": None,
            "realized_volatility_garman_klass": None,
        }

        df = self.price_history_df
        if df.empty or len(df) <= 1:
            return rv_metrics

        try:
            rv_metrics["realized_volatility_lookback_days"] = len(df)
            rv_metrics["realized_volatility_lookback_years"] = self.params.get("HISTORICAL_PERIOD", 1)

            # Close-to-Close Volatility
            log_rets = np.log(df["close"] / df["close"].shift(1)).dropna()
            rv_metrics["realized_volatility_close_to_close"] = float(np.sqrt(252) * log_rets.std() * 100)

            # Parkinson Volatility (High-Low)
            hl_log = np.log(df["high"] / df["low"])
            parkinson_var = (1.0 / (4.0 * np.log(2))) * (hl_log ** 2).mean()
            rv_metrics["realized_volatility_parkinson"] = float(np.sqrt(252 * parkinson_var) * 100)

            # Garman-Klass Volatility (OHLC)
            co_log = np.log(df["close"] / df["open"])
            gk_var = (0.5 * (hl_log ** 2)) - ((2 * np.log(2) - 1) * (co_log ** 2))
            rv_metrics["realized_volatility_garman_klass"] = float(np.sqrt(252 * gk_var.mean()) * 100)

        except (ValueError, TypeError, ZeroDivisionError) as exc:
            logger.warning("Realized volatility calculation failed: %s", exc)

        return rv_metrics

    def _calc_volume_and_oi_ratios(self) -> Dict[str, Optional[float]]:
        """Computes aggregate Put/Call volume and open interest flow ratios."""
        opt = self.options_df
        puts = opt[opt["putCallIndicator"] == "PUT"]
        calls = opt[opt["putCallIndicator"] == "CALL"]

        return {
            "put_call_volume_ratio": safe_div(puts["totalVolume"].sum(), calls["totalVolume"].sum()),
            "put_call_open_interest_ratio": safe_div(puts["openInterest"].sum(), calls["openInterest"].sum()),
        }

    def _calc_30d_skew(self) -> Dict[str, Optional[float]]:
        """Extracts ~25-delta Put and Call implied volatility to measure 30-day skew."""
        skew_data: Dict[str, Optional[float]] = {
            "skew_tenor_dte": None,
            "skew_30d_iv_differential": None,
            "skew_30d_normalized_ratio": None,
        }

        try:
            opt = self.options_df.copy()
            opt["dte_diff"] = (opt["daysToExpiration"] - 30).abs()
            min_dte_diff = opt["dte_diff"].min()
            chain_30d = opt[opt["dte_diff"] == min_dte_diff]

            if chain_30d.empty:
                return skew_data

            skew_data["skew_tenor_dte"] = int(chain_30d.iloc[0]["daysToExpiration"])
            chain_30d = chain_30d.assign(delta_abs=chain_30d["delta"].astype(float).abs())

            puts = chain_30d[chain_30d["putCallIndicator"] == "PUT"]
            calls = chain_30d[chain_30d["putCallIndicator"] == "CALL"]

            if puts.empty or calls.empty:
                return skew_data

            put_25d = puts.iloc[(puts["delta_abs"] - 0.25).abs().argmin()]
            call_25d = calls.iloc[(calls["delta_abs"] - 0.25).abs().argmin()]

            iv_p = float(put_25d["volatility"])
            iv_c = float(call_25d["volatility"])

            skew_data["skew_30d_iv_differential"] = iv_p - iv_c
            skew_data["skew_30d_normalized_ratio"] = safe_div(iv_p, iv_c)

        except (IndexError, KeyError, ValueError, TypeError) as exc:
            logger.debug("Failed 30-day skew extraction: %s", exc)

        return skew_data

    def _calc_atm_event_straddle(self) -> Dict[str, Optional[float]]:
        """Calculates front-month ATM straddle implied move percentage."""
        straddle_data: Dict[str, Optional[float]] = {
            "event_tenor_dte": None,
            "event_implied_move_pct": None,
        }

        if not self.spot:
            return straddle_data

        try:
            front_dte = self.options_df["daysToExpiration"].min()
            front_chain = self.options_df[self.options_df["daysToExpiration"] == front_dte].copy()
            straddle_data["event_tenor_dte"] = int(front_dte)

            front_chain["strike_diff"] = (front_chain["strikePrice"].astype(float) - self.spot).abs()
            atm_strike = front_chain.loc[front_chain["strike_diff"].idxmin(), "strikePrice"]

            atm_put = front_chain[
                (front_chain["strikePrice"] == atm_strike) & (front_chain["putCallIndicator"] == "PUT")
            ].iloc[0]
            atm_call = front_chain[
                (front_chain["strikePrice"] == atm_strike) & (front_chain["putCallIndicator"] == "CALL")
            ].iloc[0]

            straddle_cost = float(atm_put["mark"] + atm_call["mark"])
            move_ratio = safe_div(straddle_cost, self.spot)
            straddle_data["event_implied_move_pct"] = move_ratio * 100 if move_ratio is not None else None

        except (IndexError, KeyError, ValueError, TypeError) as exc:
            logger.debug("Failed ATM event straddle pricing: %s", exc)

        return straddle_data

    def _calc_step_5(self) -> Dict[str, Any]:
        """Calculates Classical 3-tier Floor Pivots (P, R1-R3, S1-S3)."""
        calc = {"classical_floor_pivots": None}
        df = self.price_history_df

        if not df.empty:
            latest = df.iloc[-1]
            h, l, c = latest.get("high"), latest.get("low"), latest.get("close")
            if all(pd.notna(x) for x in [h, l, c]):
                p = (h + l + c) / 3.0
                calc["classical_floor_pivots"] = {
                    "R3": float(h + 2.0 * (p - l)),
                    "R2": float(p + (h - l)),
                    "R1": float((2.0 * p) - l),
                    "Pivot": float(p),
                    "S1": float((2.0 * p) - h),
                    "S2": float(p - (h - l)),
                    "S3": float(l - 2.0 * (h - p)),
                }

        return calc