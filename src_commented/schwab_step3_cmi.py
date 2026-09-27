"""
schwab_step3_cmi.py
---
Purpose
    This module calculates the "Constant-Maturity 30-day Implied Volatility" (CMI). Because options expire on specific dates (e.g., 20 days away or 40 days away), there is rarely an option that expires exactly 30 days from today. This module finds the two expirations closest to 30 days (one before, one after) and mathematically interpolates between them to estimate exactly what a 30-day option's volatility would be.

Prerequisites
    - A populated `MarketDataContext` object containing the calculated spot (stock) price.
    - A valid Pandas DataFrame containing options chain data (with columns for days to expiration, strike price, and volatility).

What this module does
    1. Validates the incoming options data to ensure it has the required columns.
    2. Identifies all available expiration dates (days to expiration).
    3. Finds the expiration date closest to, but less than or equal to, 30 days (`t1`).
    4. Finds the expiration date closest to, but greater than or equal to, 30 days (`t2`).
    5. Calculates the time gap between `t1` and `t2` to determine how "tight" or "wide" the interpolation bracket is.
    6. Uses a helper function to find the At-The-Money (ATM) implied volatility for both `t1` and `t2`.
    7. Uses a weighted average (interpolation) based on how close `t1` and `t2` are to 30 days to calculate the final 30-day IV.
    8. Returns the calculated 30-day IV and the bracket details in a dictionary.

Configuration knobs
    None. The 30-day target is hardcoded into the mathematical logic.

Outputs
    Returns a dictionary containing:
    - The calculated 30-day implied volatility (`constant_maturity_30d_iv`).
    - The state of the calculation ('CALCULATED' or 'UNKNOWN').
    - The two expiration dates used for the bracket (`t1_dte` and `t2_dte`).
    - The number of days between the two bracket dates (`bracket_span_days`).
    - A quality rating of the bracket ('TIGHT', 'WIDE', or 'DEGENERATE_SINGLE_EXPIRATION').
    - Or, if it fails, a reason why it failed.

Notes
    If the API returns invalid or missing volatility data (e.g., negative numbers or missing columns), the module safely aborts and returns an 'UNKNOWN' state.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations

# Import typing helpers to describe that variables can be Any type, Dictionaries, or Optional (might be None)
from typing import Any, Dict, Optional

# Import the pandas library (aliased as pd) for working with complex tables of data (DataFrames)
import pandas as pd

# Import the main context object that holds all the loaded data about a stock
from schwab_marketdata_context import MarketDataContext


# Define a class that handles the Step 3 Constant Maturity Implied Volatility calculations
class Step3CMICalculator:

    # The initialization method that runs when a new Step3CMICalculator is created
    def __init__(self, ctx: MarketDataContext):
        # Store the provided market data context object inside the class so other methods can access it
        self.ctx = ctx

    # Define the main calculate method that takes a table of options data (DataFrame) and returns a dictionary of results
    def calculate(self, df: pd.DataFrame) -> Dict[str, Any]:
        # Check if the table is empty, OR if it's missing the 'daysToExpiration' column, OR if it's missing 'strikePrice'
        if df.empty or "daysToExpiration" not in df.columns or "strikePrice" not in df.columns:
            # If any of those are true, we can't calculate anything, so return a failure dictionary
            return {
                "state": "UNKNOWN",
                "reason": "options_chain_empty_or_unavailable",
            }

        # Look at the 'daysToExpiration' column, drop empty rows, convert to integers, keep only future dates (>= 0), remove duplicates, and sort
        dtes = sorted(
            list({int(d) for d in df["daysToExpiration"].dropna() if int(d) >= 0})
        )

        # If there are no valid expiration dates left after filtering
        if not dtes:
            # Return a failure dictionary
            return {"state": "UNKNOWN", "reason": "no_valid_expirations"}

        # Create a list of all expiration dates that are 30 days away or closer
        t1_cand = [d for d in dtes if d <= 30]
        # Create a list of all expiration dates that are 30 days away or further
        t2_cand = [d for d in dtes if d >= 30]

        # For the lower bracket (t1), pick the largest number from the t1 list. If the list is empty, just use the absolute closest expiration date available.
        t1 = t1_cand[-1] if t1_cand else dtes[0]
        # For the upper bracket (t2), pick the smallest number from the t2 list. If the list is empty, just use the absolute furthest expiration date available.
        t2 = t2_cand[0] if t2_cand else dtes[-1]

        # Calculate how many days are between our lower and upper brackets
        span = abs(t2 - t1)

        # Grade the quality of our brackets based on how far apart they are
        quality = (
            # If the two dates are exactly the same, it's a degenerate (poor) single point
            "DEGENERATE_SINGLE_EXPIRATION"
            if span == 0
            # If they are 10 days or less apart, it's a "TIGHT" (good) bracket, otherwise it's "WIDE" (less accurate)
            else ("TIGHT" if span <= 10 else "WIDE")
        )

        # Define an internal helper function that gets the average implied volatility for a specific expiration date
        def get_mean_iv(dte_val: int) -> Optional[float]:
            # Filter the options table to only include options expiring on this exact date
            sub = df[df["daysToExpiration"] == dte_val]
            # If the filtered table is empty or doesn't have a volatility column
            if sub.empty or "volatility" not in sub.columns:
                # Return None because we can't calculate IV
                return None

            # Add a new column calculating the absolute distance between each strike price and the current stock price
            sub = sub.assign(d_diff=(sub["strikePrice"] - self.ctx.calc_spot).abs())
            # Find the strike price that has the smallest distance (the At-The-Money strike)
            atm_k = sub.loc[sub["d_diff"].idxmin(), "strikePrice"]

            # Get all the volatility numbers for options exactly at that At-The-Money strike, dropping any empty values
            vols = sub[sub["strikePrice"] == atm_k]["volatility"].dropna()

            # Calculate the mathematical average (mean) of those volatilities and return it, or return None if there were none
            return float(vols.mean()) if not vols.empty else None

        # Call the helper function to get the IV for our lower bracket (t1) and upper bracket (t2)
        iv1, iv2 = get_mean_iv(t1), get_mean_iv(t2)

        # Check if either IV failed to calculate (is None) or if they returned an invalid negative/zero number
        if iv1 is None or iv2 is None or iv1 <= 0.0 or iv2 <= 0.0:
            # If they are invalid, return a failure dictionary explaining we hit bad data
            return {
                "constant_maturity_30d_iv": None,
                "state": "UNKNOWN",
                "reason": "invalid_iv_sentinel_detected",
                "t1_dte": t1,
                "t2_dte": t2,
                "bracket_span_days": span,
                "bracket_quality": quality,
            }

        # If both brackets actually landed on the exact same date (e.g., exactly 30 days)
        if t1 == t2:
            # The 30-day IV is just exactly the IV of that date
            iv30 = iv1
        # If the dates are different, we need to interpolate (blend) them together
        else:
            # Calculate the weight for the lower bracket (closer to 30 gets more weight) and the upper bracket
            w1, w2 = abs(t2 - 30) / float(span or 1), abs(30 - t1) / float(span or 1)
            # Multiply each IV by its weight and add them together to get the final blended 30-day IV
            iv30 = (iv1 * w1) + (iv2 * w2)

        # Return the successful calculation results as a dictionary
        return {
            # The final 30-day IV, rounded to 4 decimal places
            "constant_maturity_30d_iv": round(iv30, 4),
            # Mark the state as successfully calculated
            "state": "CALCULATED",
            # Include the metadata about the brackets we used
            "t1_dte": t1,
            "t2_dte": t2,
            "bracket_span_days": span,
            "bracket_quality": quality,
        }