"""
schwab_marketdata_context.py
---
Purpose
    This module defines the central "Context" object for the calculator. Think of it as a specialized container or backpack that holds all the loaded market data (prices, history, options) in one place so that all the different calculation steps can easily access exactly what they need without passing dozens of variables around.

Prerequisites
    - Requires the `pandas` library to hold history and options data.
    - Requires `schwab_utils.safe_float` to safely convert data.

What this module does
    1. Takes in raw JSON data, price history tables, options tables, and settings.
    2. Stores them safely as properties on the object, making sure empty tables are created if data is missing.
    3. Extracts the most critical numbers (like the last price, closing price, and market open status) for easy access.
    4. Determines the "Calculated Spot Price" (the most accurate current price of the stock to use for math), preferring the price attached to the options data if available.
    5. Records exactly where it got that spot price from and rates how "stale" or old it might be.

Configuration knobs
    None. The 18,000 second (5 hour) threshold for determining if a quote is extremely stale is hardcoded.

Outputs
    Produces a `MarketDataContext` object filled with organized data properties.

Notes
    This is extracted directly from the original MasterThesisCalculator's initialization logic to keep the code organized, but behaves exactly the same way.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations

# Import typing helpers to describe that variables can be Any type or Dictionaries
from typing import Any, Dict

# Import the pandas library (aliased as pd) for working with complex tables of data (DataFrames)
import pandas as pd

# Import a utility function to safely turn text/messy data into a clean decimal number
from schwab_utils import safe_float


# Define the MarketDataContext class, which acts as the main container for all market data
class MarketDataContext:

    # The initialization method that runs when a new MarketDataContext is created
    def __init__(
        self,
        # A dictionary holding all the raw JSON data downloaded from Schwab
        raw_data: Dict[str, Any],
        # A pandas DataFrame holding the historical price candles
        price_history_df: pd.DataFrame,
        # A pandas DataFrame holding the options chain data
        options_df: pd.DataFrame,
        # A dictionary holding configuration parameters
        params: Dict[str, Any],
    ):
        # Store the raw JSON data directly on the object
        self.raw = raw_data

        # Safely store the price history DataFrame; if what was passed in isn't actually a DataFrame, create an empty one
        self.ph_df = (
            price_history_df
            if isinstance(price_history_df, pd.DataFrame)
            else pd.DataFrame()
        )

        # Safely store the options DataFrame; if what was passed in isn't actually a DataFrame, create an empty one
        self.opt_df = (
            options_df if isinstance(options_df, pd.DataFrame) else pd.DataFrame()
        )

        # Store the parameters dictionary, or create an empty one if none was provided
        self.params = params or {}

        # Extract the last traded price from the 'phase_0_grounding' section of the raw data, safely converting it to a float
        self.quote_last = safe_float(
            self.raw.get("phase_0_grounding", {}).get("lastPrice")
        )

        # Extract the previous day's closing price from the 'phase_0_grounding' section, safely converting it to a float
        self.close = safe_float(
            self.raw.get("phase_0_grounding", {}).get("closePrice")
        )

        # Check if the market is currently open by looking for the 'market_isOpen' flag, defaulting to False
        self.is_open = bool(
            self.raw.get("phase_0_grounding", {}).get("market_isOpen", False)
        )

        # Extract how old the current quote is in seconds, safely converting it to a float
        self.quote_age = safe_float(
            self.raw.get("phase_0_grounding", {}).get("quote_age_seconds")
        )

        # Extract the text classification of the quote's age (e.g., 'STALE', 'DELAYED', 'REALTIME')
        self.q_class = str(
            self.raw.get("phase_0_grounding", {}).get("quote_age_classification") or ""
        )

        # Store a shortcut to the 'step_1_fundamentals' section of the raw data (company info, metrics, etc.)
        self.fund = self.raw.get("step_1_fundamentals", {})

        # Store a shortcut to the 'step_3_and_7_derivatives' section of the raw data (options summary info)
        self.deriv = self.raw.get("step_3_and_7_derivatives", {})

        # Try to find the underlying stock price embedded specifically within the options data (often more accurate during trading hours)
        u_p = safe_float(
            self.deriv.get("surface_parameters", {}).get("underlyingPrice")
        )

        # Determine if the stock price quote we have is considered highly stale (either over 5 hours old or explicitly marked STALE)
        is_stale_quote = (
            (self.quote_age is not None and self.quote_age > 18000.0)
            or (self.q_class == "STALE")
        )

        # Decide which stock price to use as the "official" price for all following math calculations (calc_spot)
        # If we successfully found a price embedded in the options data:
        if u_p is not None:
            # Use the options underlying price
            self.calc_spot = u_p
            # Record exactly where we got this price from so we can track it later
            self.spot_source = "options_payload_underlyingPrice"
            # Mark the "vintage" (staleness risk) as LOW because options prices are usually very fresh
            self.spot_vintage = "LOW"
        # If we didn't find an options price:
        else:
            # Fall back to using the standard last traded price from the main quote
            self.calc_spot = self.quote_last
            # Record that we used the standard quote price
            self.spot_source = "phase_0_grounding_last_price"
            # If we already decided the quote was stale, mark the vintage risk as HIGH, otherwise mark it MEDIUM
            self.spot_vintage = "HIGH" if is_stale_quote else "MEDIUM"