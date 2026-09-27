"""
schwab_marketdata_calculator.py

Purpose:
This module provides a Façade (a unified interface) that preserves the original public contract of
the `MasterThesisCalculator`. All the heavy lifting (actual logic and calculations) has been moved to
specialized modules (`schwab_step*`), but this file keeps the exact same initialization signature,
method names, and property behaviors so that existing tests, callers, or subclasses continue to work
without modification.

Prerequisites:
- Requires standard libraries (`typing`).
- Requires `pandas` for handling price history and options dataframes.
- Requires all the specialized `schwab_step*` calculator modules to be present and importable.

What this module does:
1. Initializes a central `MarketDataContext` object from the provided raw data and parameters.
2. Initializes all the individual step calculators by injecting the shared context object.
3. Provides read-only properties to mimic the instance attributes of the old calculator class.
4. Exposes the main `calculate_metrics()` public method which returns the aggregated thesis.
5. Preserves private `_calc_*` methods as thin delegate shims that simply call out to the specialized classes.

Configuration knobs:
- None directly. Parameters are passed into the constructor via a dictionary and forwarded to the context.

Outputs:
- Exposes `calculate_metrics()` which returns a comprehensive dictionary with results from all steps
  (grounding, fundamentals, derivatives, technicals).

Notes:
- This file acts purely as a router/coordinator. No actual math or logic should be added here.
"""
# Enable modern type hinting features.
from __future__ import annotations

# Import Any and Dict for typing complex nested data structures.
from typing import Any, Dict

# Import pandas, the standard library for data manipulation and analysis.
import pandas as pd

# Import the shared context object that manages state across calculators.
from schwab_marketdata_context import MarketDataContext
# Import the calculator for Step 0 (Grounding).
from schwab_step0_grounding import Step0GroundingCalculator
# Import the calculator for Step 1 (Fundamentals).
from schwab_step1_fundamentals import Step1FundamentalsCalculator
# Import the calculator for Constant Maturity Implied Volatility (CMI).
from schwab_step3_cmi import Step3CMICalculator
# Import the calculator for options Skew.
from schwab_step3_skew import Step3SkewCalculator
# Import the calculator for the At-The-Money event straddle.
from schwab_step3_atm_straddle import Step3ATMStraddleCalculator
# Import the overarching calculator for Steps 3 and 7 (Derivatives).
from schwab_step3_7_derivatives import Step3And7DerivativesCalculator
# Import the calculator for realized volatility.
from schwab_step5_realized_vol import Step5RealizedVolCalculator
# Import the overarching calculator for Step 5 (Technicals and Flows).
from schwab_step5_technicals import Step5TechnicalsCalculator


# Define the main calculator class that serves as the entry point for thesis generation.
class MasterThesisCalculator:

    # The constructor accepts raw JSON data, two pandas dataframes, and a params dictionary.
    def __init__(
        self,
        # The raw JSON payload from the Schwab API.
        raw_data: Dict[str, Any],
        # The price history (candlesticks) as a DataFrame.
        price_history_df: pd.DataFrame,
        # The options chain surface as a DataFrame.
        options_df: pd.DataFrame,
        # Execution parameters and flags.
        params: Dict[str, Any],
    ):
        # Instantiate the shared MarketDataContext using the provided arguments.
        self.ctx = MarketDataContext(
            raw_data=raw_data,
            price_history_df=price_history_df,
            options_df=options_df,
            params=params,
        )

        # Collaborators (composition only; no logic here).
        # Initialize the grounding calculator with the shared context.
        self._step0 = Step0GroundingCalculator(self.ctx)
        # Initialize the fundamentals calculator with the shared context.
        self._step1 = Step1FundamentalsCalculator(self.ctx)
        # Initialize the CMI calculator with the shared context.
        self._cmi = Step3CMICalculator(self.ctx)
        # Initialize the skew calculator with the shared context.
        self._skew = Step3SkewCalculator(self.ctx)
        # Initialize the ATM straddle calculator with the shared context.
        self._atm = Step3ATMStraddleCalculator(self.ctx)
        # Initialize the Step 3/7 orchestrator, injecting the context and specialized calculators.
        self._step3_7 = Step3And7DerivativesCalculator(
            ctx=self.ctx,
            cmi_calc=self._cmi,
            skew_calc=self._skew,
            atm_calc=self._atm,
        )
        # Initialize the realized volatility calculator (does not require the full context).
        self._rv = Step5RealizedVolCalculator()
        # Initialize the technicals calculator, injecting the context and the RV calculator.
        self._step5 = Step5TechnicalsCalculator(self.ctx, self._rv)

    # ------------------------------------------------------------------
    # Read-only attribute passthroughs (backward compatibility)
    #
    # The original class stored these directly on the instance. They now
    # live on self.ctx. These properties preserve the original attribute
    # names for any external caller, subclass, or test that reads them.
    # No setters are defined: the original code never mutated them after
    # __init__, so read-only is faithful to the original semantics.
    # ------------------------------------------------------------------

    # Expose the raw data dictionary from the context.
    @property
    def raw(self) -> Dict[str, Any]:
        return self.ctx.raw

    # Expose the price history dataframe from the context.
    @property
    def ph_df(self) -> pd.DataFrame:
        return self.ctx.ph_df

    # Expose the options chain dataframe from the context.
    @property
    def opt_df(self) -> pd.DataFrame:
        return self.ctx.opt_df

    # Expose the parameters dictionary from the context.
    @property
    def params(self) -> Dict[str, Any]:
        return self.ctx.params

    # Expose the last quote price from the context.
    @property
    def quote_last(self):
        return self.ctx.quote_last

    # Expose the previous close price from the context.
    @property
    def close(self):
        return self.ctx.close

    # Expose the flag indicating if the market is open from the context.
    @property
    def is_open(self) -> bool:
        return self.ctx.is_open

    # Expose the age of the quote from the context.
    @property
    def quote_age(self):
        return self.ctx.quote_age

    # Expose the quote classification state from the context.
    @property
    def q_class(self) -> str:
        return self.ctx.q_class

    # Expose the fundamental data dictionary from the context.
    @property
    def fund(self) -> Dict[str, Any]:
        return self.ctx.fund

    # Expose the derivatives data dictionary from the context.
    @property
    def deriv(self) -> Dict[str, Any]:
        return self.ctx.deriv

    # Expose the calculated spot price from the context.
    @property
    def calc_spot(self):
        return self.ctx.calc_spot

    # Expose the source of the spot price from the context.
    @property
    def spot_source(self) -> str:
        return self.ctx.spot_source

    # Expose the vintage/risk state of the spot price from the context.
    @property
    def spot_vintage(self) -> str:
        return self.ctx.spot_vintage

    # ------------------------------------------------------------------
    # Public contract
    # ------------------------------------------------------------------
    # This is the main public method to compute all thesis metrics.
    def calculate_metrics(self) -> Dict[str, Any]:
        # Return a dictionary wrapping the results of all major calculation steps.
        return {
            # Execute step 0 (Grounding).
            "step_0_grounding": self._calc_step_0(),
            # Execute step 1 (Fundamentals and Quality).
            "step_1_fundamentals_and_quality": self._calc_step_1(),
            # Execute steps 3 and 7 (Derivatives and Surface).
            "step_3_and_7_derivatives_and_surface": self._calc_step_3_7(),
            # Execute step 5 (Technicals and Flows).
            "step_5_technicals_and_flows": self._calc_step_5(),
        }

    # ------------------------------------------------------------------
    # Private shims (preserved for subclass / test stability)
    # ------------------------------------------------------------------
    # Delegate step 0 calculation to the Step 0 calculator.
    def _calc_step_0(self) -> Dict[str, Any]:
        return self._step0.calculate()

    # Delegate step 1 calculation to the Step 1 calculator.
    def _calc_step_1(self) -> Dict[str, Any]:
        return self._step1.calculate()

    # Delegate steps 3 and 7 calculations to the orchestrator calculator.
    def _calc_step_3_7(self) -> Dict[str, Any]:
        return self._step3_7.calculate()

    # Delegate 30-day CMI calculation to the CMI calculator.
    def _calc_cmi_30d(self, df: pd.DataFrame) -> Dict[str, Any]:
        return self._cmi.calculate(df)

    # Delegate 30-day skew calculation to the Skew calculator.
    def _calc_skew_30d(
        # The options dataframe to process.
        self, df: pd.DataFrame,
        # The previously calculated CMI block needed for context.
        cmi_block: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self._skew.calculate(df, cmi_block)

    # Delegate ATM straddle calculation to the ATM calculator.
    def _calc_atm_straddle(self, df: pd.DataFrame) -> Dict[str, Any]:
        return self._atm.calculate(df)

    # Delegate step 5 calculations to the Step 5 calculator.
    def _calc_step_5(self) -> Dict[str, Any]:
        return self._step5.calculate()

    # Delegate the realized volatility suite calculations to the RV calculator.
    def _calc_realized_vol_suite(self, df: pd.DataFrame) -> Dict[str, Any]:
        return self._rv.calculate_suite(df)

    # Delegate a specific horizon calculation to the protected method in the RV calculator.
    def _calc_rv_horizon(
        # The price history dataframe.
        self,
        df: pd.DataFrame,
        # The target window size in days.
        target_win: int,
        # The minimum number of bars required.
        min_bars: int,
        # Whether to check if the asset is newly listed (seasoning).
        check_seasoning: bool = False,
        # The total available bars.
        total_avail: int = 0,
    ) -> Dict[str, Any]:
        return self._rv._calc_rv_horizon(
            # Pass through the dataframe.
            df,
            # Pass through the target window.
            target_win,
            # Pass through the minimum bars.
            min_bars,
            # Pass through the seasoning check flag.
            check_seasoning=check_seasoning,
            # Pass through the total available bars.
            total_avail=total_avail,
        )
