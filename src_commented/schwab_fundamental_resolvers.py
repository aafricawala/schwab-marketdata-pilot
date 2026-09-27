"""
schwab_fundamental_resolvers.py
---
Purpose
Provides simple functions (resolvers) to interpret and validate fundamental financial data (like shares outstanding, P/E ratio, and dividends) for a specific financial instrument. These functions extract logic that was previously mixed in with other code to make it easier to read and test.

Prerequisites
Requires the `schwab_utils` module for utility functions like `safe_float`. Expects raw data inputs representing financial metrics to be passed in from the Schwab API response.

What this module does
1. Resolves the number of outstanding shares and determines the confidence level or state of that value based on the type of asset (e.g., if it's a warrant or an ETF, shares outstanding might not apply).
2. Calculates and verifies the Price-to-Earnings (P/E) ratio and Earnings Per Share (EPS), filtering out invalid or extreme values provided by the vendor.
3. Interprets dividend yield, payout amounts, and payment frequencies, correcting inconsistencies (like a reported zero yield but a non-zero frequency).
4. Checks the sanity of profit margins by comparing net and operating margins to flag suspicious data where the vendor might have accidentally duplicated the values.

Configuration knobs
- None directly. Behavior is driven by the inputs provided to each function.
- Uses a threshold of +/- 9999.0 to detect invalid P/E ratios (magnitude sentinels).
- Uses a tiny margin of error (1e-6) when comparing if two margin values are identical.

Outputs
Provides four main functions: `resolve_shares_outstanding`, `resolve_pe_eps`, `resolve_dividend`, and `resolve_margin_sanity`. Each returns a tuple containing the cleaned/verified values and string labels indicating the status or quality of that data.

Notes
These functions were extracted verbatim from older, inline code (`schwab_raw_marketdata.py`) to preserve the exact original behavior without any logic changes. The returned states (like "CONFIRMED" or "VENDOR_UNAVAILABLE") are used elsewhere to make downstream decisions.
"""

# Enable modern type hinting features, allowing types to be used before they are defined
from __future__ import annotations

# Import the math module to use functions like checking for infinity or Not-a-Number (NaN)
import math
# Import specific types from the typing module to help define what kind of data the functions expect and return
from typing import Any, Optional, Tuple

# Import the safe_float function from our local utilities, though it's not actually used in this specific file
from schwab_utils import safe_float


# Define a function to figure out the correct shares outstanding and its status label
def resolve_shares_outstanding(
    raw_shares: Optional[float],
    is_halted_or_unquoted: bool,
    is_warrant: bool,
    is_structural_wrapper: bool,
    is_foreign_adr: bool,
) -> Tuple[Optional[float], str]:
    # Start by assuming the shares value is exactly what the vendor provided
    shares_val = raw_shares
    # If trading for the asset is paused or it has no price quotes
    if is_halted_or_unquoted:
        # Mark the state to indicate we can't trust the shares data right now
        shares_state = "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
    # If the asset is a warrant (a type of derivative)
    elif is_warrant:
        # Warrants don't have shares outstanding in the same way, so wipe out the value
        shares_val = None
        # Record the reason why we set it to None
        shares_state = "UNAVAILABLE_FOR_WARRANT"
    # If the asset is a fund or ETF (a collection of other assets)
    elif is_structural_wrapper:
        # Funds don't report shares in this field, so wipe it out
        shares_val = None
        # Record the reason
        shares_state = "UNAVAILABLE_FOR_ETN_OR_FUND"
    # If the asset is a foreign stock trading in the US (ADR)
    elif is_foreign_adr:
        # If we actually got a number for the shares
        shares_state = (
            "VENDOR_PROVIDED_FOREIGN_ISSUER_UNVERIFIED"
            if raw_shares is not None
            # Otherwise, if it's missing, mark it unavailable for this specific reason
            else "UNAVAILABLE_FOR_FOREIGN_ADR"
        )
    # For normal stocks, if we have a number and it's greater than zero
    elif raw_shares is not None and raw_shares > 0:
        # We consider the shares data to be good and confirmed
        shares_state = "CONFIRMED"
    # If none of the above applied (meaning it's probably missing or zero)
    else:
        # Just say the vendor didn't provide a valid number
        shares_state = "VENDOR_UNAVAILABLE"
    # Return the final number of shares and the text label describing its state
    return shares_val, shares_state


# Define a function to figure out the P/E ratio, Earnings Per Share, and their status labels
def resolve_pe_eps(
    raw_pe: Optional[float],
    raw_eps: Optional[float],
    is_halted_or_unquoted: bool,
    is_warrant: bool,
    is_structural_wrapper: bool,
    is_foreign_adr: bool,
) -> Tuple[Optional[float], str, Optional[float], str]:
    # If trading is paused or there are no quotes
    if is_halted_or_unquoted:
        # Wipe out the P/E value and note that it's because the asset is halted
        pe_val, pe_state = None, "VENDOR_UNAVAILABLE_ASSET_HALTED"
        # Do the exact same thing for the Earnings Per Share
        eps_val, eps_state = None, "VENDOR_UNAVAILABLE_ASSET_HALTED"
    # If the asset is a warrant
    elif is_warrant:
        # Warrants don't have P/E ratios, so set to None and record the reason
        pe_val, pe_state = None, "NOT_APPLICABLE_WARRANT"
        # Warrants also don't have EPS
        eps_val, eps_state = None, "VENDOR_UNAVAILABLE_WARRANT_NO_EPS"
    # If the asset is an ETF or similar fund
    elif is_structural_wrapper:
        # Funds don't have a direct P/E ratio in this context
        pe_val, pe_state = None, "NOT_APPLICABLE_ETF_OR_FUND"
        # Funds don't have an EPS
        eps_val, eps_state = None, "VENDOR_UNAVAILABLE_ETF_OR_ETN_NO_EPS"
    # For normal stocks, check if the raw P/E ratio looks like a fake placeholder number (very large, infinity, or NaN)
    elif raw_pe is not None and (
        raw_pe >= 9999.0
        or raw_pe <= -9999.0
        or math.isinf(raw_pe)
        or math.isnan(raw_pe)
    ):
        # The P/E is invalid, so wipe it out and mark it as a vendor sentinel (placeholder) value
        pe_val, pe_state = None, "VENDOR_SENTINEL_MAGNITUDE"
        # Keep the raw EPS value as is
        eps_val = raw_eps
        # If we have an EPS, say it's reported as-is; otherwise say it's unavailable
        eps_state = "AS_REPORTED" if raw_eps is not None else "VENDOR_UNAVAILABLE"
    # If the asset is normal and the P/E ratio looks valid
    else:
        # Keep the raw P/E value
        pe_val = raw_pe
        # Mark the P/E state as reported (if it exists) or unavailable
        pe_state = "AS_REPORTED" if raw_pe is not None else "VENDOR_UNAVAILABLE"
        # If it's a foreign stock and the EPS is missing
        if is_foreign_adr and raw_eps is None:
            # Note specifically that it's suppressed because it's a foreign stock
            eps_val, eps_state = None, "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED"
        # Otherwise, handle the EPS normally
        else:
            # Keep the raw EPS value
            eps_val = raw_eps
            # Mark the EPS state as reported (if it exists) or unavailable
            eps_state = "AS_REPORTED" if raw_eps is not None else "VENDOR_UNAVAILABLE"
    # Return all four values: the final P/E, its state, the final EPS, and its state
    return pe_val, pe_state, eps_val, eps_state


# Define a function to figure out the dividend yield, frequency, and their status labels
def resolve_dividend(
    raw_div_y: Optional[float],
    raw_div_amt: Optional[float],
    raw_div_freq: Optional[float],
    is_halted_or_unquoted: bool,
) -> Tuple[Optional[float], str, Optional[float], Optional[str]]:
    # If there is no raw dividend yield provided
    if raw_div_y is None:
        # Mark the yield basis as completely unavailable
        div_y_basis = "VENDOR_UNAVAILABLE"
    # If the yield is exactly zero, or the dividend amount is exactly zero
    elif raw_div_y == 0.0 or raw_div_amt == 0.0:
        # As long as the asset isn't halted, we trust that it just doesn't pay a dividend
        div_y_basis = "AS_REPORTED_ZERO_NON_PAYER" if not is_halted_or_unquoted else "VENDOR_UNAVAILABLE"
    # If the yield is a positive number
    elif raw_div_y > 0.0:
        # We confirm it as an annual yield from the vendor
        div_y_basis = "ANNUAL_VENDOR_CONFIRMED"
    # For any other case (like negative yields, which shouldn't happen)
    else:
        # Just mark it as unavailable
        div_y_basis = "VENDOR_UNAVAILABLE"

    # Create a simple flag to remember if this asset effectively pays zero dividends
    is_zero_div = (raw_div_y == 0.0 or raw_div_amt == 0.0 or raw_div_y is None)
    # Start with no special state for the dividend frequency
    div_freq_state = None
    # If it DOES pay a dividend (not zero) and the yield is positive
    if not is_zero_div and raw_div_y is not None and raw_div_y > 0.0:
        # But the vendor didn't tell us how often it pays (frequency is missing or zero)
        if raw_div_freq is None or raw_div_freq == 0.0:
            # Note that the frequency was missing
            div_freq_state = "VENDOR_UNAVAILABLE_FREQUENCY_UNSPECIFIED"
            # And force the frequency to be exactly zero
            raw_div_freq = 0.0
    # On the other hand, if we already decided it DOES NOT pay a dividend
    elif is_zero_div:
        # But the vendor mysteriously gave us a frequency number anyway
        if raw_div_freq is not None and raw_div_freq > 0.0:
            # Mark this as a "ghost" frequency and we are correcting the mistake
            div_freq_state = "GHOST_FREQUENCY_RECONCILED_NON_PAYER"
            # Force the frequency to be zero since it doesn't pay anything
            raw_div_freq = 0.0
        # If the vendor correctly said the frequency was zero or missing
        else:
            # Just make sure it's exactly zero
            raw_div_freq = 0.0

    # Return the yield, its state, the frequency, and its state
    return raw_div_y, div_y_basis, raw_div_freq, div_freq_state


# Define a function to check if the net margin and operating margin make sense
def resolve_margin_sanity(
    net_m: Optional[float],
    op_m: Optional[float],
) -> Tuple[Optional[bool], Optional[str], str]:
    # Check if we actually received numbers for both margins
    if net_m is not None and op_m is not None:
        # If the two margins are almost exactly the same (within a tiny fraction) AND they aren't zero
        if abs(net_m - op_m) < 1e-6 and abs(net_m) > 0.0:
            # This is suspicious; they should rarely be exactly identical. Set suspect to True, explain why, and mark state
            margin_suspect, margin_reason, margin_state = (
                True,
                "vendor_net_and_operating_margins_identical",
                "SUSPECT_VENDOR_DATA",
            )
        # If they are different (as we expect in the real world)
        else:
            # Mark them as not suspicious, say they are properly different, and confirm the data
            margin_suspect, margin_reason, margin_state = (
                False,
                "margins_structurally_differentiated",
                "CONFIRMED",
            )
    # If we are missing one or both of the margin numbers
    else:
        # Set the flags to None and state that the inputs were absent
        margin_suspect, margin_reason, margin_state = (
            None,
            None,
            "VENDOR_UNAVAILABLE_INPUTS_ABSENT",
        )
    # Return whether it's suspect, the reason why, and the overall state label
    return margin_suspect, margin_reason, margin_state