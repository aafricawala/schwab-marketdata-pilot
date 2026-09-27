"""
schwab_step0_grounding.py

Step 0: session gap grounding. Body moved verbatim from _calc_step_0.
"""
from __future__ import annotations

from typing import Any, Dict

from schwab_marketdata_context import MarketDataContext
from schwab_utils import safe_div


class Step0GroundingCalculator:

    def __init__(self, ctx: MarketDataContext):
        self.ctx = ctx

    def calculate(self) -> Dict[str, Any]:
        if self.ctx.q_class == "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED":
            return {
                "session_gap_pct": None,
                "state": "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED",
                "session_gap_anchor": "PRIOR_SESSION_CLOSE_QUOTE",
            }
        gap = (
            safe_div((self.ctx.quote_last - self.ctx.close) * 100.0, self.ctx.close)
            if self.ctx.quote_last is not None and self.ctx.close is not None
            else None
        )
        if self.ctx.is_open and self.ctx.quote_age is not None and self.ctx.quote_age > 3600.0:
            st = "STALE_QUOTE"
        else:
            st = "CALCULATED" if gap is not None else "UNKNOWN"
        return {
            "session_gap_pct": round(gap, 4) if gap is not None else None,
            "state": st,
            "session_gap_anchor": "PRIOR_SESSION_CLOSE_QUOTE",
        }