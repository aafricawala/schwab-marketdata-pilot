"""
schwab_marketdata_context.py

Shared context object holding grounding state, dataframes, params, and the
derived calculation spot + provenance. Initialization logic is identical to
the original MasterThesisCalculator.__init__; only the class name changed.
"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from schwab_utils import safe_float


class MarketDataContext:

    def __init__(
        self,
        raw_data: Dict[str, Any],
        price_history_df: pd.DataFrame,
        options_df: pd.DataFrame,
        params: Dict[str, Any],
    ):
        self.raw = raw_data
        self.ph_df = (
            price_history_df
            if isinstance(price_history_df, pd.DataFrame)
            else pd.DataFrame()
        )
        self.opt_df = (
            options_df if isinstance(options_df, pd.DataFrame) else pd.DataFrame()
        )
        self.params = params or {}
        self.quote_last = safe_float(
            self.raw.get("phase_0_grounding", {}).get("lastPrice")
        )
        self.close = safe_float(
            self.raw.get("phase_0_grounding", {}).get("closePrice")
        )
        self.is_open = bool(
            self.raw.get("phase_0_grounding", {}).get("market_isOpen", False)
        )
        self.quote_age = safe_float(
            self.raw.get("phase_0_grounding", {}).get("quote_age_seconds")
        )
        self.q_class = str(
            self.raw.get("phase_0_grounding", {}).get("quote_age_classification") or ""
        )
        self.fund = self.raw.get("step_1_fundamentals", {})
        self.deriv = self.raw.get("step_3_and_7_derivatives", {})
        u_p = safe_float(
            self.deriv.get("surface_parameters", {}).get("underlyingPrice")
        )

        is_stale_quote = (
            (self.quote_age is not None and self.quote_age > 18000.0)
            or (self.q_class == "STALE")
        )
        if u_p is not None:
            self.calc_spot = u_p
            self.spot_source = "options_payload_underlyingPrice"
            self.spot_vintage = "LOW"
        else:
            self.calc_spot = self.quote_last
            self.spot_source = "phase_0_grounding_last_price"
            self.spot_vintage = "HIGH" if is_stale_quote else "MEDIUM"