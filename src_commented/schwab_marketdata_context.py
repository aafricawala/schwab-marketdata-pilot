"""
schwab_marketdata_context.py

Purpose:
This module defines the central "Context" object for the calculator. Think of it as a specialized container or backpack that holds all the loaded market data (prices, history, options) in one place so that all the different calculation steps can easily access exactly what they need without passing dozens of variables around.

Prerequisites:
- Requires the `pandas` library to hold history and options data.
- Requires `schwab_utils.safe_float` to safely convert data.

What this module does:
1. Takes in raw JSON data, price history tables, options tables, and settings.
2. Stores them safely as properties on the object, making sure empty tables are created if data is missing.
3. Extracts the most critical numbers (like the last price, closing price, and market open status) for easy access.
4. Determines the "Calculated Spot Price" (the most accurate current price of the stock to use for math), preferring the price attached to the options data if available.
5. Records exactly where it got that spot price from and rates how "stale" or old it might be.

Configuration knobs:
- None. The 18,000 second (5 hour) threshold for determining if a quote is extremely stale is hardcoded.

Outputs:
- Produces a `MarketDataContext` object filled with organized data properties.

Notes:
- This is extracted directly from the original MasterThesisCalculator's initialization logic to keep the code organized, but behaves exactly the same way.
"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from schwab_utils import safe_float


class MarketDataContext:

    def __init__(
        # Reference to the object itself.
        self,
        raw_data: Dict[str, Any],
        price_history_df: pd.DataFrame,
        options_df: pd.DataFrame,
        params: Dict[str, Any],
    # End of the initialization arguments.
    ):
        self.raw = raw_data

        self.ph_df = (
            # ...using the provided data...
            price_history_df
            # ...but only if it is actually a valid pandas DataFrame table...
            if isinstance(price_history_df, pd.DataFrame)
            # ...otherwise, create an empty table so the code doesn't crash later.
            else pd.DataFrame()
        )

        self.opt_df = (
            # ...using the provided data if valid, otherwise creating an empty table.
            options_df if isinstance(options_df, pd.DataFrame) else pd.DataFrame()
        )

        self.params = params or {}

        self.quote_last = safe_float(
            # Look inside the 'phase_0_grounding' section of the raw data for the 'lastPrice'.
            self.raw.get("phase_0_grounding", {}).get("lastPrice")
        )

        self.close = safe_float(
            # Look for the 'closePrice' in the grounding section.
            self.raw.get("phase_0_grounding", {}).get("closePrice")
        )

        self.is_open = bool(
            # Look for the 'market_isOpen' flag, defaulting to False if it's missing.
            self.raw.get("phase_0_grounding", {}).get("market_isOpen", False)
        )

        self.quote_age = safe_float(
            # Look for the 'quote_age_seconds' in the grounding section.
            self.raw.get("phase_0_grounding", {}).get("quote_age_seconds")
        )

        self.q_class = str(
            # Look for the 'quote_age_classification', defaulting to an empty string if missing.
            self.raw.get("phase_0_grounding", {}).get("quote_age_classification") or ""
        )

        self.fund = self.raw.get("step_1_fundamentals", {})

        self.deriv = self.raw.get("step_3_and_7_derivatives", {})

        u_p = safe_float(
            # Look inside the derivatives surface parameters for the 'underlyingPrice'.
            self.deriv.get("surface_parameters", {}).get("underlyingPrice")
        )

        is_stale_quote = (
            # It is stale if the quote is more than 18,000 seconds (5 hours) old...
            (self.quote_age is not None and self.quote_age > 18000.0)
            # ...or if the API explicitly labeled the quote classification as 'STALE'.
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