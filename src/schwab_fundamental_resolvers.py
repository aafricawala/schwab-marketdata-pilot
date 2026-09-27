"""
schwab_fundamental_resolvers.py

Pure resolvers for per-instrument fundamental fields. Each returns the same
tuple the inline block in extract_strict_underlying_data produced; bodies are
verbatim from that function.

Extracted (no logic change) from schwab_raw_marketdata.py.
"""
from __future__ import annotations

import math
from typing import Any, Optional, Tuple

from schwab_utils import safe_float


def resolve_shares_outstanding(
    raw_shares: Optional[float],
    is_halted_or_unquoted: bool,
    is_warrant: bool,
    is_structural_wrapper: bool,
    is_foreign_adr: bool,
) -> Tuple[Optional[float], str]:
    shares_val = raw_shares
    if is_halted_or_unquoted:
        shares_state = "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
    elif is_warrant:
        shares_val = None
        shares_state = "UNAVAILABLE_FOR_WARRANT"
    elif is_structural_wrapper:
        shares_val = None
        shares_state = "UNAVAILABLE_FOR_ETN_OR_FUND"
    elif is_foreign_adr:
        shares_state = (
            "VENDOR_PROVIDED_FOREIGN_ISSUER_UNVERIFIED"
            if raw_shares is not None
            else "UNAVAILABLE_FOR_FOREIGN_ADR"
        )
    elif raw_shares is not None and raw_shares > 0:
        shares_state = "CONFIRMED"
    else:
        shares_state = "VENDOR_UNAVAILABLE"
    return shares_val, shares_state


def resolve_pe_eps(
    raw_pe: Optional[float],
    raw_eps: Optional[float],
    is_halted_or_unquoted: bool,
    is_warrant: bool,
    is_structural_wrapper: bool,
    is_foreign_adr: bool,
) -> Tuple[Optional[float], str, Optional[float], str]:
    if is_halted_or_unquoted:
        pe_val, pe_state = None, "VENDOR_UNAVAILABLE_ASSET_HALTED"
        eps_val, eps_state = None, "VENDOR_UNAVAILABLE_ASSET_HALTED"
    elif is_warrant:
        pe_val, pe_state = None, "NOT_APPLICABLE_WARRANT"
        eps_val, eps_state = None, "VENDOR_UNAVAILABLE_WARRANT_NO_EPS"
    elif is_structural_wrapper:
        pe_val, pe_state = None, "NOT_APPLICABLE_ETF_OR_FUND"
        eps_val, eps_state = None, "VENDOR_UNAVAILABLE_ETF_OR_ETN_NO_EPS"
    elif raw_pe is not None and (
        raw_pe >= 9999.0
        or raw_pe <= -9999.0
        or math.isinf(raw_pe)
        or math.isnan(raw_pe)
    ):
        pe_val, pe_state = None, "VENDOR_SENTINEL_MAGNITUDE"
        eps_val = raw_eps
        eps_state = "AS_REPORTED" if raw_eps is not None else "VENDOR_UNAVAILABLE"
    else:
        pe_val = raw_pe
        pe_state = "AS_REPORTED" if raw_pe is not None else "VENDOR_UNAVAILABLE"
        if is_foreign_adr and raw_eps is None:
            eps_val, eps_state = None, "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED"
        else:
            eps_val = raw_eps
            eps_state = "AS_REPORTED" if raw_eps is not None else "VENDOR_UNAVAILABLE"
    return pe_val, pe_state, eps_val, eps_state


def resolve_dividend(
    raw_div_y: Optional[float],
    raw_div_amt: Optional[float],
    raw_div_freq: Optional[float],
    is_halted_or_unquoted: bool,
) -> Tuple[Optional[float], str, Optional[float], Optional[str]]:
    if raw_div_y is None:
        div_y_basis = "VENDOR_UNAVAILABLE"
    elif raw_div_y == 0.0 or raw_div_amt == 0.0:
        div_y_basis = "AS_REPORTED_ZERO_NON_PAYER" if not is_halted_or_unquoted else "VENDOR_UNAVAILABLE"
    elif raw_div_y > 0.0:
        div_y_basis = "ANNUAL_VENDOR_CONFIRMED"
    else:
        div_y_basis = "VENDOR_UNAVAILABLE"

    is_zero_div = (raw_div_y == 0.0 or raw_div_amt == 0.0 or raw_div_y is None)
    div_freq_state = None
    if not is_zero_div and raw_div_y is not None and raw_div_y > 0.0:
        if raw_div_freq is None or raw_div_freq == 0.0:
            div_freq_state = "VENDOR_UNAVAILABLE_FREQUENCY_UNSPECIFIED"
            raw_div_freq = 0.0
    elif is_zero_div:
        if raw_div_freq is not None and raw_div_freq > 0.0:
            div_freq_state = "GHOST_FREQUENCY_RECONCILED_NON_PAYER"
            raw_div_freq = 0.0
        else:
            raw_div_freq = 0.0

    return raw_div_y, div_y_basis, raw_div_freq, div_freq_state


def resolve_margin_sanity(
    net_m: Optional[float],
    op_m: Optional[float],
) -> Tuple[Optional[bool], Optional[str], str]:
    if net_m is not None and op_m is not None:
        if abs(net_m - op_m) < 1e-6 and abs(net_m) > 0.0:
            margin_suspect, margin_reason, margin_state = (
                True,
                "vendor_net_and_operating_margins_identical",
                "SUSPECT_VENDOR_DATA",
            )
        else:
            margin_suspect, margin_reason, margin_state = (
                False,
                "margins_structurally_differentiated",
                "CONFIRMED",
            )
    else:
        margin_suspect, margin_reason, margin_state = (
            None,
            None,
            "VENDOR_UNAVAILABLE_INPUTS_ABSENT",
        )
    return margin_suspect, margin_reason, margin_state