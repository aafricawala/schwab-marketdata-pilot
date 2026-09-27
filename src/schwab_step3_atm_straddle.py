"""
schwab_step3_atm_straddle.py

Front-expiry ATM straddle cost and practitioner expected move.
Body moved verbatim from _calc_atm_straddle.
"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from schwab_marketdata_context import MarketDataContext
from schwab_utils import safe_div, safe_float


class Step3ATMStraddleCalculator:

    def __init__(self, ctx: MarketDataContext):
        self.ctx = ctx

    def calculate(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df.empty or "daysToExpiration" not in df.columns or "strikePrice" not in df.columns:
            return {"state": "UNKNOWN", "reason": "no_valid_expirations"}
        dtes = sorted(list({int(d) for d in df["daysToExpiration"].dropna() if int(d) >= 0}))
        if not dtes:
            return {"state": "UNKNOWN", "reason": "no_valid_expirations"}
        f_dte = dtes[0]
        sub = df[df["daysToExpiration"] == f_dte].copy()
        if sub.empty:
            return {"state": "UNKNOWN", "reason": "insufficient_atm_quote_data"}
        sub["d_diff"] = (sub["strikePrice"] - self.ctx.calc_spot).abs()
        atm_k = sub.loc[sub["d_diff"].idxmin(), "strikePrice"]
        p_sub = sub[(sub["strikePrice"] == atm_k) & (sub["putCallIndicator"] == "PUT")]
        c_sub = sub[(sub["strikePrice"] == atm_k) & (sub["putCallIndicator"] == "CALL")]
        p_mark = safe_float(p_sub["mark"].iloc[0]) if not p_sub.empty else None
        c_mark = safe_float(c_sub["mark"].iloc[0]) if not c_sub.empty else None
        if p_mark is not None and c_mark is not None and self.ctx.calc_spot:
            cost = p_mark + c_mark
            move_pct = safe_div(cost * 0.85 * 100.0, self.ctx.calc_spot)
            return {
                "front_expiry_dte": f_dte,
                "atm_strike": float(atm_k),
                "combined_straddle_cost": round(cost, 2),
                "expected_move_pct": round(move_pct, 4) if move_pct else None,
                "factor_basis": "PRACTITIONER_FAT_TAIL_ADJUSTED_CONVENTION",
                "state": "CALCULATED",
            }
        return {"state": "UNKNOWN", "reason": "insufficient_atm_quote_data"}