"""
schwab_marketdata_calculator_types.py

Documentation-only TypedDict shapes for the MasterThesisCalculator output.

IMPORTANT: This module has zero runtime effect on the calculator. It exists
purely to describe the dict shape returned by calculate_metrics() for IDE
assistance, mypy, and downstream consumers who want to type their reads.

The dicts are intentionally permissive: most keys are Optional and several
branches conditionally add keys not enumerated here. Where the original code
can emit a key only on some branches, that key is marked total=False on the
relevant sub-TypedDict. No key is renamed, added to runtime output, or
removed from runtime output by importing this module.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, TypedDict


class MarketCapDivergence(TypedDict, total=False):
    derived_market_cap: Optional[float]
    reported_market_cap: Optional[float]
    market_cap_divergence_abs_usd: Optional[float]
    market_cap_divergence_pct: Optional[float]
    market_cap_divergence_state: str
    market_cap_divergence_reason: str
    market_cap_basis_note: str


class Step0Grounding(TypedDict):
    session_gap_pct: Optional[float]
    state: str
    session_gap_anchor: str


class Step1Fundamentals(TypedDict, total=False):
    # Always present.
    market_cap_divergence: MarketCapDivergence
    earnings_yield_state: str
    pe_eps_disparity_state: str
    dividend_payout_ratio_state: str
    dividend_payout_ratio_health: str
    state: str

    # Conditionally present.
    earnings_yield_pct: Optional[float]
    earnings_yield_reason: str
    earnings_yield_basis_note: str
    pe_eps_vintage_disparity: Optional[bool]
    implied_trailing_pe: float
    pe_eps_disparity_pct: float
    pe_basis_note: str
    imputed_dividend_payout_ratio_pct: Optional[float]
    dividend_payout_ratio_reason: str
    payout_exceeds_earnings: bool
    dividend_deficit_pct: float
    div_yield_vendor_vs_computed_delta_pct: float
    divYield_basis_verified: str
    coverage_unknown: bool
    full_capital_coverage_unknown: bool
    distribution_coverage_unknown: bool
    share_count_coverage_unknown: bool
    coverage_unknown_reason: str
    coverage_note: str
    distribution_coverage_unknown_reason: str


class SpotProvenance(TypedDict):
    source: str
    vintage_risk: str
    observed_price: Optional[float]


class FlowRatios(TypedDict, total=False):
    put_call_volume_ratio: Optional[float]
    put_call_open_interest_ratio: Optional[float]
    volume_regime: str
    state: str
    reason: str
    flow_ratios_note: str
    flow_oi_note: str


class ConstantMaturity30dIV(TypedDict, total=False):
    constant_maturity_30d_iv: Optional[float]
    state: str
    reason: str
    t1_dte: int
    t2_dte: int
    bracket_span_days: int
    bracket_quality: str


class Skew30d(TypedDict, total=False):
    state: str
    reason: str
    skew_delta_anchor: str
    skew_regime: str

    skew_tenor_dte: int
    skew_30d_iv_differential: Optional[float]
    skew_delta_symmetry_gap: float
    skew_actual_put_delta: Optional[float]
    skew_actual_call_delta: Optional[float]
    skew_anchor_reason: str

    spread_tolerance_source: str
    observed_put_relative_spread: Optional[float]
    observed_call_relative_spread: Optional[float]
    spread_zero_bid_flag: bool
    rejected_wing: str
    cmi_bracket_ref: str

    bracket_span_days: int
    bracket_quality: str


class ATMEventStraddle(TypedDict, total=False):
    state: str
    reason: str
    front_expiry_dte: int
    atm_strike: float
    combined_straddle_cost: float
    expected_move_pct: Optional[float]
    factor_basis: str


class Step3And7Derivatives(TypedDict, total=False):
    spot_provenance: SpotProvenance
    flow_ratios: FlowRatios
    constant_maturity_30d_iv: ConstantMaturity30dIV
    skew_30d: Skew30d
    atm_event_straddle: ATMEventStraddle

    # Present only on the empty-chain early return branch.
    state: str
    reason: str


class ClassicalFloorPivots(TypedDict, total=False):
    Pivot: float
    R1: float
    R2: float
    R3: float
    S1: float
    S2: float
    S3: float
    state: str
    reason: str


class RealizedVolHorizon(TypedDict, total=False):
    state: str
    status: str
    reason: str
    target_window_bars: int
    actual_sample_bars: int
    return_observations: int
    computed_realized_vol: float
    close_to_close: Optional[float]
    parkinson: float
    garman_klass: float
    estimator_dispersion_pp: float
    estimator_dispersion_regime: str
    estimator_methodology: str
    listing_seasoning: str
    total_available_bars: int
    sample_bars_note: str
    unsuppressed_dispersion_pp: float
    unsuppressed_garman_klass: float
    unsuppressed_close_to_close: float


RealizedVolSuite = TypedDict(
    "RealizedVolSuite",
    {
        "state": str,
        "reason": str,
        "10d_tactical": RealizedVolHorizon,
        "30d_intermediate": RealizedVolHorizon,
        "252d_macro": RealizedVolHorizon,
    },
    total=False,
)


class Step5Technicals(TypedDict):
    classical_floor_pivots: ClassicalFloorPivots
    realized_volatility: RealizedVolSuite


class MasterThesisMetrics(TypedDict):
    step_0_grounding: Step0Grounding
    step_1_fundamentals_and_quality: Step1Fundamentals
    step_3_and_7_derivatives_and_surface: Step3And7Derivatives
    step_5_technicals_and_flows: Step5Technicals


# Convenience alias used by downstream consumers who only need an untyped view.
MetricsDict = Dict[str, Any]