"""
schwab_step5_technicals.py

Step 5: classical floor pivots and realized volatility suite orchestration.
Body moved verbatim from _calc_step_5; RV suite delegated to injected calc.
"""
from __future__ import annotations

from typing import Any, Dict

from schwab_marketdata_context import MarketDataContext
from schwab_step5_realized_vol import Step5RealizedVolCalculator
from schwab_utils import safe_float


class Step5TechnicalsCalculator:

    def __init__(self, ctx: MarketDataContext, rv_calc: Step5RealizedVolCalculator):
        self.ctx = ctx
        self.rv_calc = rv_calc

    def calculate(self) -> Dict[str, Any]:
        pivots = {"state": "UNKNOWN", "reason": "insufficient_ohlc_bars"}
        rv = {"state": "UNKNOWN", "reason": "insufficient_ohlc_bars"}

        if self.ctx.ph_df.empty:
            return {"classical_floor_pivots": pivots, "realized_volatility": rv}

        if "datetime" not in self.ctx.ph_df.columns:
            return {
                "classical_floor_pivots": {"state": "UNKNOWN", "reason": "missing_datetime_column"},
                "realized_volatility": {"state": "UNKNOWN", "reason": "missing_datetime_column"},
            }

        clean_bars = self.ctx.ph_df.dropna(
            subset=["open", "high", "low", "close", "datetime"]
        ).sort_values("datetime")

        if clean_bars.empty:
            return {"classical_floor_pivots": pivots, "realized_volatility": rv}

        c_series = clean_bars["close"]
        l_series = clean_bars["low"]
        h_series = clean_bars["high"]

        is_nav_flat = (h_series == l_series).mean() >= 0.80

        if (c_series <= 0.01).any() or (l_series <= 0.01).any():
            rv = {
                "state": "UNKNOWN",
                "reason": "sub_cent_zero_price_bars_unsuitable_for_diffusion_estimators",
            }
        elif is_nav_flat:
            rv = {
                "state": "NOT_APPLICABLE_NAV_BASED_ASSET",
                "reason": "intraday_hl_identical_nav_bars",
            }
        else:
            rv = self.rv_calc.calculate_suite(clean_bars)

        if is_nav_flat:
            pivots = {
                "state": "NOT_APPLICABLE_NAV_BASED_ASSET",
                "reason": "intraday_hl_identical_nav_bars",
            }
        else:
            last_bar = clean_bars.iloc[-1]
            h, l, c = safe_float(last_bar["high"]), safe_float(last_bar["low"]), safe_float(last_bar["close"])
            if h is not None and l is not None and c is not None and h > 0 and l > 0 and c > 0:
                p = (h + l + c) / 3.0
                if p >= 0.005:
                    pivots = {
                        "Pivot": round(p, 2),
                        "R1": round((2 * p) - l, 2),
                        "R2": round(p + (h - l), 2),
                        "R3": round(p + 2 * (h - l), 2),
                        "S1": round((2 * p) - h, 2),
                        "S2": round(p - (h - l), 2),
                        "S3": round(p - 2 * (h - l), 2),
                        "state": "CALCULATED",
                    }
                else:
                    pivots = {"state": "UNKNOWN", "reason": "candle_prices_non_positive"}
            else:
                pivots = {"state": "UNKNOWN", "reason": "candle_prices_non_positive"}

        return {"classical_floor_pivots": pivots, "realized_volatility": rv}