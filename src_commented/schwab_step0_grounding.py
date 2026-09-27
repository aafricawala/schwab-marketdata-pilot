"""
schwab_step0_grounding.py
---
Purpose
    This module performs the very first step (Step 0) of market data calculations. It calculates the "session gap," which is the percentage difference between a stock's current price and its closing price from the previous day. This helps determine how much the stock "gapped" up or down overnight or since the last close.

Prerequisites
    - A populated `MarketDataContext` object that holds current and historical price data for a stock.

What this module does
    1. Checks if the stock is currently halted or completely unavailable.
    2. If available, calculates the percentage difference between the last known price and the previous close price.
    3. Checks if the quote data is "stale" (meaning the market is open but the price hasn't updated in over an hour).
    4. Packages the calculated gap percentage and the state of the data into a dictionary for the next steps to use.

Configuration knobs
    None. The 3600.0 seconds (1 hour) threshold for stale quotes is hardcoded.

Outputs
    Returns a dictionary containing:
    - `session_gap_pct`: The calculated gap as a percentage (rounded to 4 decimal places), or None.
    - `state`: A string describing the state of the calculation ('UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED', 'STALE_QUOTE', 'CALCULATED', or 'UNKNOWN').
    - `session_gap_anchor`: A string hardcoded to "PRIOR_SESSION_CLOSE_QUOTE" to indicate what the gap was measured against.

Notes
    This is extracted directly from older monolithic code to keep things organized.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations

# Import typing helpers to describe that variables can be Any type or Dictionaries
from typing import Any, Dict

# Import the main context object that holds all the loaded data about a stock
from schwab_marketdata_context import MarketDataContext
# Import a utility function that safely performs division without crashing if the denominator is zero
from schwab_utils import safe_div


# Define a class that handles the Step 0 calculations
class Step0GroundingCalculator:

    # The initialization method that runs when a new Step0GroundingCalculator is created
    def __init__(self, ctx: MarketDataContext):
        # Store the provided market data context object inside the class so other methods can access it
        self.ctx = ctx

    # Define the main calculate method that performs the work and returns a dictionary of results
    def calculate(self) -> Dict[str, Any]:
        # Check if the context flagged this stock as completely halted or unquoted
        if self.ctx.q_class == "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED":
            # If it is halted, return a hardcoded dictionary saying no calculations can be done
            return {
                # We can't calculate a gap percentage, so set it to None
                "session_gap_pct": None,
                # Explicitly state that the asset is halted or unquoted
                "state": "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED",
                # Indicate what we would have compared it to, if we had data
                "session_gap_anchor": "PRIOR_SESSION_CLOSE_QUOTE",
            }

        # Calculate the actual gap percentage
        gap = (
            # Subtract yesterday's close from the last price, multiply by 100 for a percentage, and safely divide by the close
            safe_div((self.ctx.quote_last - self.ctx.close) * 100.0, self.ctx.close)
            # ONLY do this math if both the last price and the close price actually exist (are not None)
            if self.ctx.quote_last is not None and self.ctx.close is not None
            # Otherwise, just set the gap to None
            else None
        )

        # Check if the market is open AND we know how old the quote is AND the quote is older than 3600 seconds (1 hour)
        if self.ctx.is_open and self.ctx.quote_age is not None and self.ctx.quote_age > 3600.0:
            # If all that is true, mark the state (st) as a 'STALE_QUOTE' because it hasn't updated in too long
            st = "STALE_QUOTE"
        # If the quote is fresh or the market is closed
        else:
            # Mark the state as 'CALCULATED' if we successfully computed the gap, otherwise mark it 'UNKNOWN'
            st = "CALCULATED" if gap is not None else "UNKNOWN"

        # Return the final dictionary of results
        return {
            # Return the gap percentage rounded to 4 decimal places, or None if we didn't calculate one
            "session_gap_pct": round(gap, 4) if gap is not None else None,
            # Return the state we determined above
            "state": st,
            # Return the anchor indicating we compared the current price to the previous session's close
            "session_gap_anchor": "PRIOR_SESSION_CLOSE_QUOTE",
        }