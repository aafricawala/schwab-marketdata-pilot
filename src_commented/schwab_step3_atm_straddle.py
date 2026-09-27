"""
schwab_step3_atm_straddle.py
---
Purpose
    This module calculates the cost of an "At-The-Money (ATM) Straddle" for the closest expiration date (front-expiry). A straddle involves buying both a call and a put option at the same strike price. It also calculates the "expected move," which is an estimate of how much the stock price might change based on the straddle's cost, adjusted by a common rule-of-thumb factor used by traders.

Prerequisites
    - A populated `MarketDataContext` object containing the current spot (stock) price.
    - A valid Pandas DataFrame containing options chain data (with columns for days to expiration, strike price, put/call indicator, and mark price).

What this module does
    1. Checks if the options data exists and has the required columns.
    2. Finds the closest upcoming expiration date (the lowest number of days to expiration).
    3. Filters the options data to only include contracts for that specific expiration date.
    4. Finds the "At-The-Money" strike price, which is the strike price closest to the stock's current price.
    5. Retrieves the current market price ("mark") for both the Put and the Call option at that strike.
    6. Adds the prices together to find the total cost of the straddle.
    7. Calculates the expected percentage move by taking 85% of the straddle cost and dividing it by the stock's price.
    8. Returns all these calculated values in a dictionary.

Configuration knobs
    None. The 0.85 multiplier (85%) used in the expected move calculation is a hardcoded industry convention.

Outputs
    Returns a dictionary containing:
    - The state of the calculation ('CALCULATED' or 'UNKNOWN').
    - The number of days to the front expiration (`front_expiry_dte`).
    - The chosen ATM strike price (`atm_strike`).
    - The total cost of the straddle (`combined_straddle_cost`).
    - The calculated expected move percentage (`expected_move_pct`).
    - A note indicating the formula used (`factor_basis`).
    - Or, if it fails, a reason why it failed (e.g., 'no_valid_expirations').

Notes
    The 0.85 (85%) factor applied to the straddle cost is often called a "practitioner's fat-tail adjustment" used by options traders to estimate the expected move range.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations

# Import typing helpers to describe that variables can be Any type or Dictionaries
from typing import Any, Dict

# Import the pandas library (aliased as pd) for working with complex tables of data (DataFrames)
import pandas as pd

# Import the main context object that holds all the loaded data about a stock
from schwab_marketdata_context import MarketDataContext
# Import utility functions for safely dividing numbers and safely converting text/types to float numbers
from schwab_utils import safe_div, safe_float


# Define a class that handles the Step 3 ATM Straddle calculations
class Step3ATMStraddleCalculator:

    # The initialization method that runs when a new Step3ATMStraddleCalculator is created
    def __init__(self, ctx: MarketDataContext):
        # Store the provided market data context object inside the class so other methods can access it
        self.ctx = ctx

    # Define the main calculate method that takes a table of options data (DataFrame) and returns a dictionary of results
    def calculate(self, df: pd.DataFrame) -> Dict[str, Any]:
        # Check if the table is totally empty, OR if it's missing the 'daysToExpiration' column, OR if it's missing the 'strikePrice' column
        if df.empty or "daysToExpiration" not in df.columns or "strikePrice" not in df.columns:
            # If any of those are true, we can't calculate anything, so return a failure dictionary
            return {"state": "UNKNOWN", "reason": "no_valid_expirations"}

        # Look at the 'daysToExpiration' column, drop any empty rows, convert them to whole numbers (integers),
        # keep only the ones that are 0 or greater (in the future), remove duplicates using a set, and sort them into a list from lowest to highest
        dtes = sorted(list({int(d) for d in df["daysToExpiration"].dropna() if int(d) >= 0}))

        # If the list of valid expiration days is empty after filtering
        if not dtes:
            # Return a failure dictionary because there are no valid future options
            return {"state": "UNKNOWN", "reason": "no_valid_expirations"}

        # Get the very first item in the sorted list, which is the closest expiration date (front-expiry)
        f_dte = dtes[0]

        # Filter the main table to create a smaller table ('sub') that ONLY contains options expiring on that closest date
        sub = df[df["daysToExpiration"] == f_dte].copy()

        # If for some reason this smaller table is empty
        if sub.empty:
            # Return a failure dictionary
            return {"state": "UNKNOWN", "reason": "insufficient_atm_quote_data"}

        # Create a new column in the smaller table called 'd_diff' that calculates the absolute distance between each strike price and the current stock price
        sub["d_diff"] = (sub["strikePrice"] - self.ctx.calc_spot).abs()

        # Find the row with the smallest 'd_diff' (the closest strike to the stock price) and get its 'strikePrice' value
        atm_k = sub.loc[sub["d_diff"].idxmin(), "strikePrice"]

        # Filter the smaller table again to get ONLY the 'PUT' option at that exact strike price
        p_sub = sub[(sub["strikePrice"] == atm_k) & (sub["putCallIndicator"] == "PUT")]

        # Filter the smaller table again to get ONLY the 'CALL' option at that exact strike price
        c_sub = sub[(sub["strikePrice"] == atm_k) & (sub["putCallIndicator"] == "CALL")]

        # If we found a Put option, safely convert its 'mark' (market price) to a number; otherwise, set it to None
        p_mark = safe_float(p_sub["mark"].iloc[0]) if not p_sub.empty else None

        # If we found a Call option, safely convert its 'mark' (market price) to a number; otherwise, set it to None
        c_mark = safe_float(c_sub["mark"].iloc[0]) if not c_sub.empty else None

        # Check that we successfully got a price for both the Put and the Call, AND that we have a valid stock price
        if p_mark is not None and c_mark is not None and self.ctx.calc_spot:
            # Add the price of the Put and the Call together to get the total straddle cost
            cost = p_mark + c_mark

            # Calculate the expected move: multiply the cost by 85%, turn it into a percentage, and safely divide by the stock price
            move_pct = safe_div(cost * 0.85 * 100.0, self.ctx.calc_spot)

            # Return the successful calculation results as a dictionary
            return {
                # The days to expiration we used
                "front_expiry_dte": f_dte,
                # The At-The-Money strike price we selected (converted to a float just in case)
                "atm_strike": float(atm_k),
                # The total cost of the straddle, rounded to 2 decimal places (like dollars and cents)
                "combined_straddle_cost": round(cost, 2),
                # The expected move percentage, rounded to 4 decimal places (if we successfully calculated it)
                "expected_move_pct": round(move_pct, 4) if move_pct else None,
                # A hardcoded string explaining why we multiplied by 0.85
                "factor_basis": "PRACTITIONER_FAT_TAIL_ADJUSTED_CONVENTION",
                # Mark the state as successfully calculated
                "state": "CALCULATED",
            }

        # If we didn't have valid prices for the Put, Call, or Stock, return a failure dictionary
        return {"state": "UNKNOWN", "reason": "insufficient_atm_quote_data"}