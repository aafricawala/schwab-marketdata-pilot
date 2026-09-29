"""
schwab_step3_skew.py

25-delta skew at ~30d tenor, with spread gate and fallback anchor logic.
Body moved verbatim from _calc_skew_30d.
"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from schwab_marketdata_context import MarketDataContext
from schwab_utils import safe_div, safe_float


class Step3SkewCalculator:

    def __init__(self, ctx: MarketDataContext):
        self.ctx = ctx

    def calculate(
        self, df: pd.DataFrame, cmi_block: Dict[str, Any]
    ) -> Dict[str, Any]:
        b_span = cmi_block.get("bracket_span_days")
        b_qual = cmi_block.get("bracket_quality")
        if df.empty or "daysToExpiration" not in df.columns or "putCallIndicator" not in df.columns:
            ret = {
                "state": "UNKNOWN",
                "reason": "no_valid_dte_for_skew",
                "skew_delta_anchor": "REJECTED_BEFORE_SELECTION",
                "skew_regime": "UNKNOWN",
            }
            if b_span is not None:
                ret["bracket_span_days"] = b_span
            if b_qual:
                ret["bracket_quality"] = b_qual
            return ret
        dtes = sorted(
            list({int(d) for d in df["daysToExpiration"].dropna() if int(d) >= 0})
        )
        if not dtes:
            ret = {
                "state": "UNKNOWN",
                "reason": "no_valid_dte_for_skew",
                "skew_delta_anchor": "REJECTED_BEFORE_SELECTION",
                "skew_regime": "UNKNOWN",
            }
            if b_span is not None:
                ret["bracket_span_days"] = b_span
            if b_qual:
                ret["bracket_quality"] = b_qual
            return ret
        t_dte = min(dtes, key=lambda d: abs(d - 30))
        sub = df[df["daysToExpiration"] == t_dte]
        if "delta" not in sub.columns:
            ret = {
                "skew_tenor_dte": t_dte,
                "state": "UNKNOWN",
                "reason": "missing_wing_delta_contracts",
                "skew_delta_anchor": "REJECTED_BEFORE_SELECTION",
                "skew_regime": "UNKNOWN",
            }
            if b_span is not None:
                ret["bracket_span_days"] = b_span
            if b_qual:
                ret["bracket_quality"] = b_qual
            return ret
        puts = sub[sub["putCallIndicator"] == "PUT"].assign(
            d_diff=(sub["delta"].abs() - 0.25).abs()
        )
        calls = sub[sub["putCallIndicator"] == "CALL"].assign(
            d_diff=(sub["delta"].abs() - 0.25).abs()
        )
        if puts.empty or calls.empty:
            ret = {
                "skew_tenor_dte": t_dte,
                "state": "UNKNOWN",
                "reason": "missing_wing_delta_contracts",
                "skew_delta_anchor": "REJECTED_BEFORE_SELECTION",
                "skew_regime": "UNKNOWN",
            }
            if b_span is not None:
                ret["bracket_span_days"] = b_span
            if b_qual:
                ret["bracket_quality"] = b_qual
            return ret
        p_row = puts.loc[puts["d_diff"].idxmin()]
        c_row = calls.loc[calls["d_diff"].idxmin()]
        p_bid, p_ask, p_iv = safe_float(p_row.get("bid")), safe_float(p_row.get("ask")), safe_float(p_row.get("volatility"))
        c_bid, c_ask, c_iv = safe_float(c_row.get("bid")), safe_float(c_row.get("ask")), safe_float(c_row.get("volatility"))
        p_mid = safe_float(p_row.get("mark")) or (safe_div(p_bid + p_ask, 2) if p_bid is not None and p_ask is not None else None)
        c_mid = safe_float(c_row.get("mark")) or (safe_div(c_bid + c_ask, 2) if c_bid is not None and c_ask is not None else None)
        p_spr = 2.0 if (p_bid == 0.0 and p_ask and p_ask > 0) else (safe_div(abs(p_ask - p_bid), p_mid) if p_ask is not None and p_bid is not None and p_mid else None)
        c_spr = 2.0 if (c_bid == 0.0 and c_ask and c_ask > 0) else (safe_div(abs(c_ask - c_bid), c_mid) if c_ask is not None and c_bid is not None and c_mid else None)
        max_spr = self.ctx.params.get("MAX_SKEW_RELATIVE_SPREAD", 0.50)
        p_fail = p_spr is not None and p_spr > max_spr
        c_fail = c_spr is not None and c_spr > max_spr
        if p_fail or c_fail or p_spr is None or c_spr is None:
            rej_wing = "BOTH" if (p_fail and c_fail) else ("PUT" if p_fail else "CALL")
            rej_dict = {
                "skew_tenor_dte": t_dte,
                "skew_delta_anchor": "REJECTED_AT_WING_SPREAD_GATE",
                "skew_regime": "UNKNOWN",
                "spread_tolerance_source": "DEFAULT_EXECUTION_BOUNDARY",
                "state": "UNKNOWN",
                "reason": "skew_wings_exceed_spread_tolerance",
                "observed_put_relative_spread": round(p_spr, 4) if p_spr is not None else None,
                "observed_call_relative_spread": round(c_spr, 4) if c_spr is not None else None,
                "spread_zero_bid_flag": p_bid == 0.0 or c_bid == 0.0,
                "rejected_wing": rej_wing,
                "cmi_bracket_ref": "constant_maturity_30d_iv",
            }
            if b_span is not None:
                rej_dict["bracket_span_days"] = b_span
            if b_qual:
                rej_dict["bracket_quality"] = b_qual
            return rej_dict
        diff = p_iv - c_iv if p_iv and c_iv else None
        p_d, c_d = safe_float(p_row.get("delta")), safe_float(c_row.get("delta"))
        p_abs, c_abs = abs(p_d) if p_d else 0.0, abs(c_d) if c_d else 0.0
        sym_gap = round(abs(p_abs - c_abs), 3)
        p_in_band = 0.20 <= p_abs <= 0.30
        c_in_band = 0.20 <= c_abs <= 0.30
        is_primary = p_in_band and c_in_band and (sym_gap <= 0.05)
        anchor_label = "PRIMARY_25D_SYMMETRIC" if is_primary else "FALLBACK_NEAREST_SYMMETRIC"
        s_regime = "REVERSE_CALL_SKEW" if (diff is not None and diff > 0) else "STANDARD_PUT_SKEW"
        ret = {
            "skew_tenor_dte": t_dte,
            "skew_delta_anchor": anchor_label,
            "skew_30d_iv_differential": round(diff, 3) if diff is not None else None,
            "skew_regime": s_regime,
            "skew_delta_symmetry_gap": sym_gap,
            "skew_actual_put_delta": round(p_d, 3) if p_d is not None else None,
            "skew_actual_call_delta": round(c_d, 3) if c_d is not None else None,
            "spread_tolerance_source": "DEFAULT_EXECUTION_BOUNDARY",
            "state": "CALCULATED",
        }
        if b_span is not None:
            ret["bracket_span_days"] = b_span
        if b_qual:
            ret["bracket_quality"] = b_qual
        if not is_primary:
            ret["skew_anchor_reason"] = "PRIMARY_BAND_VIOLATED" if not (p_in_band and c_in_band) else "SYMMETRY_GAP_EXCEEDED"
        return ret
