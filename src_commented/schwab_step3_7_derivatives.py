"""
Filename: schwab_step3_7_derivatives.py
Purpose: Orchestrates the calculation of Step 3 and 7 derivative metrics, including spot provenance, options flow ratios, Constant Maturity Implied Volatility (CMI), volatility skew, and ATM straddles.
Prerequisites: Requires a populated `MarketDataContext` and initialized sub-calculators (CMI, Skew, ATM Straddle).
What this module does:
1. Validates the availability of options chain data.
2. Calculates put-call ratios for volume and open interest.
3. Classifies options flow into regimes (e.g., Heavy Put Flow, Neutral).
4. Delegates complex derivatives math (CMI, Skew, ATM Straddle) to specialized calculators.
Configuration knobs: Uses static thresholds for regime classification (e.g., vr < 0.50, vr > 2.00).
Outputs: Returns a comprehensive dictionary aggregating all derivative calculations and flow ratios.
Notes: Combines data from multiple sub-calculators without changing their logic, preserving original formatting.
"""
# Import the annotations feature from future to enable forward references in type hints
from __future__ import annotations

# Import Any and Dict from typing for type hinting return structures
from typing import Any, Dict

# Import the shared market data context class
from schwab_marketdata_context import MarketDataContext
# Import the specialized CMI calculator class
from schwab_step3_cmi import Step3CMICalculator
# Import the specialized Skew calculator class
from schwab_step3_skew import Step3SkewCalculator
# Import the specialized ATM Straddle calculator class
from schwab_step3_atm_straddle import Step3ATMStraddleCalculator
# Import utility functions for safe division operations
from schwab_utils import safe_div


# Define the main calculator class for Step 3 and 7 derivatives aggregation
class Step3And7DerivativesCalculator:

    # Initialize the calculator, storing context and injected sub-calculators
    def __init__(
        self,
        # The primary market data context
        ctx: MarketDataContext,
        # The CMI calculator instance
        cmi_calc: Step3CMICalculator,
        # The Skew calculator instance
        skew_calc: Step3SkewCalculator,
        # The ATM Straddle calculator instance
        atm_calc: Step3ATMStraddleCalculator,
    ):
        # Store the context instance
        self.ctx = ctx
        # Store the CMI calculator instance
        self.cmi_calc = cmi_calc
        # Store the Skew calculator instance
        self.skew_calc = skew_calc
        # Store the ATM Straddle calculator instance
        self.atm_calc = atm_calc

    # Define the primary method to calculate and aggregate all derivatives metrics
    def calculate(self) -> Dict[str, Any]:
        # Construct the spot provenance dictionary showing data source and vintage
        spot_prov = {
            # Note the source of the spot price calculation
            "source": self.ctx.spot_source,
            # Note the vintage or timestamp of the spot price
            "vintage_risk": self.ctx.spot_vintage,
            # Note the final observed spot price used for calculations
            "observed_price": self.ctx.calc_spot,
        }
        # Execute the CMI calculation using the options dataframe
        cmi_block = self.cmi_calc.calculate(self.ctx.opt_df)
        # Check if the options dataframe is empty or missing the crucial putCallIndicator column
        if self.ctx.opt_df.empty or "putCallIndicator" not in self.ctx.opt_df.columns:
            # Return a fast-fail structure indicating options are unavailable
            return {
                # Include the spot provenance even if options fail
                "spot_provenance": spot_prov,
                # Set the overall state to UNKNOWN
                "state": "UNKNOWN",
                # Note the reason for the failure
                "reason": "options_chain_empty_or_unavailable",
                # Provide a nullified skew block
                "skew_30d": {
                    # State is unknown due to missing options
                    "state": "UNKNOWN",
                    # Note the reason for the failure
                    "reason": "options_chain_empty_or_unavailable",
                    # Note the anchor was rejected early
                    "skew_delta_anchor": "REJECTED_BEFORE_SELECTION",
                    # Regime is unknown
                    "skew_regime": "UNKNOWN",
                },
                # Provide a nullified flow ratios block
                "flow_ratios": {
                    # PC volume ratio is null
                    "put_call_volume_ratio": None,
                    # PC open interest ratio is null
                    "put_call_open_interest_ratio": None,
                    # Regime indicates no volume exists
                    "volume_regime": "NO_OPTIONS_VOLUME",
                    # State is unknown
                    "state": "UNKNOWN",
                    # Note the reason for the failure
                    "reason": "options_chain_empty_or_unavailable",
                },
            }
        # Create a local copy of the options dataframe for processing
        df = self.ctx.opt_df.copy()
        # Filter the dataframe to isolate only Put options
        puts = df[df["putCallIndicator"] == "PUT"]
        # Filter the dataframe to isolate only Call options
        calls = df[df["putCallIndicator"] == "CALL"]

        # Determine the column name for volume, accommodating 'totalVolume' or 'volume' variations
        vol_col = "totalVolume" if "totalVolume" in df.columns else ("volume" if "volume" in df.columns else None)
        # Determine the column name for open interest, accommodating 'openInterest' or 'open_interest' variations
        oi_col = "openInterest" if "openInterest" in df.columns else ("open_interest" if "open_interest" in df.columns else None)

        # Sum the total volume for all Put options, defaulting to 0.0 if column missing
        p_vol = puts[vol_col].sum() if vol_col else 0.0
        # Sum the total volume for all Call options, defaulting to 0.0 if column missing
        c_vol = calls[vol_col].sum() if vol_col else 0.0
        # Sum the total open interest for all Put options, defaulting to 0.0 if column missing
        p_oi = puts[oi_col].sum() if oi_col else 0.0
        # Sum the total open interest for all Call options, defaulting to 0.0 if column missing
        c_oi = calls[oi_col].sum() if oi_col else 0.0

        # Calculate the put-call volume ratio safely
        vr = safe_div(p_vol, c_vol)
        # Calculate the put-call open interest ratio safely
        oir = safe_div(p_oi, c_oi)
        # Calculate the total combined options volume
        tot_vol = (p_vol or 0.0) + (c_vol or 0.0)

        # Check if both volume ratio and open interest ratio were successfully calculated
        if vr is not None and oir is not None:
            # Set the flow calculation state to successful
            flow_state = "CALCULATED"
            # Determine if volume ratio is extremely low indicating heavy call flow
            if vr < 0.50:
                # Assign regime as heavy call flow
                regime = "HEAVY_CALL_FLOW"
            # Determine if volume ratio is extremely high indicating heavy put flow
            elif vr > 2.00:
                # Assign regime as heavy put flow
                regime = "HEAVY_PUT_FLOW"
            # Otherwise, assign regime as neutral
            else:
                # Assign regime as neutral
                regime = "NEUTRAL"
        # Check if at least one of the ratios was successfully calculated
        elif vr is not None or oir is not None:
            # Set the flow calculation state to partial
            flow_state = "PARTIAL"
            # Determine the regime based on the available volume ratio, if any
            regime = (
                # Check for heavy call flow
                "HEAVY_CALL_FLOW"
                if (vr is not None and vr < 0.50)
                else (
                    # Check for heavy put flow
                    "HEAVY_PUT_FLOW"
                    if (vr is not None and vr > 2.00)
                    # Assign neutral or unclassified if ratio exists but is moderate, or is missing entirely
                    else ("NEUTRAL" if vr is not None else "UNCLASSIFIED")
                )
            )
        # If neither ratio could be calculated
        else:
            # Set the flow calculation state to unknown
            flow_state = "UNKNOWN"
            # Assign regime based on whether there was truly zero volume or just bad data columns
            regime = "NO_OPTIONS_VOLUME" if tot_vol == 0.0 else "UNCLASSIFIED"

        # Construct the core flow ratios dictionary
        flow: Dict[str, Any] = {
            # Store the rounded volume ratio, if available
            "put_call_volume_ratio": round(vr, 4) if vr is not None else None,
            # Store the rounded open interest ratio, if available
            "put_call_open_interest_ratio": round(oir, 4) if oir is not None else None,
            # Store the determined volume regime string
            "volume_regime": regime,
            # Store the calculated state of the flow metrics
            "state": flow_state,
        }

        # If the flow state indicates failure or partial success, append reason codes
        if flow_state in ("UNKNOWN", "PARTIAL"):
            # Check if total volume across the entire chain was explicitly zero
            if tot_vol == 0.0:
                # Note zero volume reason
                flow["reason"] = "options_chain_has_zero_contract_volume"
            # Check if call open interest specifically was zero, causing division failure
            elif c_oi == 0.0:
                # Note zero call OI reason
                flow["reason"] = "zero_call_open_interest_on_traded_chain"
            # Check if put open interest specifically was zero
            elif p_oi == 0.0:
                # Note zero put OI reason
                flow["reason"] = "zero_put_open_interest_on_traded_chain"
            # Check if call volume specifically was zero, causing division failure
            elif c_vol == 0.0:
                # Note zero call volume reason
                flow["reason"] = "zero_call_volume_on_active_chain"
            # Fallback for other liquidity issues
            else:
                # Note general insufficient liquidity
                flow["reason"] = "insufficient_liquidity_across_options_surface"

            # Check for anomaly: zero put volume but positive call volume
            if p_vol == 0.0 and c_vol > 0.0 and flow["reason"] != "options_chain_has_zero_contract_volume":
                # Append a special note highlighting zero put volume
                flow["flow_ratios_note"] = "ZERO_PUT_VOLUME_OBSERVED"
            # Check for anomaly: zero put open interest but positive call open interest
            if p_oi == 0.0 and c_oi > 0.0 and flow["reason"] != "zero_put_open_interest_on_traded_chain":
                # Append a special note highlighting zero put open interest
                flow["flow_oi_note"] = "ZERO_PUT_OPEN_INTEREST_OBSERVED"

        # Execute the Skew calculation using the options dataframe and the previously calculated CMI block
        skew_block = self.skew_calc.calculate(df, cmi_block)
        # Execute the ATM Straddle calculation using the options dataframe
        atm_block = self.atm_calc.calculate(df)
        # Construct and return the final comprehensive aggregated dictionary
        return {
            # Embed the spot provenance metadata
            "spot_provenance": spot_prov,
            # Embed the computed flow ratios dictionary
            "flow_ratios": flow,
            # Embed the CMI results block
            "constant_maturity_30d_iv": cmi_block,
            # Embed the Volatility Skew results block
            "skew_30d": skew_block,
            # Embed the ATM Straddle results block
            "atm_event_straddle": atm_block,
        }
