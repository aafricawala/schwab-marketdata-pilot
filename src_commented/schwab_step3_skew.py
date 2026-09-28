"""
schwab_step3_skew.py

Purpose:
This module calculates the options "volatility skew" for a 30-day timeframe (tenor). Skew measures the difference in implied volatility between out-of-the-money puts and calls (specifically around the 25-delta mark). This indicates whether the market is pricing more risk to the downside (standard put skew) or upside (reverse call skew).

Prerequisites:
- Requires the `pandas` library for analyzing option chains.
- Requires `MarketDataContext` from `schwab_marketdata_context` to access current market data and configuration limits.
- Requires utility functions `safe_div` and `safe_float` from `schwab_utils` for safe math operations.

What this module does:
1. Filters the option chain to find the expiration date closest to 30 days.
2. Identifies the put and call options whose deltas are closest to 25 (0.25 absolute delta).
3. Verifies that the bid-ask spreads on these specific options aren't excessively wide to ensure the data is trustworthy (spread gate).
4. Calculates the difference in implied volatility between the selected put and call.
5. Classifies the type of skew (standard vs. reverse) and flags whether the selected options were perfectly symmetric or if it had to use a fallback nearest match.

Configuration knobs:
- `MAX_SKEW_RELATIVE_SPREAD`: A tolerance limit set in the context parameters (defaulting to 0.50 or 50% of the midpoint) dictating how wide a bid-ask spread can be before the option is rejected as untrustworthy.

Outputs:
- A dictionary containing the calculated skew differential, the skew regime classification, data quality flags (anchor labels), and references to the chosen expiration.

Notes:
- The function will abort and return "UNKNOWN" states if no valid expiration exists, if delta data is missing, or if the bid-ask spreads fail the quality checks.
"""
# Enable modern Python type hint features even in older versions of Python.
from __future__ import annotations

# Import typing helpers to describe data structures like dictionaries and any-type variables.
from typing import Any, Dict

# Import the pandas library (aliased as pd) for working with complex tables of data (DataFrames).
import pandas as pd

# Import the MarketDataContext class to access shared market data and settings.
from schwab_marketdata_context import MarketDataContext
# Import utility functions for safe division and safe decimal conversion to prevent crashes.
from schwab_utils import safe_div, safe_float


# Define a class responsible for calculating option volatility skew.
class Step3SkewCalculator:

    # Initialize the calculator with the shared MarketDataContext object.
    def __init__(self, ctx: MarketDataContext):
        # Store the context so we can access parameters and data later.
        self.ctx = ctx

    # Define the main method to calculate skew.
    def calculate(
        # Accept the options DataFrame and the Constant Maturity Implied (CMI) block data.
        self, df: pd.DataFrame, cmi_block: Dict[str, Any]
    # Declare that this method will return a dictionary containing the skew analysis results.
    ) -> Dict[str, Any]:
        # Safely extract the 'bracket span' (how many days between the chosen expirations) from the CMI block.
        b_span = cmi_block.get("bracket_span_days")
        # Safely extract the 'bracket quality' rating from the CMI block.
        b_qual = cmi_block.get("bracket_quality")
        # Check if the options data is empty or missing crucial columns like DTE or option type.
        if df.empty or "daysToExpiration" not in df.columns or "putCallIndicator" not in df.columns:
            # If data is missing, prepare a rejection dictionary.
            ret = {
                # Mark the state as UNKNOWN because calculation is impossible.
                "state": "UNKNOWN",
                # Specify the failure reason: no valid days to expiration.
                "reason": "no_valid_dte_for_skew",
                # Note that it failed before we could even pick options to compare.
                "skew_delta_anchor": "REJECTED_BEFORE_SELECTION",
                # Note that the skew regime cannot be determined.
                "skew_regime": "UNKNOWN",
            # Close the dictionary.
            }
            # Pass through the bracket span if it was provided.
            if b_span is not None:
                # Add the bracket span to the output dictionary.
                ret["bracket_span_days"] = b_span
            # Pass through the bracket quality if it was provided.
            if b_qual:
                # Add the bracket quality to the output dictionary.
                ret["bracket_quality"] = b_qual
            # Return the dictionary.
            return ret
        # Get a sorted list of unique Days to Expiration (DTEs) present in the chain.
        dtes = sorted(
            # Convert to integers, remove empties, and ensure they are not expired (>= 0).
            list({int(d) for d in df["daysToExpiration"].dropna() if int(d) >= 0})
        # Close the DTE list creation.
        )
        # If there are no valid future expiration dates left, we cannot calculate skew.
        if not dtes:
            # If data is missing, prepare a rejection dictionary.
            ret = {
                # Mark the state as UNKNOWN because calculation is impossible.
                "state": "UNKNOWN",
                # Specify the failure reason: no valid days to expiration.
                "reason": "no_valid_dte_for_skew",
                # Note that it failed before we could even pick options to compare.
                "skew_delta_anchor": "REJECTED_BEFORE_SELECTION",
                # Note that the skew regime cannot be determined.
                "skew_regime": "UNKNOWN",
            # Close the dictionary.
            }
            # Pass through the bracket span if it was provided.
            if b_span is not None:
                # Add the bracket span to the output dictionary.
                ret["bracket_span_days"] = b_span
            # Pass through the bracket quality if it was provided.
            if b_qual:
                # Add the bracket quality to the output dictionary.
                ret["bracket_quality"] = b_qual
            # Return the dictionary.
            return ret
        # Find the specific expiration date (target DTE) that is mathematically closest to exactly 30 days.
        t_dte = min(dtes, key=lambda d: abs(d - 30))
        # Create a smaller DataFrame ('sub') containing only the options for that target expiration.
        sub = df[df["daysToExpiration"] == t_dte]
        # Verify that the options data actually includes the 'delta' metric needed for skew math.
        if "delta" not in sub.columns:
            # If data is missing, prepare a rejection dictionary.
            ret = {
                # Record the DTE we are evaluating.
                "skew_tenor_dte": t_dte,
                # Mark the state as UNKNOWN because calculation is impossible.
                "state": "UNKNOWN",
                # Specify the failure reason: delta data is missing.
                "reason": "missing_wing_delta_contracts",
                # Note that it failed before we could even pick options to compare.
                "skew_delta_anchor": "REJECTED_BEFORE_SELECTION",
                # Note that the skew regime cannot be determined.
                "skew_regime": "UNKNOWN",
            # Close the dictionary.
            }
            # Pass through the bracket span if it was provided.
            if b_span is not None:
                # Add the bracket span to the output dictionary.
                ret["bracket_span_days"] = b_span
            # Pass through the bracket quality if it was provided.
            if b_qual:
                # Add the bracket quality to the output dictionary.
                ret["bracket_quality"] = b_qual
            # Return the dictionary.
            return ret
        # Filter the data to only PUTs, and add a new column...
        puts = sub[sub["putCallIndicator"] == "PUT"].assign(
            # ...that calculates how far each option's absolute delta is from the 0.25 target.
            d_diff=(sub["delta"].abs() - 0.25).abs()
        # Close the DTE list creation.
        )
        # Filter the data to only CALLs, and add a new column for delta difference.
        calls = sub[sub["putCallIndicator"] == "CALL"].assign(
            # ...that calculates how far each option's absolute delta is from the 0.25 target.
            d_diff=(sub["delta"].abs() - 0.25).abs()
        # Close the DTE list creation.
        )
        # Check if we completely lack either puts or calls for this expiration.
        if puts.empty or calls.empty:
            # If data is missing, prepare a rejection dictionary.
            ret = {
                # Record the DTE we are evaluating.
                "skew_tenor_dte": t_dte,
                # Mark the state as UNKNOWN because calculation is impossible.
                "state": "UNKNOWN",
                # Specify the failure reason: delta data is missing.
                "reason": "missing_wing_delta_contracts",
                # Note that it failed before we could even pick options to compare.
                "skew_delta_anchor": "REJECTED_BEFORE_SELECTION",
                # Note that the skew regime cannot be determined.
                "skew_regime": "UNKNOWN",
            # Close the dictionary.
            }
            # Pass through the bracket span if it was provided.
            if b_span is not None:
                # Add the bracket span to the output dictionary.
                ret["bracket_span_days"] = b_span
            # Pass through the bracket quality if it was provided.
            if b_qual:
                # Add the bracket quality to the output dictionary.
                ret["bracket_quality"] = b_qual
            # Return the dictionary.
            return ret
        # Select the single put option row that has the smallest 'd_diff' (closest to 25 delta).
        p_row = puts.loc[puts["d_diff"].idxmin()]
        # Select the single call option row that has the smallest 'd_diff' (closest to 25 delta).
        c_row = calls.loc[calls["d_diff"].idxmin()]
        # Safely extract the bid price, ask price, and implied volatility for the chosen put.
        p_bid, p_ask, p_iv = safe_float(p_row.get("bid")), safe_float(p_row.get("ask")), safe_float(p_row.get("volatility"))
        # Safely extract the bid price, ask price, and implied volatility for the chosen call.
        c_bid, c_ask, c_iv = safe_float(c_row.get("bid")), safe_float(c_row.get("ask")), safe_float(c_row.get("volatility"))
        # Determine the put midpoint price (mark), falling back to calculating the average of bid/ask if missing.
        p_mid = safe_float(p_row.get("mark")) or (safe_div(p_bid + p_ask, 2) if p_bid is not None and p_ask is not None else None)
        # Determine the call midpoint price (mark), falling back to calculating the average of bid/ask if missing.
        c_mid = safe_float(c_row.get("mark")) or (safe_div(c_bid + c_ask, 2) if c_bid is not None and c_ask is not None else None)
        # Calculate the put's relative bid-ask spread (spread width divided by price). Assign an artificial fail grade (2.0) if bid is zero.
        p_spr = 2.0 if (p_bid == 0.0 and p_ask and p_ask > 0) else (safe_div(abs(p_ask - p_bid), p_mid) if p_ask is not None and p_bid is not None and p_mid else None)
        # Calculate the call's relative bid-ask spread. Assign an artificial fail grade (2.0) if bid is zero.
        c_spr = 2.0 if (c_bid == 0.0 and c_ask and c_ask > 0) else (safe_div(abs(c_ask - c_bid), c_mid) if c_ask is not None and c_bid is not None and c_mid else None)
        # Get the maximum allowed relative spread from settings, defaulting to 50% (0.50) if not explicitly set.
        max_spr = self.ctx.params.get("MAX_SKEW_RELATIVE_SPREAD", 0.50)
        # Check if the put spread exceeds the maximum tolerance.
        p_fail = p_spr is not None and p_spr > max_spr
        # Check if the call spread exceeds the maximum tolerance.
        c_fail = c_spr is not None and c_spr > max_spr
        # If either wing fails the spread test, or spread data is entirely missing...
        if p_fail or c_fail or p_spr is None or c_spr is None:
            # Determine which specific wing caused the failure (for logging).
            rej_wing = "BOTH" if (p_fail and c_fail) else ("PUT" if p_fail else "CALL")
            # Prepare a rejection dictionary citing poor data quality (wide spread gate).
            rej_dict = {
                # Record the DTE we are evaluating.
                "skew_tenor_dte": t_dte,
                # Note the failure point: rejected due to wide bid-ask spreads.
                "skew_delta_anchor": "REJECTED_AT_WING_SPREAD_GATE",
                # Note that the skew regime cannot be determined.
                "skew_regime": "UNKNOWN",
                # Note where the limit rule came from.
                "spread_tolerance_source": "DEFAULT_EXECUTION_BOUNDARY",
                # Mark the state as UNKNOWN because calculation is impossible.
                "state": "UNKNOWN",
                # Provide the detailed reason: spreads exceed tolerance.
                "reason": "skew_wings_exceed_spread_tolerance",
                # Output the actual put spread metric so the user can debug.
                "observed_put_relative_spread": round(p_spr, 4) if p_spr is not None else None,
                # Output the actual call spread metric so the user can debug.
                "observed_call_relative_spread": round(c_spr, 4) if c_spr is not None else None,
                # Flag if the failure was specifically due to a zero bid.
                "spread_zero_bid_flag": p_bid == 0.0 or c_bid == 0.0,
                # Note which wing failed.
                "rejected_wing": rej_wing,
                # Reference the CMI bracket used.
                "cmi_bracket_ref": "constant_maturity_30d_iv",
            # Close the dictionary.
            }
            # Pass through the bracket span if it was provided.
            if b_span is not None:
                # Add the bracket span to the rejection dictionary.
                rej_dict["bracket_span_days"] = b_span
            # Pass through the bracket quality if it was provided.
            if b_qual:
                # Add the bracket quality to the rejection dictionary.
                rej_dict["bracket_quality"] = b_qual
            # Return the rejection dictionary.
            return rej_dict
        # Calculate the actual skew: the difference between the Put's Implied Volatility and the Call's Implied Volatility.
        diff = p_iv - c_iv if p_iv and c_iv else None
        # Extract the raw delta values for our chosen options.
        p_d, c_d = safe_float(p_row.get("delta")), safe_float(c_row.get("delta"))
        # Convert the deltas to absolute numbers (puts are usually negative).
        p_abs, c_abs = abs(p_d) if p_d else 0.0, abs(c_d) if c_d else 0.0
        # Calculate the 'symmetry gap' (how perfectly matched the two wing deltas are).
        sym_gap = round(abs(p_abs - c_abs), 3)
        # Check if the chosen put delta is within an acceptable 'band' around the 0.25 target.
        p_in_band = 0.20 <= p_abs <= 0.30
        # Check if the chosen call delta is within that same band.
        c_in_band = 0.20 <= c_abs <= 0.30
        # Define a 'primary' (high quality) match: both are within the band AND they are closely matched to each other.
        is_primary = p_in_band and c_in_band and (sym_gap <= 0.05)
        # Set the data quality label based on whether it met the strict primary conditions.
        anchor_label = "PRIMARY_25D_SYMMETRIC" if is_primary else "FALLBACK_NEAREST_SYMMETRIC"
        # Define the regime: if Puts are more expensive (diff > 0), it's reverse call skew, otherwise standard put skew.
        s_regime = "REVERSE_CALL_SKEW" if (diff is not None and diff > 0) else "STANDARD_PUT_SKEW"
        # Build the final successful result dictionary.
        ret = {
            # Record the DTE we are evaluating.
            "skew_tenor_dte": t_dte,
            # Output the data quality anchor label.
            "skew_delta_anchor": anchor_label,
            # Provide the calculated skew difference.
            "skew_30d_iv_differential": round(diff, 3) if diff is not None else None,
            # Provide the identified regime.
            "skew_regime": s_regime,
            # Output the symmetry gap metric.
            "skew_delta_symmetry_gap": sym_gap,
            # Output the actual put delta used.
            "skew_actual_put_delta": round(p_d, 3) if p_d is not None else None,
            # Output the actual call delta used.
            "skew_actual_call_delta": round(c_d, 3) if c_d is not None else None,
            # Note where the limit rule came from.
            "spread_tolerance_source": "DEFAULT_EXECUTION_BOUNDARY",
            # Mark the state as successfully calculated.
            "state": "CALCULATED",
        # Close the dictionary.
        }
        # Pass through the bracket span if it was provided.
        if b_span is not None:
            # Add the bracket span to the output dictionary.
            ret["bracket_span_days"] = b_span
        # Pass through the bracket quality if it was provided.
        if b_qual:
            # Add the bracket quality to the output dictionary.
            ret["bracket_quality"] = b_qual
        # If we had to fall back to lower-quality symmetry matches...
        if not is_primary:
            # Note exactly why we failed the primary quality test.
            ret["skew_anchor_reason"] = "PRIMARY_BAND_VIOLATED" if not (p_in_band and c_in_band) else "SYMMETRY_GAP_EXCEEDED"
        # Return the dictionary.
        return ret
