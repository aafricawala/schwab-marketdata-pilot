"""
schwab_step5_realized_vol.py

Purpose:
This module provides a calculator for historical realized volatility of an asset over multiple time horizons (10-day, 30-day, and 252-day). It uses different mathematical estimators (Close-to-Close, Parkinson, Garman-Klass) to measure how much an asset's price has fluctuated in the past, aiding in risk assessment and option pricing comparisons.

Prerequisites:
- Requires standard numerical and data analysis libraries: `numpy` and `pandas`.
- Input data must be a Pandas DataFrame containing 'open', 'high', 'low', and 'close' price columns.

What this module does:
1. Calculates historical price volatility across short (10-day), intermediate (30-day), and macroeconomic (252-day) timeframes.
2. Applies the standard Close-to-Close volatility estimator.
3. Applies advanced estimators (Parkinson, Garman-Klass) that incorporate intraday high/low/open prices for more accurate volatility measurement.
4. Checks for data sufficiency, returning partial or insufficient history states if too few trading days are available.
5. Identifies and suppresses extreme or anomalous volatility readings to prevent skewed analytics.

Configuration knobs:
- Built-in minimum bar requirements (e.g., 8 bars for a 10-day window, 180 bars for a 252-day window).
- Built-in thresholds for "extreme dispersion" (e.g., volatility > 200%, or > 100% difference between estimators).

Outputs:
- A dictionary containing nested volatility metrics and state indicators for the 10d, 30d, and 252d horizons.

Notes:
- The estimators assume 252 trading days in a year for annualization.
- Volatility is returned as a percentage (e.g., 25.0 means 25% annualized volatility).
"""
# Enable modern Python type hint features even in older versions of Python.
from __future__ import annotations

# Import typing helpers to describe data structures like dictionaries and any-type variables.
from typing import Any, Dict

# Import the numpy library (aliased as np) for fast numerical math operations.
import numpy as np
# Import the pandas library (aliased as pd) for working with complex tables of data.
import pandas as pd


# Define a class to encapsulate all realized volatility calculation logic.
class Step5RealizedVolCalculator:

    # Define the main public method that orchestrates volatility calculations across multiple time horizons.
    def calculate_suite(self, df: pd.DataFrame) -> Dict[str, Any]:
        # Get the total number of rows (trading days/bars) in the provided DataFrame.
        n = len(df)
        # If we have less than 2 rows, we can't calculate even a single return.
        if n < 2:
            # Return an unknown state indicating there is not enough data.
            return {"state": "UNKNOWN", "reason": "insufficient_bars_for_returns"}
        # Initialize the result dictionary with a success state.
        res: Dict[str, Any] = {"state": "CALCULATED"}
        # Calculate the 10-day (tactical/short-term) volatility using the last 11 days of data, requiring at least 8 days.
        res["10d_tactical"] = self._calc_rv_horizon(df.tail(11), 10, min_bars=8)
        # Calculate the 30-day (intermediate) volatility using the last 31 days of data, requiring at least 20 days.
        res["30d_intermediate"] = self._calc_rv_horizon(df.tail(31), 30, min_bars=20)
        # Calculate the 252-day (macro/annual) volatility using up to 253 days of data, requiring 180 days, and tracking listing age.
        res["252d_macro"] = self._calc_rv_horizon(df.tail(253), 252, min_bars=180, check_seasoning=True, total_avail=n)
        # Return the complete suite of volatility metrics.
        return res

    # Define an internal helper method to calculate volatility over a specific time window.
    def _calc_rv_horizon(
        # Reference to the object itself.
        self,
        # The historical price data to analyze.
        df: pd.DataFrame,
        # The ideal number of trading days for this horizon.
        target_win: int,
        # The minimum acceptable number of trading days to proceed with calculation.
        min_bars: int,
        # Whether to check if the stock is a new listing based on available history.
        check_seasoning: bool = False,
        # The total absolute number of trading days available in the full dataset.
        total_avail: int = 0,
    # Declare that this method returns a dictionary of volatility metrics.
    ) -> Dict[str, Any]:
        # Determine how many price bars were actually passed into this window.
        n_bars = len(df)
        # Calculate the number of possible return observations (which is always one less than the number of price bars).
        n_rets = max(0, n_bars - 1)
        # Initialize the Close-to-Close volatility variable as None.
        c2c_vol = None
        # Define string constants for the column names we expect in the DataFrame.
        c_col, h_col, l_col, o_col = "close", "high", "low", "open"

        # If we have enough data points to compute standard deviation and the 'close' column exists...
        if n_rets >= 2 and c_col in df.columns:
            # Calculate the daily logarithmic returns (ln(today_close / yesterday_close)) and drop the first empty row.
            log_ret = np.log(df[c_col] / df[c_col].shift(1)).dropna()
            # Compute the annualized standard deviation of the log returns (Close-to-Close volatility), expressed as a percentage.
            c2c_vol = float(log_ret.std(ddof=1) * np.sqrt(252) * 100.0) if len(log_ret) > 1 else None

        # If the actual number of data bars is less than the minimum required for this horizon...
        if n_bars < min_bars:
            # Prepare an error response dictionary indicating insufficient history.
            ret_dict: Dict[str, Any] = {
                # Mark the state as INSUFFICIENT_HISTORY.
                "state": "INSUFFICIENT_HISTORY",
                # Record the number of bars we were ideally looking for.
                "target_window_bars": target_win,
                # Record the actual number of bars we had available.
                "actual_sample_bars": n_bars,
                # Record how many daily returns could be calculated.
                "return_observations": n_rets,
                # Provide a reason string showing the specific minimum threshold that wasn't met.
                "reason": f"sample_bars_below_minimum_{min_bars}",
            # Close the dictionary.
            }
            # Even if data is insufficient for advanced models, if we managed to calculate basic Close-to-Close volatility...
            if c2c_vol is not None:
                # ...include it in the output for informational purposes.
                ret_dict["computed_realized_vol"] = round(c2c_vol, 2)
            # If we are checking the macro timeframe (asking if the stock is a new listing)...
            if check_seasoning:
                # Classify the stock as established or unseasoned based on whether it has about a year of trading history.
                ret_dict["listing_seasoning"] = "ESTABLISHED_LISTING" if total_avail >= 250 else "UNSEASONED_LISTING"
                # Include the absolute total number of trading days available in the dataset.
                ret_dict["total_available_bars"] = total_avail
            # Return the early-exit dictionary because we can't proceed to advanced calculations.
            return ret_dict

        # Calculate the log difference between the intraday high and low prices.
        hl = np.log(df[h_col] / df[l_col])
        # Calculate the log difference between the closing and opening prices.
        co = np.log(df[c_col] / df[o_col])
        # Calculate the Parkinson volatility estimator, which relies purely on high-low ranges, annualized to a percentage.
        park = float(np.sqrt((1.0 / (4.0 * np.log(2.0))) * (hl**2).mean()) * np.sqrt(252) * 100.0)
        # Calculate the Garman-Klass volatility estimator, combining high-low ranges and close-open ranges for higher efficiency.
        gk = float(np.sqrt((0.5 * (hl**2) - ((2.0 * np.log(2.0) - 1.0) * (co**2))).mean()) * np.sqrt(252) * 100.0)
        # Calculate the absolute dispersion (difference) between the standard Close-to-Close volatility and the Garman-Klass volatility.
        disp = abs((c2c_vol or gk) - gk)

        # Check if the volatility readings are extremely high or if the estimators disagree wildly (indicating anomalous data).
        if disp > 100.0 or gk > 200.0 or (c2c_vol is not None and c2c_vol > 200.0):
            # If anomalies are detected, prepare a 'suppressed' result dictionary to prevent bad data from polluting downstream analytics.
            suppressed_dict: Dict[str, Any] = {
                # Mark the state as UNKNOWN because the numbers are too extreme to trust.
                "state": "UNKNOWN",
                # Note the reason for suppression.
                "reason": "extreme_dispersion_regime_suppresses_estimator",
                # Record the number of bars we were ideally looking for.
                "target_window_bars": target_win,
                # Record the actual number of bars we had available.
                "actual_sample_bars": n_bars,
                # Record how many daily returns could be calculated.
                "return_observations": n_rets,
                # Include the calculated difference between estimators, so users can see how bad it was.
                "unsuppressed_dispersion_pp": round(disp, 4),
                # Include the raw Garman-Klass calculation for reference.
                "unsuppressed_garman_klass": round(gk, 4),
            # Close the dictionary.
            }
            # Even if data is insufficient for advanced models, if we managed to calculate basic Close-to-Close volatility...
            if c2c_vol is not None:
                # Include the standard Close-to-Close calculation for reference.
                suppressed_dict["unsuppressed_close_to_close"] = round(c2c_vol, 4)
            # If we are checking the macro timeframe (asking if the stock is a new listing)...
            if check_seasoning:
                # Classify the listing age.
                suppressed_dict["listing_seasoning"] = "ESTABLISHED_LISTING" if total_avail >= 250 else "UNSEASONED_LISTING"
                # Include total available history.
                suppressed_dict["total_available_bars"] = total_avail
            # Return the suppressed dictionary, aborting the normal return path.
            return suppressed_dict

        # Determine if we have a full dataset for the target window, or if we had enough to calculate but less than the ideal amount.
        st = "PARTIAL_HISTORY" if (target_win == 252 and n_bars < 252) else "FULL_HISTORY"
        # Prepare the final, successful response dictionary.
        ret: Dict[str, Any] = {
            # Set the status (FULL_HISTORY or PARTIAL_HISTORY).
            "status": st,
            # Record the actual number of bars we had available.
            "actual_sample_bars": n_bars,
            # Record how many daily returns could be calculated.
            "return_observations": n_rets,
            # Provide the standard Close-to-Close volatility, rounded to 4 decimal places.
            "close_to_close": round(c2c_vol, 4) if c2c_vol else None,
            # Provide the Parkinson volatility.
            "parkinson": round(park, 4),
            # Provide the Garman-Klass volatility (often the preferred, most efficient metric).
            "garman_klass": round(gk, 4),
            # Note the percentage point difference between the standard and advanced models.
            "estimator_dispersion_pp": round(disp, 4),
            # Cite the specific methodology of the primary advanced estimator used.
            "estimator_methodology": "Garman-Klass (1980) zero-drift invariant",
        }

        # If the estimators differ significantly (but not enough to be fully suppressed)...
        if disp > 40.0:
            # ...flag this specific horizon as having an extreme dispersion regime, warning the user of potential instability.
            ret["estimator_dispersion_regime"] = "EXTREME_DISPERSION"

        # If we are checking the macro timeframe (asking if the stock is a new listing)...
        if check_seasoning:
            # Append the listing seasoning status.
            ret["listing_seasoning"] = "ESTABLISHED_LISTING" if total_avail >= 250 else "UNSEASONED_LISTING"
            # Append the total available dataset length.
            ret["total_available_bars"] = total_avail
            # Provide extra context if we were able to compute the macro metric but didn't have a full year of data.
            if st == "PARTIAL_HISTORY":
                # Note that we hit the minimum requirement (e.g., 180 days) but fell short of the 252-day ideal target.
                ret["sample_bars_note"] = "lookback_satisfies_minimum_threshold_below_target"
        return ret