"""
schwab_step3_cmi.py

Constant-maturity 30d IV bracket interpolation.
Body moved verbatim from _calc_cmi_30d.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from schwab_marketdata_context import MarketDataContext


class Step3CMICalculator:

    def __init__(self, ctx: MarketDataContext):
        self.ctx = ctx

    def calculate(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty or "daysToExpiration" not in df.columns or "strikePrice" not in df.columns:
            return {
                "state": "UNKNOWN",
                "reason": "options_chain_empty_or_unavailable",
            }
        dtes = sorted(
            list({int(d) for d in df["daysToExpiration"].dropna() if int(d) >= 0})
        )
        if not dtes:
            return {"state": "UNKNOWN", "reason": "no_valid_expirations"}
        t1_cand = [d for d in dtes if d <= 30]
        t2_cand = [d for d in dtes if d >= 30]
        t1 = t1_cand[-1] if t1_cand else dtes[0]
        t2 = t2_cand[0] if t2_cand else dtes[-1]
        span = abs(t2 - t1)
        quality = (
            "DEGENERATE_SINGLE_EXPIRATION"
            if span == 0
            else ("TIGHT" if span <= 10 else "WIDE")
        )

        def get_mean_iv(dte_val: int) -> Optional[float]:
            sub = df[df["daysToExpiration"] == dte_val]
            if sub.empty or "volatility" not in sub.columns:
                return None
            sub = sub.assign(d_diff=(sub["strikePrice"] - self.ctx.calc_spot).abs())
            atm_k = sub.loc[sub["d_diff"].idxmin(), "strikePrice"]
            vols = sub[sub["strikePrice"] == atm_k]["volatility"].dropna()
            return float(vols.mean()) if not vols.empty else None

        iv1, iv2 = get_mean_iv(t1), get_mean_iv(t2)
        if iv1 is None or iv2 is None or iv1 <= 0.0 or iv2 <= 0.0:
            return {
                "constant_maturity_30d_iv": None,
                "state": "UNKNOWN",
                "reason": "invalid_iv_sentinel_detected",
                "t1_dte": t1,
                "t2_dte": t2,
                "bracket_span_days": span,
                "bracket_quality": quality,
            }

        if t1 == t2:
            iv30 = iv1
        else:
            w1, w2 = abs(t2 - 30) / float(span or 1), abs(30 - t1) / float(span or 1)
            iv30 = (iv1 * w1) + (iv2 * w2)
        return {
            "constant_maturity_30d_iv": round(iv30, 4),
            "state": "CALCULATED",
            "t1_dte": t1,
            "t2_dte": t2,
            "bracket_span_days": span,
            "bracket_quality": quality,
        }