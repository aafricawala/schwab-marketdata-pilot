"""
Filename: schwab_marketdata_calculator.py
Purpose: Acts as a façade and orchestration engine for executing a multi-step fundamental and technical analysis pipeline on financial market data.
Prerequisites: Requires instantiated context and various specialized calculation steps (Step 1, Step 3, Step 5, etc.) and valid data structures.
What this module does:
1. Initializes a MarketDataContext to hold state and references for a specific financial symbol.
2. Coordinates the execution of sequential analysis steps.
3. Provides properties to access underlying context data.
4. Returns calculated metrics in a structured dictionary.
Configuration knobs: None explicitly.
Outputs: Returns nested dictionaries representing a full quantitative and fundamental profile of a security.
Notes: Preserves the original public contract of MasterThesisCalculator while delegating logic to step calculators.
"""
# Import the annotations feature from future to enable forward references in type hinting
from __future__ import annotations

# Import Any and Dict from the typing module for type hinting the nested dictionaries
from typing import Any, Dict

# Import pandas for data manipulation and type hinting DataFrames
import pandas as pd

# Import the MarketDataContext class to manage shared state across all calculators
from schwab_marketdata_context import MarketDataContext
# Import the Step 0 calculator responsible for grounding and validating raw data
from schwab_step0_grounding import Step0GroundingCalculator
# Import the Step 1 calculator responsible for fundamental analysis
from schwab_step1_fundamentals import Step1FundamentalsCalculator
# Import the Step 3 CMI calculator for cross-market implied metrics
from schwab_step3_cmi import Step3CMICalculator
# Import the Step 3 Skew calculator for volatility surface skew
from schwab_step3_skew import Step3SkewCalculator
# Import the Step 3 ATM Straddle calculator
from schwab_step3_atm_straddle import Step3ATMStraddleCalculator
# Import the overarching Step 3 and 7 aggregator for derivatives
from schwab_step3_7_derivatives import Step3And7DerivativesCalculator
# Import the Step 5 calculator for realized volatility
from schwab_step5_realized_vol import Step5RealizedVolCalculator
# Import the Step 5 calculator for technical analysis indicators
from schwab_step5_technicals import Step5TechnicalsCalculator


# Define the main façade class that orchestrates the entire calculation pipeline
class MasterThesisCalculator:

    # Initialize the calculator with all necessary input data and configuration parameters
    def __init__(
        self,
        # The raw payload containing quotes and fundamental data
        raw_data: Dict[str, Any],
        # A pandas DataFrame containing historical price data
        price_history_df: pd.DataFrame,
        # A pandas DataFrame containing the options chain data
        options_df: pd.DataFrame,
        # A dictionary of configuration parameters for the calculations
        params: Dict[str, Any],
    ):
        # Instantiate the shared context object to hold all data and state centrally
        self.ctx = MarketDataContext(
            raw_data=raw_data,
            price_history_df=price_history_df,
            options_df=options_df,
            params=params,
        )

        # Initialize the Step 0 grounding calculator with the shared context
        self._step0 = Step0GroundingCalculator(self.ctx)
        # Initialize the Step 1 fundamentals calculator with the shared context
        self._step1 = Step1FundamentalsCalculator(self.ctx)
        # Initialize the Step 3 CMI calculator with the shared context
        self._cmi = Step3CMICalculator(self.ctx)
        # Initialize the Step 3 Skew calculator with the shared context
        self._skew = Step3SkewCalculator(self.ctx)
        # Initialize the Step 3 ATM Straddle calculator with the shared context
        self._atm = Step3ATMStraddleCalculator(self.ctx)
        # Initialize the Step 3/7 derivatives aggregator, injecting the context and sub-calculators
        self._step3_7 = Step3And7DerivativesCalculator(
            ctx=self.ctx,
            cmi_calc=self._cmi,
            skew_calc=self._skew,
            atm_calc=self._atm,
        )
        # Initialize the Step 5 realized volatility calculator (does not need context directly)
        self._rv = Step5RealizedVolCalculator()
        # Initialize the Step 5 technicals calculator, injecting context and the realized vol calculator
        self._step5 = Step5TechnicalsCalculator(self.ctx, self._rv)

    # ------------------------------------------------------------------
    # Define read-only properties that act as passthroughs to the shared context
    # ------------------------------------------------------------------

    # Expose the raw data dictionary from the context
    @property
    def raw(self) -> Dict[str, Any]:
        return self.ctx.raw

    # Expose the price history DataFrame from the context
    @property
    def ph_df(self) -> pd.DataFrame:
        return self.ctx.ph_df

    # Expose the options chain DataFrame from the context
    @property
    def opt_df(self) -> pd.DataFrame:
        return self.ctx.opt_df

    # Expose the configuration parameters dictionary from the context
    @property
    def params(self) -> Dict[str, Any]:
        return self.ctx.params

    # Expose the last quote value from the context
    @property
    def quote_last(self):
        return self.ctx.quote_last

    # Expose the closing price from the context
    @property
    def close(self):
        return self.ctx.close

    # Expose the boolean flag indicating if the market is open from the context
    @property
    def is_open(self) -> bool:
        return self.ctx.is_open

    # Expose the age of the quote from the context
    @property
    def quote_age(self):
        return self.ctx.quote_age

    # Expose the quote class string from the context
    @property
    def q_class(self) -> str:
        return self.ctx.q_class

    # Expose the fundamental data dictionary from the context
    @property
    def fund(self) -> Dict[str, Any]:
        return self.ctx.fund

    # Expose the derivatives data dictionary from the context
    @property
    def deriv(self) -> Dict[str, Any]:
        return self.ctx.deriv

    # Expose the calculated spot price from the context
    @property
    def calc_spot(self):
        return self.ctx.calc_spot

    # Expose the source of the spot price from the context
    @property
    def spot_source(self) -> str:
        return self.ctx.spot_source

    # Expose the vintage/timestamp of the spot price from the context
    @property
    def spot_vintage(self) -> str:
        return self.ctx.spot_vintage

    # ------------------------------------------------------------------
    # Define the primary public method to execute all steps
    # ------------------------------------------------------------------

    # Execute the full suite of calculations and return the final aggregated dictionary
    def calculate_metrics(self) -> Dict[str, Any]:
        # Return a dictionary combining the results of each major step
        return {
            # Execute Step 0 and assign to 'step_0_grounding'
            "step_0_grounding": self._calc_step_0(),
            # Execute Step 1 and assign to 'step_1_fundamentals_and_quality'
            "step_1_fundamentals_and_quality": self._calc_step_1(),
            # Execute Step 3/7 and assign to 'step_3_and_7_derivatives_and_surface'
            "step_3_and_7_derivatives_and_surface": self._calc_step_3_7(),
            # Execute Step 5 and assign to 'step_5_technicals_and_flows'
            "step_5_technicals_and_flows": self._calc_step_5(),
        }

    # ------------------------------------------------------------------
    # Define private shim methods that delegate to the specialized calculators
    # ------------------------------------------------------------------

    # Delegate the execution of Step 0 to the Step0GroundingCalculator
    def _calc_step_0(self) -> Dict[str, Any]:
        return self._step0.calculate()

    # Delegate the execution of Step 1 to the Step1FundamentalsCalculator
    def _calc_step_1(self) -> Dict[str, Any]:
        return self._step1.calculate()

    # Delegate the execution of the derivatives aggregator to the Step3And7DerivativesCalculator
    def _calc_step_3_7(self) -> Dict[str, Any]:
        return self._step3_7.calculate()

    # Delegate the 30-day CMI calculation to the Step3CMICalculator
    def _calc_cmi_30d(self, df: pd.DataFrame) -> Dict[str, Any]:
        return self._cmi.calculate(df)

    # Delegate the 30-day skew calculation to the Step3SkewCalculator, passing required CMI block
    def _calc_skew_30d(
        self, df: pd.DataFrame, cmi_block: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self._skew.calculate(df, cmi_block)

    # Delegate the ATM straddle calculation to the Step3ATMStraddleCalculator
    def _calc_atm_straddle(self, df: pd.DataFrame) -> Dict[str, Any]:
        return self._atm.calculate(df)

    # Delegate the execution of Step 5 to the Step5TechnicalsCalculator
    def _calc_step_5(self) -> Dict[str, Any]:
        return self._step5.calculate()

    # Delegate the execution of the full realized volatility suite to the Step5RealizedVolCalculator
    def _calc_realized_vol_suite(self, df: pd.DataFrame) -> Dict[str, Any]:
        return self._rv.calculate_suite(df)

    # Delegate the calculation of realized volatility over a specific horizon
    def _calc_rv_horizon(
        self,
        # The price history DataFrame
        df: pd.DataFrame,
        # The target window size in periods
        target_win: int,
        # The minimum number of bars required to compute
        min_bars: int,
        # A flag to check if the data is seasoned enough (default False)
        check_seasoning: bool = False,
        # The total number of available periods (default 0)
        total_avail: int = 0,
    ) -> Dict[str, Any]:
        # Call the protected horizon calculation method on the realized vol calculator
        return self._rv._calc_rv_horizon(
            df,
            target_win,
            min_bars,
            check_seasoning=check_seasoning,
            total_avail=total_avail,
        )
