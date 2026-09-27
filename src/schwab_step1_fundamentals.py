"""
schwab_step1_fundamentals.py

Step 1: fundamentals, quality, market-cap divergence, earnings yield,
PE/EPS vintage disparity, dividend payout ratio, coverage flags.
Body moved verbatim from _calc_step_1.
"""
from __future__ import annotations

from typing import Any, Dict

from schwab_marketdata_context import MarketDataContext
from schwab_utils import safe_div, safe_float


class Step1FundamentalsCalculator:

    def __init__(self, ctx: MarketDataContext):
        self.ctx = ctx

    def calculate(self) -> Dict[str, Any]:
        pe = safe_float(self.ctx.fund.get("peRatio"))
        eps = safe_float(self.ctx.fund.get("eps"))
        div_amt = safe_float(self.ctx.fund.get("divAmount"))
        div_y = safe_float(self.ctx.fund.get("divYield"))
        shares = safe_float(self.ctx.fund.get("sharesOutstanding"))
        mcap = safe_float(self.ctx.fund.get("marketCap"))
        eps_state = str(self.ctx.fund.get("eps_state") or "")
        pe_state = str(self.ctx.fund.get("peRatio_state") or "")
        shares_state = str(self.ctx.fund.get("shares_outstanding_state") or "")

        is_halted = (
            self.ctx.q_class == "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
            or shares_state == "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
            or eps_state == "VENDOR_UNAVAILABLE_ASSET_HALTED"
            or pe_state == "VENDOR_UNAVAILABLE_ASSET_HALTED"
        )
        is_warrant = (
            shares_state == "UNAVAILABLE_FOR_WARRANT"
            or eps_state == "VENDOR_UNAVAILABLE_WARRANT_NO_EPS"
            or pe_state == "NOT_APPLICABLE_WARRANT"
        )
        is_etn = not is_halted and not is_warrant and (
            shares_state == "UNAVAILABLE_FOR_ETN_OR_FUND"
            or eps_state == "VENDOR_UNAVAILABLE_ETF_OR_ETN_NO_EPS"
            or pe_state == "NOT_APPLICABLE_ETF_OR_FUND"
        )

        derived_mcap = (
            round(self.ctx.calc_spot * shares, 2) if self.ctx.calc_spot and shares else None
        )
        mcap_note = None
        if shares_state == "VENDOR_PROVIDED_FOREIGN_ISSUER_UNVERIFIED":
            mcap_note = "DERIVED_FROM_UNVERIFIED_FOREIGN_FLOAT"
        elif shares_state == "UNAVAILABLE_FOR_FOREIGN_ADR":
            mcap_note = "ADR_DEPOSITARY_SHARES_UNAVAILABLE"
        elif shares_state == "UNAVAILABLE_FOR_WARRANT":
            mcap_note = "WARRANT_CAPITAL_STRUCTURE_EXCLUDED"

        if derived_mcap is not None and mcap is not None:
            div_abs = abs(derived_mcap - mcap)
            div_pct = round(safe_div(div_abs * 100.0, mcap) or 0.0, 4)
            mcap_div = {
                "derived_market_cap": derived_mcap,
                "reported_market_cap": mcap,
                "market_cap_divergence_abs_usd": div_abs,
                "market_cap_divergence_pct": div_pct,
                "market_cap_divergence_state": (
                    "CALCULATED"
                    if div_pct <= 5.0
                    else "INTEGRITY_FAILURE_REQUIRES_REVIEW"
                ),
                "market_cap_divergence_reason": (
                    "within_5pct_reconciliation_band"
                    if div_pct <= 5.0
                    else "divergence_exceeds_5pct_threshold"
                ),
            }
        elif derived_mcap is not None:
            mcap_div = {
                "derived_market_cap": derived_mcap,
                "reported_market_cap": None,
                "market_cap_divergence_abs_usd": None,
                "market_cap_divergence_pct": None,
                "market_cap_divergence_state": "DERIVED_ONLY_VENDOR_ABSENT",
                "market_cap_divergence_reason": "vendor_does_not_provide_market_cap",
            }
        else:
            if is_halted:
                div_rsn = "asset_halted_or_unquoted_quote_unavailable"
            elif is_warrant:
                div_rsn = "vendor_does_not_provide_shares_for_warrant"
            elif is_etn:
                div_rsn = "vendor_does_not_provide_shares_for_etn_or_fund"
            else:
                div_rsn = "requires_verified_shares_outstanding"
            mcap_div = {
                "derived_market_cap": None,
                "reported_market_cap": mcap,
                "market_cap_divergence_abs_usd": None,
                "market_cap_divergence_pct": None,
                "market_cap_divergence_state": "UNVERIFIED_COMPONENTS",
                "market_cap_divergence_reason": div_rsn,
            }
        if mcap_note:
            mcap_div["market_cap_basis_note"] = mcap_note
        calc: Dict[str, Any] = {"market_cap_divergence": mcap_div}

        spot_near_zero = self.ctx.calc_spot is not None and self.ctx.calc_spot <= 0.01
        eps_non_pos = eps is None or eps <= 0.0 or abs(eps) < 0.01

        near_zero_pe_stub = pe is not None and 0.0 < pe <= 0.05
        class_mismatch_eps = bool(
            self.ctx.calc_spot and eps and eps > self.ctx.calc_spot * 2.0
        )

        if is_halted:
            calc["earnings_yield_state"] = "N/A"
            calc["earnings_yield_reason"] = "asset_halted_or_unquoted_quote_unavailable"
        elif is_warrant:
            calc["earnings_yield_state"] = "N/A"
            calc["earnings_yield_reason"] = "warrant_derivative_instrument_no_corporate_earnings"
        elif is_etn:
            calc["earnings_yield_state"] = "N/A"
            calc["earnings_yield_reason"] = "earnings_negative_or_unstable_pe_ratio_non_positive"
        elif spot_near_zero:
            calc["earnings_yield_state"] = "N/A"
            calc["earnings_yield_reason"] = "spot_price_near_zero_or_negative_earnings"
        elif pe and pe > 0:
            if eps_non_pos:
                calc["earnings_yield_state"] = "N/A"
                if eps is not None and eps < 0.0:
                    calc["earnings_yield_reason"] = "pe_ratio_positive_while_trailing_eps_negative_unreconciled"
                elif eps is not None and 0.0 < eps < 0.01:
                    calc["earnings_yield_reason"] = "pe_ratio_unsupported_by_sub_cent_reported_eps"
                else:
                    calc["earnings_yield_reason"] = "pe_ratio_unsupported_by_non_positive_reported_eps"
            elif near_zero_pe_stub or class_mismatch_eps:
                calc["earnings_yield_state"] = "N/A"
                calc["earnings_yield_reason"] = "pe_ratio_structurally_inconsistent_with_trailing_eps"
            elif self.ctx.calc_spot and (
                (pe * eps / self.ctx.calc_spot > 100.0)
                or (self.ctx.calc_spot / (pe * eps) > 100.0)
            ):
                calc["earnings_yield_state"] = "N/A"
                calc["earnings_yield_reason"] = "pe_ratio_structurally_inconsistent_with_trailing_eps"
            else:
                calc["earnings_yield_pct"] = round(safe_div(100.0, pe) or 0.0, 4)
                calc["earnings_yield_state"] = "CALCULATED"
        elif eps and eps >= 0.01 and self.ctx.calc_spot:
            calc["earnings_yield_pct"] = round(safe_div(eps * 100.0, self.ctx.calc_spot) or 0.0, 4)
            calc["earnings_yield_state"] = "CALCULATED"
        else:
            calc["earnings_yield_state"] = "N/A"
            calc["earnings_yield_reason"] = (
                "spot_price_near_zero_or_negative_earnings"
                if (spot_near_zero or (eps is not None and eps <= 0.0))
                else "earnings_negative_or_unstable_pe_ratio_non_positive"
            )

        has_sub_cent_eps = eps is not None and abs(eps) < 0.01
        imp_pe = (
            safe_div(self.ctx.calc_spot, eps)
            if (
                not is_etn
                and not is_warrant
                and not is_halted
                and self.ctx.calc_spot
                and eps
                and eps > 0
                and not has_sub_cent_eps
            )
            else None
        )

        if is_halted:
            calc["pe_eps_vintage_disparity"] = None
            calc["pe_eps_disparity_state"] = "NOT_APPLICABLE_ASSET_HALTED"
        elif is_warrant or pe_state == "NOT_APPLICABLE_WARRANT":
            calc["pe_eps_vintage_disparity"] = None
            calc["pe_eps_disparity_state"] = "NOT_APPLICABLE_WARRANT"
        elif is_etn or pe_state == "NOT_APPLICABLE_ETF_OR_FUND":
            calc["pe_eps_vintage_disparity"] = None
            calc["pe_eps_disparity_state"] = "NOT_APPLICABLE_ETF_OR_FUND"
        elif not is_etn and pe and pe < 0 and imp_pe and imp_pe > 0:
            calc["pe_eps_vintage_disparity"] = True
            calc["pe_eps_disparity_state"] = "NEGATIVE_REPORTED_PE_POSITIVE_EPS"
            calc["implied_trailing_pe"] = round(imp_pe, 2)
            calc["pe_basis_note"] = "reported_pe_reflects_negative_forward_consensus_vs_positive_trailing_eps"
        elif not is_etn and pe and pe > 0 and (eps is None or eps < 0.0):
            calc["pe_eps_vintage_disparity"] = True
            calc["pe_eps_disparity_state"] = "POSITIVE_REPORTED_PE_NEGATIVE_EPS"
            if eps is not None and eps < 0.0:
                calc["pe_basis_note"] = "reported_pe_positive_while_trailing_eps_negative_unreconciled"
            else:
                calc["pe_basis_note"] = "reported_pe_positive_while_trailing_eps_unavailable"
        elif not is_etn and pe and pe > 0 and imp_pe and imp_pe > 0:
            abs_delta = abs(pe - imp_pe)
            if abs_delta < 0.05 or pe <= 0.05 or imp_pe <= 0.05:
                calc["pe_eps_vintage_disparity"] = False
                calc["pe_eps_disparity_state"] = "WITHIN_TOLERANCE"
                calc["implied_trailing_pe"] = round(imp_pe, 2)
                calc["pe_eps_disparity_pct"] = 0.0
            else:
                disp_pct = round(abs_delta / imp_pe * 100.0, 2)
                has_disp = disp_pct > 50.0 and abs_delta > 2.0
                disp_state = (
                    "SEVERE_VINTAGE_DISPARITY"
                    if disp_pct > 100.0
                    else ("VINTAGE_DISPARITY" if has_disp else "WITHIN_TOLERANCE")
                )
                calc["pe_eps_vintage_disparity"] = has_disp
                calc["pe_eps_disparity_state"] = disp_state
                calc["implied_trailing_pe"] = round(imp_pe, 2)
                calc["pe_eps_disparity_pct"] = disp_pct
                if disp_pct > 100.0:
                    calc["pe_basis_note"] = "SEVERE_DISPARITY_CAUSE_UNVERIFIED"
                elif has_disp:
                    calc["pe_basis_note"] = "reported_pe_reflects_forward_consensus_vs_trailing_eps"
        else:
            calc["pe_eps_vintage_disparity"] = None
            calc["pe_eps_disparity_state"] = "NOT_APPLICABLE"

        is_non_payer = div_y == 0.0 or div_amt == 0.0 or div_y is None
        if is_halted:
            calc["dividend_payout_ratio_state"] = "NOT_APPLICABLE_ASSET_HALTED"
            calc["dividend_payout_ratio_reason"] = "asset_halted_or_unquoted_quote_unavailable"
            calc["dividend_payout_ratio_health"] = "NOT_APPLICABLE"
        elif is_warrant:
            calc["dividend_payout_ratio_state"] = "NOT_APPLICABLE_WARRANT"
            calc["dividend_payout_ratio_reason"] = "warrant_no_dividend_distribution"
            calc["dividend_payout_ratio_health"] = "NOT_APPLICABLE"
        elif is_non_payer:
            calc["dividend_payout_ratio_state"] = "NOT_APPLICABLE_NON_PAYER"
            calc["dividend_payout_ratio_reason"] = "non_payer_no_distribution"
            calc["dividend_payout_ratio_health"] = "NOT_APPLICABLE"
        elif is_etn:
            calc["dividend_payout_ratio_state"] = "NOT_APPLICABLE_ETF_OR_FUND"
            calc["dividend_payout_ratio_reason"] = "etn_fund_no_corporate_eps"
            calc["dividend_payout_ratio_health"] = "CAPITAL_STRUCTURE_UNVERIFIED"
        elif eps_state == "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED":
            calc["dividend_payout_ratio_state"] = "NOT_APPLICABLE_FOREIGN_ADR"
            calc["dividend_payout_ratio_reason"] = "eps_suppressed_for_foreign_adr"
            calc["dividend_payout_ratio_health"] = "CAPITAL_STRUCTURE_UNVERIFIED"
        elif eps is not None and eps >= 0.01:
            payout = safe_div(div_amt * 100.0, eps)
            calc["imputed_dividend_payout_ratio_pct"] = round(payout, 2) if payout is not None else None
            calc["dividend_payout_ratio_state"] = "CALCULATED"
            if payout is not None and payout > 100.0:
                calc["dividend_payout_ratio_health"] = "UNSUSTAINABLE_COVERAGE_DEFICIT"
                calc["payout_exceeds_earnings"] = True
                calc["dividend_deficit_pct"] = round(payout - 100.0, 2)
            elif payout is not None and payout > 75.0:
                calc["dividend_payout_ratio_health"] = "ELEVATED"
                calc["payout_exceeds_earnings"] = False
            else:
                calc["dividend_payout_ratio_health"] = "SUSTAINABLE"
                calc["payout_exceeds_earnings"] = False
        else:
            calc["dividend_payout_ratio_state"] = "UNKNOWN"
            if eps == 0.0:
                calc["dividend_payout_ratio_reason"] = "eps_zero_denominator_hazard"
            elif eps is not None and abs(eps) < 0.01:
                calc["dividend_payout_ratio_reason"] = "eps_sub_cent_denominator_hazard"
            elif eps is not None and eps < 0.0:
                calc["dividend_payout_ratio_reason"] = "negative_eps_unsupported_payout"
            else:
                calc["dividend_payout_ratio_reason"] = "missing_dividend_or_eps_data"
            calc["dividend_payout_ratio_health"] = "UNSUSTAINABLE_OR_DISTORTED"

        if is_halted:
            calc["state"] = "PARTIAL"
            calc["coverage_unknown"] = True
            calc["full_capital_coverage_unknown"] = True
            calc["distribution_coverage_unknown"] = True
            calc["share_count_coverage_unknown"] = True
            calc["coverage_unknown_reason"] = "asset_halted_or_unquoted_quote_unavailable"
        elif is_warrant:
            calc["state"] = "PARTIAL"
            calc["coverage_unknown"] = True
            calc["full_capital_coverage_unknown"] = True
            calc["distribution_coverage_unknown"] = True
            calc["share_count_coverage_unknown"] = True
            calc["coverage_unknown_reason"] = "warrant_derivative_capital_structure"
        elif is_etn:
            calc["state"] = "PARTIAL"
            calc["coverage_unknown"] = True
            calc["full_capital_coverage_unknown"] = True
            calc["distribution_coverage_unknown"] = True
            calc["share_count_coverage_unknown"] = True
            calc["coverage_unknown_reason"] = "etn_or_fund_no_earnings_or_shares"
            if div_y and div_y > 10.0 and self.ctx.calc_spot:
                c_y = safe_div(div_amt * 100.0, self.ctx.calc_spot)
                if c_y:
                    calc["div_yield_vendor_vs_computed_delta_pct"] = round(abs(div_y - c_y), 2)
                    calc["divYield_basis_verified"] = "ANNUAL_VENDOR_CONFIRMED"
        else:
            has_calc = any(
                calc.get(k) is not None
                for k in ["earnings_yield_pct", "imputed_dividend_payout_ratio_pct"]
            )
            calc["state"] = "CALCULATED" if has_calc else "PARTIAL"
            if is_non_payer:
                calc["distribution_coverage_unknown"] = False
                calc["share_count_coverage_unknown"] = False
                calc["coverage_unknown"] = False
                calc["full_capital_coverage_unknown"] = False
                calc["coverage_note"] = "not_applicable_non_payer_no_distribution"
            else:
                calc["distribution_coverage_unknown"] = eps is None or eps <= 0.0
                calc["share_count_coverage_unknown"] = shares is None
                calc["full_capital_coverage_unknown"] = eps is None or shares is None
                calc["coverage_unknown"] = calc["full_capital_coverage_unknown"]
                if eps is None and shares is None:
                    calc["coverage_unknown_reason"] = "dividend_payer_missing_eps_and_shares"
                elif eps is None:
                    calc["coverage_unknown_reason"] = "dividend_payer_missing_eps"
                elif shares is None:
                    calc["coverage_unknown_reason"] = "dividend_payer_missing_shares"
            if eps_state == "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED":
                calc["distribution_coverage_unknown_reason"] = "adr_eps_suppressed_no_coverage_assessment"
            if pe and pe > 0 and (
                eps is None or eps_state == "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED"
            ):
                calc["earnings_yield_basis_note"] = "derived_solely_from_vendor_pe_ratio_eps_unavailable"
        return calc