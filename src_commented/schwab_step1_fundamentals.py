"""
Filename: schwab_step1_fundamentals.py
Purpose: Computes fundamental analysis metrics such as market-cap divergence, earnings yield, PE/EPS disparity, and dividend payout ratio coverage for a given financial asset.
Prerequisites: No special secrets required, but it relies on context objects with vendor market data (`MarketDataContext`) and utility functions.
What this module does:
1. Calculates market capitalization divergence (derived vs reported).
2. Computes the earnings yield of the asset.
3. Analyzes the disparity between PE ratio and EPS (vintage disparity).
4. Assesses the dividend payout ratio and its sustainability/health.
5. Sets coverage flags indicating missing or partial data states.
Configuration knobs: None explicitly.
Outputs: Returns a dictionary of computed fundamental metrics and analytical state/health flags.
Notes: Carefully handles edge cases like halted assets, warrants, and ETFs/ETNs which lack standard corporate earnings.
"""
# Import the annotations feature from future to enable forward references in type hints
from __future__ import annotations

# Import Any and Dict from the typing module for type annotations
from typing import Any, Dict

# Import the MarketDataContext class to access the shared state and market data
from schwab_marketdata_context import MarketDataContext
# Import utility functions for safe division and safe float conversion
from schwab_utils import safe_div, safe_float


# Define a class responsible for computing step 1 fundamental metrics
class Step1FundamentalsCalculator:

    # Define the initialization method which takes a MarketDataContext instance
    def __init__(self, ctx: MarketDataContext):
        # Store the context instance as an instance variable
        self.ctx = ctx

    # Define the main calculation method that returns a dictionary of metrics
    def calculate(self) -> Dict[str, Any]:
        # Safely extract and convert the PE ratio from fundamental data
        pe = safe_float(self.ctx.fund.get("peRatio"))
        # Safely extract and convert the Earnings Per Share (EPS) from fundamental data
        eps = safe_float(self.ctx.fund.get("eps"))
        # Safely extract and convert the dividend amount from fundamental data
        div_amt = safe_float(self.ctx.fund.get("divAmount"))
        # Safely extract and convert the dividend yield percentage
        div_y = safe_float(self.ctx.fund.get("divYield"))
        # Safely extract and convert the number of outstanding shares
        shares = safe_float(self.ctx.fund.get("sharesOutstanding"))
        # Safely extract and convert the reported market capitalization
        mcap = safe_float(self.ctx.fund.get("marketCap"))
        # Extract the state flag for EPS, defaulting to an empty string if missing
        eps_state = str(self.ctx.fund.get("eps_state") or "")
        # Extract the state flag for the PE ratio, defaulting to an empty string
        pe_state = str(self.ctx.fund.get("peRatio_state") or "")
        # Extract the state flag for shares outstanding, defaulting to an empty string
        shares_state = str(self.ctx.fund.get("shares_outstanding_state") or "")

        # Determine if the asset is halted by checking various state flags for halted/unquoted keywords
        is_halted = (
            self.ctx.q_class == "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
            or shares_state == "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
            or eps_state == "VENDOR_UNAVAILABLE_ASSET_HALTED"
            or pe_state == "VENDOR_UNAVAILABLE_ASSET_HALTED"
        )
        # Determine if the asset is a warrant by checking related state flags
        is_warrant = (
            shares_state == "UNAVAILABLE_FOR_WARRANT"
            or eps_state == "VENDOR_UNAVAILABLE_WARRANT_NO_EPS"
            or pe_state == "NOT_APPLICABLE_WARRANT"
        )
        # Determine if the asset is an ETN/ETF, ensuring it is not halted or a warrant first
        is_etn = not is_halted and not is_warrant and (
            shares_state == "UNAVAILABLE_FOR_ETN_OR_FUND"
            or eps_state == "VENDOR_UNAVAILABLE_ETF_OR_ETN_NO_EPS"
            or pe_state == "NOT_APPLICABLE_ETF_OR_FUND"
        )

        # Calculate a derived market cap by multiplying spot price by outstanding shares if both exist
        derived_mcap = (
            round(self.ctx.calc_spot * shares, 2) if self.ctx.calc_spot and shares else None
        )
        # Initialize a variable to hold any specific note regarding the market cap basis
        mcap_note = None
        # Check if shares are from an unverified foreign issuer
        if shares_state == "VENDOR_PROVIDED_FOREIGN_ISSUER_UNVERIFIED":
            # Assign a specific note for unverified foreign float
            mcap_note = "DERIVED_FROM_UNVERIFIED_FOREIGN_FLOAT"
        # Check if shares are unavailable because the asset is a foreign ADR
        elif shares_state == "UNAVAILABLE_FOR_FOREIGN_ADR":
            # Assign a specific note for ADR depositary shares
            mcap_note = "ADR_DEPOSITARY_SHARES_UNAVAILABLE"
        # Check if shares are unavailable because the asset is a warrant
        elif shares_state == "UNAVAILABLE_FOR_WARRANT":
            # Assign a specific note for warrant capital structures
            mcap_note = "WARRANT_CAPITAL_STRUCTURE_EXCLUDED"

        # Check if we successfully calculated a derived market cap AND a reported market cap exists
        if derived_mcap is not None and mcap is not None:
            # Calculate the absolute difference between the derived and reported market cap
            div_abs = abs(derived_mcap - mcap)
            # Calculate the percentage difference, defaulting to 0.0 if division fails
            div_pct = round(safe_div(div_abs * 100.0, mcap) or 0.0, 4)
            # Create a dictionary containing all the market cap divergence metrics
            mcap_div = {
                "derived_market_cap": derived_mcap,
                "reported_market_cap": mcap,
                "market_cap_divergence_abs_usd": div_abs,
                "market_cap_divergence_pct": div_pct,
                # Assign a status indicating whether the divergence is within a 5% tolerance
                "market_cap_divergence_state": (
                    "CALCULATED"
                    if div_pct <= 5.0
                    else "INTEGRITY_FAILURE_REQUIRES_REVIEW"
                ),
                # Assign a human-readable reason detailing why it passed or failed
                "market_cap_divergence_reason": (
                    "within_5pct_reconciliation_band"
                    if div_pct <= 5.0
                    else "divergence_exceeds_5pct_threshold"
                ),
            }
        # Check if only the derived market cap was calculated but reported is missing
        elif derived_mcap is not None:
            # Create a dictionary noting that the vendor did not provide a market cap
            mcap_div = {
                "derived_market_cap": derived_mcap,
                "reported_market_cap": None,
                "market_cap_divergence_abs_usd": None,
                "market_cap_divergence_pct": None,
                "market_cap_divergence_state": "DERIVED_ONLY_VENDOR_ABSENT",
                "market_cap_divergence_reason": "vendor_does_not_provide_market_cap",
            }
        # Handle the fallback scenario where derived market cap cannot be calculated
        else:
            # Check if the missing derived cap is due to the asset being halted
            if is_halted:
                # Set the reason string to halted asset
                div_rsn = "asset_halted_or_unquoted_quote_unavailable"
            # Check if the missing derived cap is due to the asset being a warrant
            elif is_warrant:
                # Set the reason string to warrant exclusion
                div_rsn = "vendor_does_not_provide_shares_for_warrant"
            # Check if the missing derived cap is due to the asset being an ETN/fund
            elif is_etn:
                # Set the reason string to ETN/fund exclusion
                div_rsn = "vendor_does_not_provide_shares_for_etn_or_fund"
            # Handle any other reason
            else:
                # Note that verified shares outstanding are required to calculate it
                div_rsn = "requires_verified_shares_outstanding"
            # Create a dictionary populating nulls for derived metrics and logging the failure reason
            mcap_div = {
                "derived_market_cap": None,
                "reported_market_cap": mcap,
                "market_cap_divergence_abs_usd": None,
                "market_cap_divergence_pct": None,
                "market_cap_divergence_state": "UNVERIFIED_COMPONENTS",
                "market_cap_divergence_reason": div_rsn,
            }
        # If a special note was generated during the shares inspection, add it to the divergence dictionary
        if mcap_note:
            # Append the note to the dictionary
            mcap_div["market_cap_basis_note"] = mcap_note
        # Initialize the main calculations dictionary with the populated market cap divergence payload
        calc: Dict[str, Any] = {"market_cap_divergence": mcap_div}

        # Check if the spot price is effectively near zero
        spot_near_zero = self.ctx.calc_spot is not None and self.ctx.calc_spot <= 0.01
        # Check if the EPS is missing, zero, or slightly negative (near zero)
        eps_non_pos = eps is None or eps <= 0.0 or abs(eps) < 0.01

        # Check if the PE ratio is a tiny positive stub value indicating potential errors
        near_zero_pe_stub = pe is not None and 0.0 < pe <= 0.05
        # Identify a severe mismatch where EPS is more than double the entire spot price
        class_mismatch_eps = bool(
            self.ctx.calc_spot and eps and eps > self.ctx.calc_spot * 2.0
        )

        # Handle earnings yield calculation failures when asset is halted
        if is_halted:
            # Set the earnings yield state to not applicable
            calc["earnings_yield_state"] = "N/A"
            # Set the reason indicating quotes are unavailable
            calc["earnings_yield_reason"] = "asset_halted_or_unquoted_quote_unavailable"
        # Handle earnings yield failures for warrants
        elif is_warrant:
            # Set the earnings yield state to not applicable
            calc["earnings_yield_state"] = "N/A"
            # Note that warrants do not have corporate earnings
            calc["earnings_yield_reason"] = "warrant_derivative_instrument_no_corporate_earnings"
        # Handle earnings yield failures for ETNs
        elif is_etn:
            # Set the earnings yield state to not applicable
            calc["earnings_yield_state"] = "N/A"
            # Note that ETNs lack stable corporate earnings structures
            calc["earnings_yield_reason"] = "earnings_negative_or_unstable_pe_ratio_non_positive"
        # Handle failures when the underlying price is too low to compute meaningful yield
        elif spot_near_zero:
            # Set the earnings yield state to not applicable
            calc["earnings_yield_state"] = "N/A"
            # Note that the spot price is too near zero
            calc["earnings_yield_reason"] = "spot_price_near_zero_or_negative_earnings"
        # Proceed to evaluate earnings yield if a valid, positive PE is provided
        elif pe and pe > 0:
            # Check if despite a positive PE, the EPS is non-positive
            if eps_non_pos:
                # Set state to N/A because of structural inconsistency
                calc["earnings_yield_state"] = "N/A"
                # Sub-check if EPS is strictly negative
                if eps is not None and eps < 0.0:
                    # Note the unreconciled contradiction (positive PE, negative EPS)
                    calc["earnings_yield_reason"] = "pe_ratio_positive_while_trailing_eps_negative_unreconciled"
                # Sub-check if EPS is a tiny positive number
                elif eps is not None and 0.0 < eps < 0.01:
                    # Note that sub-cent EPS doesn't support the PE securely
                    calc["earnings_yield_reason"] = "pe_ratio_unsupported_by_sub_cent_reported_eps"
                # Fallback condition for zero or absent EPS
                else:
                    # Note that non-positive EPS invalidates the PE
                    calc["earnings_yield_reason"] = "pe_ratio_unsupported_by_non_positive_reported_eps"
            # Check if PE is extremely small or EPS is impossibly large compared to price
            elif near_zero_pe_stub or class_mismatch_eps:
                # Set the state to N/A due to structural inconsistency
                calc["earnings_yield_state"] = "N/A"
                # Note the reason for rejection
                calc["earnings_yield_reason"] = "pe_ratio_structurally_inconsistent_with_trailing_eps"
            # Check if the calculated spot implied by PE and EPS diverges massively from actual spot (ratio > 100)
            elif self.ctx.calc_spot and (
                (pe * eps / self.ctx.calc_spot > 100.0)
                or (self.ctx.calc_spot / (pe * eps) > 100.0)
            ):
                # Set the state to N/A due to extreme mathematical divergence
                calc["earnings_yield_state"] = "N/A"
                # Note the structural inconsistency failure
                calc["earnings_yield_reason"] = "pe_ratio_structurally_inconsistent_with_trailing_eps"
            # If all validations pass, calculate earnings yield from PE
            else:
                # Earnings yield is calculated as the inverse of PE (1/PE) expressed as percentage
                calc["earnings_yield_pct"] = round(safe_div(100.0, pe) or 0.0, 4)
                # Mark the state as successfully calculated
                calc["earnings_yield_state"] = "CALCULATED"
        # If PE was missing or zero, but we have valid EPS and a spot price, derive yield from them directly
        elif eps and eps >= 0.01 and self.ctx.calc_spot:
            # Earnings yield is calculated as (EPS / Price) * 100
            calc["earnings_yield_pct"] = round(safe_div(eps * 100.0, self.ctx.calc_spot) or 0.0, 4)
            # Mark the state as successfully calculated
            calc["earnings_yield_state"] = "CALCULATED"
        # Fallback condition where no valid earnings yield can be computed
        else:
            # Set the state to N/A
            calc["earnings_yield_state"] = "N/A"
            # Provide a reason based on whether spot was near zero, EPS was negative, or just unstable data
            calc["earnings_yield_reason"] = (
                "spot_price_near_zero_or_negative_earnings"
                if (spot_near_zero or (eps is not None and eps <= 0.0))
                else "earnings_negative_or_unstable_pe_ratio_non_positive"
            )

        # Flag indicating if the EPS is extremely small (sub-cent) which can blow up math divisions
        has_sub_cent_eps = eps is not None and abs(eps) < 0.01
        # Attempt to compute an implied PE (Price / EPS) directly from the current quote
        imp_pe = (
            safe_div(self.ctx.calc_spot, eps)
            # Only compute if asset isn't ETN, warrant, halted, and both spot/eps are valid positive numbers without sub-cent issues
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

        # Handle PE/EPS disparity state for halted assets
        if is_halted:
            # Nullify disparity value since asset is halted
            calc["pe_eps_vintage_disparity"] = None
            # Set state to not applicable due to halt
            calc["pe_eps_disparity_state"] = "NOT_APPLICABLE_ASSET_HALTED"
        # Handle PE/EPS disparity state for warrants
        elif is_warrant or pe_state == "NOT_APPLICABLE_WARRANT":
            # Nullify disparity value since warrants don't have PEs
            calc["pe_eps_vintage_disparity"] = None
            # Set state to not applicable for warrants
            calc["pe_eps_disparity_state"] = "NOT_APPLICABLE_WARRANT"
        # Handle PE/EPS disparity state for ETNs/Funds
        elif is_etn or pe_state == "NOT_APPLICABLE_ETF_OR_FUND":
            # Nullify disparity value for funds
            calc["pe_eps_vintage_disparity"] = None
            # Set state to not applicable for ETFs
            calc["pe_eps_disparity_state"] = "NOT_APPLICABLE_ETF_OR_FUND"
        # Check for a contradiction: reported PE is negative while calculated implied PE is positive
        elif not is_etn and pe and pe < 0 and imp_pe and imp_pe > 0:
            # Mark that a disparity exists
            calc["pe_eps_vintage_disparity"] = True
            # Set the disparity state flag
            calc["pe_eps_disparity_state"] = "NEGATIVE_REPORTED_PE_POSITIVE_EPS"
            # Store the computed implied PE for reference
            calc["implied_trailing_pe"] = round(imp_pe, 2)
            # Add a note explaining this usually happens when forward consensus is negative but trailing is positive
            calc["pe_basis_note"] = "reported_pe_reflects_negative_forward_consensus_vs_positive_trailing_eps"
        # Check for opposite contradiction: reported PE is positive but trailing EPS is negative or missing
        elif not is_etn and pe and pe > 0 and (eps is None or eps < 0.0):
            # Mark that a disparity exists
            calc["pe_eps_vintage_disparity"] = True
            # Set the disparity state flag
            calc["pe_eps_disparity_state"] = "POSITIVE_REPORTED_PE_NEGATIVE_EPS"
            # If the EPS is explicitly negative
            if eps is not None and eps < 0.0:
                # Note the unreconciled contradiction
                calc["pe_basis_note"] = "reported_pe_positive_while_trailing_eps_negative_unreconciled"
            # If EPS is completely missing
            else:
                # Note that trailing EPS is missing but PE is provided
                calc["pe_basis_note"] = "reported_pe_positive_while_trailing_eps_unavailable"
        # Handle cases where both reported PE and implied PE are positive and valid
        elif not is_etn and pe and pe > 0 and imp_pe and imp_pe > 0:
            # Calculate the absolute difference between reported PE and implied PE
            abs_delta = abs(pe - imp_pe)
            # If the difference is very small (within tolerance) or values are tiny
            if abs_delta < 0.05 or pe <= 0.05 or imp_pe <= 0.05:
                # Mark that no significant disparity exists
                calc["pe_eps_vintage_disparity"] = False
                # Set the state to within tolerance
                calc["pe_eps_disparity_state"] = "WITHIN_TOLERANCE"
                # Store the implied trailing PE
                calc["implied_trailing_pe"] = round(imp_pe, 2)
                # Note zero percentage disparity
                calc["pe_eps_disparity_pct"] = 0.0
            # If there is a meaningful difference between reported and implied PEs
            else:
                # Calculate the percentage difference relative to implied PE
                disp_pct = round(abs_delta / imp_pe * 100.0, 2)
                # Define a disparity as being > 50% relative and > 2.0 absolute
                has_disp = disp_pct > 50.0 and abs_delta > 2.0
                # Determine the severity state based on percentage
                disp_state = (
                    "SEVERE_VINTAGE_DISPARITY"
                    if disp_pct > 100.0
                    else ("VINTAGE_DISPARITY" if has_disp else "WITHIN_TOLERANCE")
                )
                # Set the boolean flag for whether a significant disparity exists
                calc["pe_eps_vintage_disparity"] = has_disp
                # Record the calculated severity state
                calc["pe_eps_disparity_state"] = disp_state
                # Store the implied trailing PE
                calc["implied_trailing_pe"] = round(imp_pe, 2)
                # Record the exact disparity percentage
                calc["pe_eps_disparity_pct"] = disp_pct
                # If the disparity is extreme (over 100%)
                if disp_pct > 100.0:
                    # Note that the cause is unverified and severe
                    calc["pe_basis_note"] = "SEVERE_DISPARITY_CAUSE_UNVERIFIED"
                # If the disparity exists but is moderate
                elif has_disp:
                    # Note this often occurs because vendor PE uses forward estimates while implied PE uses trailing actuals
                    calc["pe_basis_note"] = "reported_pe_reflects_forward_consensus_vs_trailing_eps"
        # Fallback for any other unhandled disparity conditions
        else:
            # Nullify disparity flag
            calc["pe_eps_vintage_disparity"] = None
            # Set state to not applicable
            calc["pe_eps_disparity_state"] = "NOT_APPLICABLE"

        # Determine if the asset is a non-dividend payer (yield or amount is zero or missing)
        is_non_payer = div_y == 0.0 or div_amt == 0.0 or div_y is None
        # Handle payout ratio for halted assets
        if is_halted:
            # Set state to not applicable due to halt
            calc["dividend_payout_ratio_state"] = "NOT_APPLICABLE_ASSET_HALTED"
            # Note quotes are unavailable
            calc["dividend_payout_ratio_reason"] = "asset_halted_or_unquoted_quote_unavailable"
            # Set health status to not applicable
            calc["dividend_payout_ratio_health"] = "NOT_APPLICABLE"
        # Handle payout ratio for warrants
        elif is_warrant:
            # Set state to not applicable for warrants
            calc["dividend_payout_ratio_state"] = "NOT_APPLICABLE_WARRANT"
            # Note warrants do not distribute dividends
            calc["dividend_payout_ratio_reason"] = "warrant_no_dividend_distribution"
            # Set health status to not applicable
            calc["dividend_payout_ratio_health"] = "NOT_APPLICABLE"
        # Handle payout ratio for non-dividend paying stocks
        elif is_non_payer:
            # Set state to not applicable for non-payers
            calc["dividend_payout_ratio_state"] = "NOT_APPLICABLE_NON_PAYER"
            # Note there is no distribution
            calc["dividend_payout_ratio_reason"] = "non_payer_no_distribution"
            # Set health status to not applicable
            calc["dividend_payout_ratio_health"] = "NOT_APPLICABLE"
        # Handle payout ratio for ETNs/Funds
        elif is_etn:
            # Set state to not applicable for funds
            calc["dividend_payout_ratio_state"] = "NOT_APPLICABLE_ETF_OR_FUND"
            # Note that funds lack standard corporate EPS structures for payout math
            calc["dividend_payout_ratio_reason"] = "etn_fund_no_corporate_eps"
            # Note health is unverified because capital structure isn't corporate
            calc["dividend_payout_ratio_health"] = "CAPITAL_STRUCTURE_UNVERIFIED"
        # Handle payout ratio for foreign ADRs with suppressed EPS data
        elif eps_state == "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED":
            # Set state to not applicable due to foreign ADR
            calc["dividend_payout_ratio_state"] = "NOT_APPLICABLE_FOREIGN_ADR"
            # Note EPS is suppressed
            calc["dividend_payout_ratio_reason"] = "eps_suppressed_for_foreign_adr"
            # Note health is unverified
            calc["dividend_payout_ratio_health"] = "CAPITAL_STRUCTURE_UNVERIFIED"
        # Calculate payout ratio if EPS is valid and positive
        elif eps is not None and eps >= 0.01:
            # Payout ratio is calculated as (Dividend Amount / EPS) * 100
            payout = safe_div(div_amt * 100.0, eps)
            # Store the computed payout ratio, rounding to 2 decimals
            calc["imputed_dividend_payout_ratio_pct"] = round(payout, 2) if payout is not None else None
            # Set the state indicating a successful calculation
            calc["dividend_payout_ratio_state"] = "CALCULATED"
            # Evaluate health: if payout is over 100% of earnings
            if payout is not None and payout > 100.0:
                # Mark the health as unsustainable since dividend exceeds earnings
                calc["dividend_payout_ratio_health"] = "UNSUSTAINABLE_COVERAGE_DEFICIT"
                # Flag that payout exceeds earnings
                calc["payout_exceeds_earnings"] = True
                # Calculate and record the exact deficit percentage
                calc["dividend_deficit_pct"] = round(payout - 100.0, 2)
            # Evaluate health: if payout is between 75% and 100% of earnings
            elif payout is not None and payout > 75.0:
                # Mark health as elevated
                calc["dividend_payout_ratio_health"] = "ELEVATED"
                # Flag that payout does not exceed earnings
                calc["payout_exceeds_earnings"] = False
            # Evaluate health: if payout is below 75%
            else:
                # Mark health as sustainable
                calc["dividend_payout_ratio_health"] = "SUSTAINABLE"
                # Flag that payout does not exceed earnings
                calc["payout_exceeds_earnings"] = False
        # Fallback condition where EPS is invalid for payout ratio math (e.g. negative or zero)
        else:
            # Set payout state to unknown
            calc["dividend_payout_ratio_state"] = "UNKNOWN"
            # Check specifically for zero EPS
            if eps == 0.0:
                # Note zero denominator hazard
                calc["dividend_payout_ratio_reason"] = "eps_zero_denominator_hazard"
            # Check for near-zero sub-cent EPS
            elif eps is not None and abs(eps) < 0.01:
                # Note sub-cent denominator hazard which inflates ratios absurdly
                calc["dividend_payout_ratio_reason"] = "eps_sub_cent_denominator_hazard"
            # Check for negative EPS
            elif eps is not None and eps < 0.0:
                # Note that negative EPS cannot support a dividend payout
                calc["dividend_payout_ratio_reason"] = "negative_eps_unsupported_payout"
            # General fallback for missing data
            else:
                # Note missing inputs
                calc["dividend_payout_ratio_reason"] = "missing_dividend_or_eps_data"
            # Mark health as unsustainable or distorted due to invalid inputs
            calc["dividend_payout_ratio_health"] = "UNSUSTAINABLE_OR_DISTORTED"

        # Final coverage flag summary - check if asset is halted
        if is_halted:
            # Set overall module state to partial
            calc["state"] = "PARTIAL"
            # Set coverage unknown flags to True
            calc["coverage_unknown"] = True
            # Flag capital coverage as unknown
            calc["full_capital_coverage_unknown"] = True
            # Flag distribution coverage as unknown
            calc["distribution_coverage_unknown"] = True
            # Flag share count coverage as unknown
            calc["share_count_coverage_unknown"] = True
            # Provide reason for unknown coverage due to halt
            calc["coverage_unknown_reason"] = "asset_halted_or_unquoted_quote_unavailable"
        # Final coverage flag summary - check if asset is a warrant
        elif is_warrant:
            # Set overall module state to partial
            calc["state"] = "PARTIAL"
            # Set coverage unknown flags to True
            calc["coverage_unknown"] = True
            # Flag capital coverage as unknown
            calc["full_capital_coverage_unknown"] = True
            # Flag distribution coverage as unknown
            calc["distribution_coverage_unknown"] = True
            # Flag share count coverage as unknown
            calc["share_count_coverage_unknown"] = True
            # Provide reason due to derivative structure
            calc["coverage_unknown_reason"] = "warrant_derivative_capital_structure"
        # Final coverage flag summary - check if asset is an ETN/Fund
        elif is_etn:
            # Set overall module state to partial
            calc["state"] = "PARTIAL"
            # Set coverage unknown flags to True
            calc["coverage_unknown"] = True
            # Flag capital coverage as unknown
            calc["full_capital_coverage_unknown"] = True
            # Flag distribution coverage as unknown
            calc["distribution_coverage_unknown"] = True
            # Flag share count coverage as unknown
            calc["share_count_coverage_unknown"] = True
            # Provide reason due to lack of corporate earnings/shares
            calc["coverage_unknown_reason"] = "etn_or_fund_no_earnings_or_shares"
            # If the fund has a very high yield reported, check it against implied yield
            if div_y and div_y > 10.0 and self.ctx.calc_spot:
                # Compute yield based on dividend amount and current spot price
                c_y = safe_div(div_amt * 100.0, self.ctx.calc_spot)
                # If a computed yield could be determined
                if c_y:
                    # Calculate the delta between the vendor reported yield and our computed yield
                    calc["div_yield_vendor_vs_computed_delta_pct"] = round(abs(div_y - c_y), 2)
                    # Note that the yield basis is vendor confirmed
                    calc["divYield_basis_verified"] = "ANNUAL_VENDOR_CONFIRMED"
        # Final coverage flag summary for standard corporate equities
        else:
            # Determine if at least one of the primary yields or ratios was successfully calculated
            has_calc = any(
                calc.get(k) is not None
                for k in ["earnings_yield_pct", "imputed_dividend_payout_ratio_pct"]
            )
            # Set the overall state to CALCULATED if true, otherwise PARTIAL
            calc["state"] = "CALCULATED" if has_calc else "PARTIAL"
            # Check if the asset doesn't pay dividends
            if is_non_payer:
                # Flag that distribution coverage is known (it's legitimately zero)
                calc["distribution_coverage_unknown"] = False
                # Flag that share count coverage is known
                calc["share_count_coverage_unknown"] = False
                # Overall coverage is not unknown
                calc["coverage_unknown"] = False
                # Capital coverage is not unknown
                calc["full_capital_coverage_unknown"] = False
                # Note that it simply doesn't distribute dividends
                calc["coverage_note"] = "not_applicable_non_payer_no_distribution"
            # For dividend paying equities
            else:
                # Distribution coverage is unknown if EPS is missing or zero/negative
                calc["distribution_coverage_unknown"] = eps is None or eps <= 0.0
                # Share coverage is unknown if shares are missing
                calc["share_count_coverage_unknown"] = shares is None
                # Full capital coverage is unknown if either EPS or shares are missing
                calc["full_capital_coverage_unknown"] = eps is None or shares is None
                # Overall coverage unknown matches full capital coverage
                calc["coverage_unknown"] = calc["full_capital_coverage_unknown"]
                # Determine the specific reason if both are missing
                if eps is None and shares is None:
                    # Note both are missing
                    calc["coverage_unknown_reason"] = "dividend_payer_missing_eps_and_shares"
                # Determine reason if only EPS is missing
                elif eps is None:
                    # Note EPS is missing
                    calc["coverage_unknown_reason"] = "dividend_payer_missing_eps"
                # Determine reason if only shares are missing
                elif shares is None:
                    # Note shares are missing
                    calc["coverage_unknown_reason"] = "dividend_payer_missing_shares"
            # Special case for ADRs with suppressed EPS
            if eps_state == "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED":
                # Note that distribution coverage is unknown specifically because of ADR suppression
                calc["distribution_coverage_unknown_reason"] = "adr_eps_suppressed_no_coverage_assessment"
            # Special case where PE exists but EPS is suppressed or missing
            if pe and pe > 0 and (
                eps is None or eps_state == "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED"
            ):
                # Add a note explaining that earnings yield had to rely solely on PE without EPS confirmation
                calc["earnings_yield_basis_note"] = "derived_solely_from_vendor_pe_ratio_eps_unavailable"
        # Return the final, fully populated calculations dictionary
        return calc
