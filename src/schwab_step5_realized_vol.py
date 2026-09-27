"""
schwab_step5_realized_vol.py

Realized volatility suite (10d / 30d / 252d) and per-horizon estimator.
Bodies moved verbatim from _calc_realized_vol_suite and _calc_rv_horizon.
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd


class Step5RealizedVolCalculator:

    def calculate_suite(self, df: pd.DataFrame) -> Dict[str, Any]:
        n = len(df)
        if n < 2:
            return {"state": "UNKNOWN", "reason": "insufficient_bars_for_returns"}
        res: Dict[str, Any] = {"state": "CALCULATED"}
        res["10d_tactical"] = self._calc_rv_horizon(df.tail(11), 10, min_bars=8)
        res["30d_intermediate"] = self._calc_rv_horizon(df.tail(31), 30, min_bars=20)
        res["252d_macro"] = self._calc_rv_horizon(df.tail(253), 252, min_bars=180, check_seasoning=True, total_avail=n)
        return res

    def _calc_rv_horizon(
        self,
        df: pd.DataFrame,
        target_win: int,
        min_bars: int,
        check_seasoning: bool = False,
        total_avail: int = 0,
    ) -> Dict[str, Any]:
        n_bars = len(df)
        n_rets = max(0, n_bars - 1)
        c2c_vol = None
        c_col, h_col, l_col, o_col = "close", "high", "low", "open"

        if n_rets >= 2 and c_col in df.columns:
            log_ret = np.log(df[c_col] / df[c_col].shift(1)).dropna()
            c2c_vol = float(log_ret.std(ddof=1) * np.sqrt(252) * 100.0) if len(log_ret) > 1 else None

        if n_bars < min_bars:
            ret_dict: Dict[str, Any] = {
                "state": "INSUFFICIENT_HISTORY",
                "target_window_bars": target_win,
                "actual_sample_bars": n_bars,
                "return_observations": n_rets,
                "reason": f"sample_bars_below_minimum_{min_bars}",
            }
            if c2c_vol is not None:
                ret_dict["computed_realized_vol"] = round(c2c_vol, 2)
            if check_seasoning:
                ret_dict["listing_seasoning"] = "ESTABLISHED_LISTING" if total_avail >= 250 else "UNSEASONED_LISTING"
                ret_dict["total_available_bars"] = total_avail
            return ret_dict

        hl = np.log(df[h_col] / df[l_col])
        co = np.log(df[c_col] / df[o_col])
        park = float(np.sqrt((1.0 / (4.0 * np.log(2.0))) * (hl**2).mean()) * np.sqrt(252) * 100.0)
        gk = float(np.sqrt((0.5 * (hl**2) - ((2.0 * np.log(2.0) - 1.0) * (co**2))).mean()) * np.sqrt(252) * 100.0)
        disp = abs((c2c_vol or gk) - gk)

        if disp > 100.0 or gk > 200.0 or (c2c_vol is not None and c2c_vol > 200.0):
            suppressed_dict: Dict[str, Any] = {
                "state": "UNKNOWN",
                "reason": "extreme_dispersion_regime_suppresses_estimator",
                "target_window_bars": target_win,
                "actual_sample_bars": n_bars,
                "return_observations": n_rets,
                "unsuppressed_dispersion_pp": round(disp, 4),
                "unsuppressed_garman_klass": round(gk, 4),
            }
            if c2c_vol is not None:
                suppressed_dict["unsuppressed_close_to_close"] = round(c2c_vol, 4)
            if check_seasoning:
                suppressed_dict["listing_seasoning"] = "ESTABLISHED_LISTING" if total_avail >= 250 else "UNSEASONED_LISTING"
                suppressed_dict["total_available_bars"] = total_avail
            return suppressed_dict

        st = "PARTIAL_HISTORY" if (target_win == 252 and n_bars < 252) else "FULL_HISTORY"
        ret: Dict[str, Any] = {
            "status": st,
            "actual_sample_bars": n_bars,
            "return_observations": n_rets,
            "close_to_close": round(c2c_vol, 4) if c2c_vol else None,
            "parkinson": round(park, 4),
            "garman_klass": round(gk, 4),
            "estimator_dispersion_pp": round(disp, 4),
            "estimator_methodology": "Garman-Klass (1980) zero-drift invariant",
        }

        if disp > 40.0:
            ret["estimator_dispersion_regime"] = "EXTREME_DISPERSION"

        if check_seasoning:
            ret["listing_seasoning"] = "ESTABLISHED_LISTING" if total_avail >= 250 else "UNSEASONED_LISTING"
            ret["total_available_bars"] = total_avail
            if st == "PARTIAL_HISTORY":
                ret["sample_bars_note"] = "lookback_satisfies_minimum_threshold_below_target"
        return ret