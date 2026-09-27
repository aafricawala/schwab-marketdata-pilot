"""
schwab_marketdata_calculator.py

Façade. Preserves the original public contract of MasterThesisCalculator:
  - same __init__ signature (raw_data, price_history_df, options_df, params)
  - same calculate_metrics() return shape
  - same private _calc_* method names as thin delegating shims
  - same instance attribute names via read-only property passthroughs

All heavy lifting now lives in the schwab_step* modules; this file only wires
context + collaborators and delegates. Logic is unchanged.
"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from schwab_marketdata_context import MarketDataContext
from schwab_step0_grounding import Step0GroundingCalculator
from schwab_step1_fundamentals import Step1FundamentalsCalculator
from schwab_step3_cmi import Step3CMICalculator
from schwab_step3_skew import Step3SkewCalculator
from schwab_step3_atm_straddle import Step3ATMStraddleCalculator
from schwab_step3_7_derivatives import Step3And7DerivativesCalculator
from schwab_step5_realized_vol import Step5RealizedVolCalculator
from schwab_step5_technicals import Step5TechnicalsCalculator


class MasterThesisCalculator:

    def __init__(
        self,
        raw_data: Dict[str, Any],
        price_history_df: pd.DataFrame,
        options_df: pd.DataFrame,
        params: Dict[str, Any],
    ):
        self.ctx = MarketDataContext(
            raw_data=raw_data,
            price_history_df=price_history_df,
            options_df=options_df,
            params=params,
        )

        # Collaborators (composition only; no logic here).
        self._step0 = Step0GroundingCalculator(self.ctx)
        self._step1 = Step1FundamentalsCalculator(self.ctx)
        self._cmi = Step3CMICalculator(self.ctx)
        self._skew = Step3SkewCalculator(self.ctx)
        self._atm = Step3ATMStraddleCalculator(self.ctx)
        self._step3_7 = Step3And7DerivativesCalculator(
            ctx=self.ctx,
            cmi_calc=self._cmi,
            skew_calc=self._skew,
            atm_calc=self._atm,
        )
        self._rv = Step5RealizedVolCalculator()
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
    @property
    def raw(self) -> Dict[str, Any]:
        return self.ctx.raw

    @property
    def ph_df(self) -> pd.DataFrame:
        return self.ctx.ph_df

    @property
    def opt_df(self) -> pd.DataFrame:
        return self.ctx.opt_df

    @property
    def params(self) -> Dict[str, Any]:
        return self.ctx.params

    @property
    def quote_last(self):
        return self.ctx.quote_last

    @property
    def close(self):
        return self.ctx.close

    @property
    def is_open(self) -> bool:
        return self.ctx.is_open

    @property
    def quote_age(self):
        return self.ctx.quote_age

    @property
    def q_class(self) -> str:
        return self.ctx.q_class

    @property
    def fund(self) -> Dict[str, Any]:
        return self.ctx.fund

    @property
    def deriv(self) -> Dict[str, Any]:
        return self.ctx.deriv

    @property
    def calc_spot(self):
        return self.ctx.calc_spot

    @property
    def spot_source(self) -> str:
        return self.ctx.spot_source

    @property
    def spot_vintage(self) -> str:
        return self.ctx.spot_vintage

    # ------------------------------------------------------------------
    # Public contract
    # ------------------------------------------------------------------
    def calculate_metrics(self) -> Dict[str, Any]:
        return {
            "step_0_grounding": self._calc_step_0(),
            "step_1_fundamentals_and_quality": self._calc_step_1(),
            "step_3_and_7_derivatives_and_surface": self._calc_step_3_7(),
            "step_5_technicals_and_flows": self._calc_step_5(),
        }

    # ------------------------------------------------------------------
    # Private shims (preserved for subclass / test stability)
    # ------------------------------------------------------------------
    def _calc_step_0(self) -> Dict[str, Any]:
        return self._step0.calculate()

    def _calc_step_1(self) -> Dict[str, Any]:
        return self._step1.calculate()

    def _calc_step_3_7(self) -> Dict[str, Any]:
        return self._step3_7.calculate()

    def _calc_cmi_30d(self, df: pd.DataFrame) -> Dict[str, Any]:
        return self._cmi.calculate(df)

    def _calc_skew_30d(
        self, df: pd.DataFrame, cmi_block: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self._skew.calculate(df, cmi_block)

    def _calc_atm_straddle(self, df: pd.DataFrame) -> Dict[str, Any]:
        return self._atm.calculate(df)

    def _calc_step_5(self) -> Dict[str, Any]:
        return self._step5.calculate()

    def _calc_realized_vol_suite(self, df: pd.DataFrame) -> Dict[str, Any]:
        return self._rv.calculate_suite(df)

    def _calc_rv_horizon(
        self,
        df: pd.DataFrame,
        target_win: int,
        min_bars: int,
        check_seasoning: bool = False,
        total_avail: int = 0,
    ) -> Dict[str, Any]:
        return self._rv._calc_rv_horizon(
            df,
            target_win,
            min_bars,
            check_seasoning=check_seasoning,
            total_avail=total_avail,
        )