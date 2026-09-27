"""
schwab_step3_7_derivatives.py

Purpose:
This module orchestrates Step 3 and Step 7 of the derivatives calculations. It acts as a central coordinator
that computes options flow ratios (like put-to-call volume and open interest) and delegates more complex
calculations (such as constant maturity implied volatility, skew, and at-the-money straddles) to other
specialized calculators.

Prerequisites:
- A valid `MarketDataContext` containing the current options chain data as a pandas DataFrame.
- Instances of `Step3CMICalculator`, `Step3SkewCalculator`, and `Step3ATMStraddleCalculator` must be provided.

What this module does:
1. Records the source and vintage of the underlying asset's spot price.
2. Calls the CMI (Constant Maturity Implied Volatility) calculator.
3. Checks if the options chain is available and not empty. If it is empty, it returns early with "UNKNOWN" states.
4. Separates the options chain data into "puts" and "calls".
5. Calculates total volume and total open interest for both puts and calls.
6. Computes the put/call volume ratio and put/call open interest ratio.
7. Classifies the market sentiment into regimes (e.g., "HEAVY_CALL_FLOW", "HEAVY_PUT_FLOW", or "NEUTRAL").
8. Identifies reasons for any missing or partial flow data (e.g., zero volume).
9. Delegates the calculation of 30-day skew and the at-the-money event straddle to specialized classes.
10. Combines all these results into a single, comprehensive dictionary block.

Configuration knobs:
- No specific environment variables are used directly here, but ratios are rounded to 4 decimal places.
- Flow regime thresholds are hardcoded (ratio < 0.50 means HEAVY_CALL_FLOW; ratio > 2.00 means HEAVY_PUT_FLOW).

Outputs:
Returns a dictionary containing:
- spot_provenance: details about the current spot price.
- flow_ratios: put/call volume and open interest ratios, along with the volume regime.
- constant_maturity_30d_iv: the calculated CMI block.
- skew_30d: the calculated 30-day skew block.
- atm_event_straddle: the calculated straddle block.

Notes:
- If certain standard column names like "totalVolume" or "openInterest" are missing, it falls back to
  alternative names like "volume" or "open_interest".
"""
# Import the annotations feature from future to support modern type hints.
from __future__ import annotations

# Import Any and Dict from the typing module for type hinting.
from typing import Any, Dict

# Import the MarketDataContext which holds the current market state and options data.
from schwab_marketdata_context import MarketDataContext
# Import the calculator class responsible for Constant Maturity Implied Volatility (CMI).
from schwab_step3_cmi import Step3CMICalculator
# Import the calculator class responsible for computing options skew.
from schwab_step3_skew import Step3SkewCalculator
# Import the calculator class responsible for computing the at-the-money straddle.
from schwab_step3_atm_straddle import Step3ATMStraddleCalculator
# Import a utility function to safely perform division without raising errors on zero.
from schwab_utils import safe_div


# Define the main calculator class for Step 3 and 7 derivatives calculations.
class Step3And7DerivativesCalculator:

    # The constructor initializes the calculator with context and specialized calculators.
    def __init__(
        self,
        # The main context object containing market data and dataframes.
        ctx: MarketDataContext,
        # The specialized calculator for CMI.
        cmi_calc: Step3CMICalculator,
        # The specialized calculator for Skew.
        skew_calc: Step3SkewCalculator,
        # The specialized calculator for ATM Straddles.
        atm_calc: Step3ATMStraddleCalculator,
    ):
        # Store the provided market data context as an instance variable.
        self.ctx = ctx
        # Store the CMI calculator as an instance variable.
        self.cmi_calc = cmi_calc
        # Store the Skew calculator as an instance variable.
        self.skew_calc = skew_calc
        # Store the ATM Straddle calculator as an instance variable.
        self.atm_calc = atm_calc

    # Define the calculate method which returns a dictionary with all results.
    def calculate(self) -> Dict[str, Any]:
        # Create a dictionary to hold the provenance (origin) of the spot price.
        spot_prov = {
            # Record the source of the spot price from the context.
            "source": self.ctx.spot_source,
            # Record the vintage (time relevance/risk) of the spot price.
            "vintage_risk": self.ctx.spot_vintage,
            # Record the actual observed spot price value.
            "observed_price": self.ctx.calc_spot,
        }
        # Run the CMI calculator using the options dataframe from the context.
        cmi_block = self.cmi_calc.calculate(self.ctx.opt_df)

        # Check if the options dataframe is empty, or if it lacks the required "putCallIndicator" column.
        if self.ctx.opt_df.empty or "putCallIndicator" not in self.ctx.opt_df.columns:
            # If the chain is invalid or empty, return early with a failure/unknown state dictionary.
            return {
                # Include the spot provenance we just built.
                "spot_provenance": spot_prov,
                # Set the overall state to UNKNOWN.
                "state": "UNKNOWN",
                # Provide a reason why it failed.
                "reason": "options_chain_empty_or_unavailable",
                # Provide a default UNKNOWN block for the 30-day skew.
                "skew_30d": {
                    # State is unknown.
                    "state": "UNKNOWN",
                    # Reason for unknown state.
                    "reason": "options_chain_empty_or_unavailable",
                    # The delta anchor is rejected because we could not select it.
                    "skew_delta_anchor": "REJECTED_BEFORE_SELECTION",
                    # The skew regime cannot be determined.
                    "skew_regime": "UNKNOWN",
                },
                # Provide a default empty block for flow ratios.
                "flow_ratios": {
                    # No volume ratio could be calculated.
                    "put_call_volume_ratio": None,
                    # No open interest ratio could be calculated.
                    "put_call_open_interest_ratio": None,
                    # Volume regime indicates no volume is present.
                    "volume_regime": "NO_OPTIONS_VOLUME",
                    # Flow state is unknown.
                    "state": "UNKNOWN",
                    # Reason is the same as the main state.
                    "reason": "options_chain_empty_or_unavailable",
                },
            }

        # Create a copy of the options dataframe so we don't accidentally modify the original.
        df = self.ctx.opt_df.copy()

        # Filter the dataframe to only include rows where the putCallIndicator is "PUT".
        puts = df[df["putCallIndicator"] == "PUT"]
        # Filter the dataframe to only include rows where the putCallIndicator is "CALL".
        calls = df[df["putCallIndicator"] == "CALL"]

        # Determine the name of the volume column; prefer "totalVolume", fallback to "volume", otherwise None.
        vol_col = "totalVolume" if "totalVolume" in df.columns else ("volume" if "volume" in df.columns else None)
        # Determine the name of the open interest column; prefer "openInterest", fallback to "open_interest", otherwise None.
        oi_col = "openInterest" if "openInterest" in df.columns else ("open_interest" if "open_interest" in df.columns else None)

        # Sum the volume column for all puts, defaulting to 0.0 if the column is missing.
        p_vol = puts[vol_col].sum() if vol_col else 0.0
        # Sum the volume column for all calls, defaulting to 0.0 if the column is missing.
        c_vol = calls[vol_col].sum() if vol_col else 0.0
        # Sum the open interest column for all puts, defaulting to 0.0 if the column is missing.
        p_oi = puts[oi_col].sum() if oi_col else 0.0
        # Sum the open interest column for all calls, defaulting to 0.0 if the column is missing.
        c_oi = calls[oi_col].sum() if oi_col else 0.0

        # Calculate the put-to-call volume ratio using a safe division utility.
        vr = safe_div(p_vol, c_vol)
        # Calculate the put-to-call open interest ratio using a safe division utility.
        oir = safe_div(p_oi, c_oi)
        # Calculate the total options volume across both puts and calls.
        tot_vol = (p_vol or 0.0) + (c_vol or 0.0)

        # If both the volume ratio and open interest ratio were successfully calculated.
        if vr is not None and oir is not None:
            # Set the flow state to fully CALCULATED.
            flow_state = "CALCULATED"
            # If the put/call volume ratio is less than 0.50, call flow is dominant.
            if vr < 0.50:
                # Classify regime as heavy call flow.
                regime = "HEAVY_CALL_FLOW"
            # If the put/call volume ratio is greater than 2.00, put flow is dominant.
            elif vr > 2.00:
                # Classify regime as heavy put flow.
                regime = "HEAVY_PUT_FLOW"
            # If the ratio is between 0.50 and 2.00, the flow is considered balanced.
            else:
                # Classify regime as neutral.
                regime = "NEUTRAL"

        # If only one of the ratios (volume OR open interest) was calculated successfully.
        elif vr is not None or oir is not None:
            # Set the flow state to PARTIAL because we only have some data.
            flow_state = "PARTIAL"
            # Determine the regime based on the volume ratio if it exists.
            regime = (
                # Heavy call flow if volume ratio is less than 0.50.
                "HEAVY_CALL_FLOW"
                if (vr is not None and vr < 0.50)
                else (
                    # Heavy put flow if volume ratio is greater than 2.00.
                    "HEAVY_PUT_FLOW"
                    if (vr is not None and vr > 2.00)
                    # If volume ratio exists but doesn't meet the thresholds, call it neutral; otherwise unclassified.
                    else ("NEUTRAL" if vr is not None else "UNCLASSIFIED")
                )
            )

        # If neither ratio could be calculated.
        else:
            # Set the flow state to UNKNOWN.
            flow_state = "UNKNOWN"
            # If total volume is exactly zero, the regime is no options volume, otherwise it's unclassified.
            regime = "NO_OPTIONS_VOLUME" if tot_vol == 0.0 else "UNCLASSIFIED"

        # Create the flow dictionary block with our calculated metrics.
        flow: Dict[str, Any] = {
            # Include the volume ratio, rounded to 4 decimal places if it's not None.
            "put_call_volume_ratio": round(vr, 4) if vr is not None else None,
            # Include the open interest ratio, rounded to 4 decimal places if it's not None.
            "put_call_open_interest_ratio": round(oir, 4) if oir is not None else None,
            # Include the determined volume regime string.
            "volume_regime": regime,
            # Include the calculated state (CALCULATED, PARTIAL, or UNKNOWN).
            "state": flow_state,
        }

        # If the flow state indicates missing or partial data, we need to provide a reason.
        if flow_state in ("UNKNOWN", "PARTIAL"):
            # Check if total volume is zero.
            if tot_vol == 0.0:
                # Reason: there is zero volume across all contracts on this chain.
                flow["reason"] = "options_chain_has_zero_contract_volume"
            # Check if call open interest is zero.
            elif c_oi == 0.0:
                # Reason: there is no call open interest at all.
                flow["reason"] = "zero_call_open_interest_on_traded_chain"
            # Check if put open interest is zero.
            elif p_oi == 0.0:
                # Reason: there is no put open interest at all.
                flow["reason"] = "zero_put_open_interest_on_traded_chain"
            # Check if call volume is zero.
            elif c_vol == 0.0:
                # Reason: there is no call volume traded today.
                flow["reason"] = "zero_call_volume_on_active_chain"
            # If none of the specific zero conditions match, use a general insufficient liquidity reason.
            else:
                # Reason: broad lack of liquidity.
                flow["reason"] = "insufficient_liquidity_across_options_surface"

            # If put volume is zero but call volume exists, and the primary reason wasn't total zero volume.
            if p_vol == 0.0 and c_vol > 0.0 and flow["reason"] != "options_chain_has_zero_contract_volume":
                # Add a specific note indicating zero put volume was seen.
                flow["flow_ratios_note"] = "ZERO_PUT_VOLUME_OBSERVED"
            # If put open interest is zero but call open interest exists, and primary reason wasn't total zero put OI.
            if p_oi == 0.0 and c_oi > 0.0 and flow["reason"] != "zero_put_open_interest_on_traded_chain":
                # Add a specific note indicating zero put open interest was seen.
                flow["flow_oi_note"] = "ZERO_PUT_OPEN_INTEREST_OBSERVED"

        # Delegate the 30-day skew calculation to the specialized calculator, passing in the DataFrame and CMI block.
        skew_block = self.skew_calc.calculate(df, cmi_block)
        # Delegate the at-the-money straddle calculation to its specialized calculator, passing the DataFrame.
        atm_block = self.atm_calc.calculate(df)

        # Return a dictionary containing all computed pieces for Steps 3 and 7.
        return {
            # The spot provenance dictionary.
            "spot_provenance": spot_prov,
            # The flow ratios dictionary block.
            "flow_ratios": flow,
            # The constant maturity 30-day implied volatility block.
            "constant_maturity_30d_iv": cmi_block,
            # The 30-day skew block.
            "skew_30d": skew_block,
            # The ATM event straddle block.
            "atm_event_straddle": atm_block,
        }
