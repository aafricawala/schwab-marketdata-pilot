"""
schwab_step3_7_derivatives.py

Step 3/7 orchestrator: spot provenance, flow ratios, CMI, skew, ATM straddle.
Body moved verbatim from _calc_step_3_7; sub-blocks delegated to dedicated
calculators which are injected in the constructor.
"""
from __future__ import annotations

from typing import Any, Dict

from schwab_marketdata_context import MarketDataContext
from schwab_step3_cmi import Step3CMICalculator
from schwab_step3_skew import Step3SkewCalculator
from schwab_step3_atm_straddle import Step3ATMStraddleCalculator
from schwab_utils import safe_div


class Step3And7DerivativesCalculator:

    def __init__(
        self,
        ctx: MarketDataContext,
        cmi_calc: Step3CMICalculator,
        skew_calc: Step3SkewCalculator,
        atm_calc: Step3ATMStraddleCalculator,
    ):
        self.ctx = ctx
        self.cmi_calc = cmi_calc
        self.skew_calc = skew_calc
        self.atm_calc = atm_calc

    def calculate(self) -> Dict[str, Any]:
        spot_prov = {
            "source": self.ctx.spot_source,
            "vintage_risk": self.ctx.spot_vintage,
            "observed_price": self.ctx.calc_spot,
        }
        cmi_block = self.cmi_calc.calculate(self.ctx.opt_df)
        if self.ctx.opt_df.empty or "putCallIndicator" not in self.ctx.opt_df.columns:
            return {
                "spot_provenance": spot_prov,
                "state": "UNKNOWN",
                "reason": "options_chain_empty_or_unavailable",
                "skew_30d": {
                    "state": "UNKNOWN",
                    "reason": "options_chain_empty_or_unavailable",
                    "skew_delta_anchor": "REJECTED_BEFORE_SELECTION",
                    "skew_regime": "UNKNOWN",
                },
                "flow_ratios": {
                    "put_call_volume_ratio": None,
                    "put_call_open_interest_ratio": None,
                    "volume_regime": "NO_OPTIONS_VOLUME",
                    "state": "UNKNOWN",
                    "reason": "options_chain_empty_or_unavailable",
                },
            }
        df = self.ctx.opt_df.copy()
        puts = df[df["putCallIndicator"] == "PUT"]
        calls = df[df["putCallIndicator"] == "CALL"]

        vol_col = "totalVolume" if "totalVolume" in df.columns else ("volume" if "volume" in df.columns else None)
        oi_col = "openInterest" if "openInterest" in df.columns else ("open_interest" if "open_interest" in df.columns else None)

        p_vol = puts[vol_col].sum() if vol_col else 0.0
        c_vol = calls[vol_col].sum() if vol_col else 0.0
        p_oi = puts[oi_col].sum() if oi_col else 0.0
        c_oi = calls[oi_col].sum() if oi_col else 0.0

        vr = safe_div(p_vol, c_vol)
        oir = safe_div(p_oi, c_oi)
        tot_vol = (p_vol or 0.0) + (c_vol or 0.0)

        if vr is not None and oir is not None:
            flow_state = "CALCULATED"
            if vr < 0.50:
                regime = "HEAVY_CALL_FLOW"
            elif vr > 2.00:
                regime = "HEAVY_PUT_FLOW"
            else:
                regime = "NEUTRAL"
        elif vr is not None or oir is not None:
            flow_state = "PARTIAL"
            regime = (
                "HEAVY_CALL_FLOW"
                if (vr is not None and vr < 0.50)
                else (
                    "HEAVY_PUT_FLOW"
                    if (vr is not None and vr > 2.00)
                    else ("NEUTRAL" if vr is not None else "UNCLASSIFIED")
                )
            )
        else:
            flow_state = "UNKNOWN"
            regime = "NO_OPTIONS_VOLUME" if tot_vol == 0.0 else "UNCLASSIFIED"

        flow: Dict[str, Any] = {
            "put_call_volume_ratio": round(vr, 4) if vr is not None else None,
            "put_call_open_interest_ratio": round(oir, 4) if oir is not None else None,
            "volume_regime": regime,
            "state": flow_state,
        }

        if flow_state in ("UNKNOWN", "PARTIAL"):
            if tot_vol == 0.0:
                flow["reason"] = "options_chain_has_zero_contract_volume"
            elif c_oi == 0.0:
                flow["reason"] = "zero_call_open_interest_on_traded_chain"
            elif p_oi == 0.0:
                flow["reason"] = "zero_put_open_interest_on_traded_chain"
            elif c_vol == 0.0:
                flow["reason"] = "zero_call_volume_on_active_chain"
            else:
                flow["reason"] = "insufficient_liquidity_across_options_surface"

            if p_vol == 0.0 and c_vol > 0.0 and flow["reason"] != "options_chain_has_zero_contract_volume":
                flow["flow_ratios_note"] = "ZERO_PUT_VOLUME_OBSERVED"
            if p_oi == 0.0 and c_oi > 0.0 and flow["reason"] != "zero_put_open_interest_on_traded_chain":
                flow["flow_oi_note"] = "ZERO_PUT_OPEN_INTEREST_OBSERVED"

        skew_block = self.skew_calc.calculate(df, cmi_block)
        atm_block = self.atm_calc.calculate(df)
        return {
            "spot_provenance": spot_prov,
            "flow_ratios": flow,
            "constant_maturity_30d_iv": cmi_block,
            "skew_30d": skew_block,
            "atm_event_straddle": atm_block,
        }