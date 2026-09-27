"""
schwab_marketdata_calculator_types.py
---
Purpose
Provides strict structural definitions (types) for the complex data dictionaries output by the main market data calculator. This is used entirely for documentation, auto-completion in code editors (IDEs), and static type checking tools (like mypy).

Prerequisites
None beyond standard Python libraries.

What this module does
1. Defines the expected shape of the market capitalization calculation output (`MarketCapDivergence`).
2. Defines the expected shape of the initial price gap checks (`Step0Grounding`).
3. Defines the expected shape of the fundamental analysis output (`Step1Fundamentals`).
4. Defines the shapes for options-related data, like volume ratios, volatility, skew, and straddle costs (`Step3And7Derivatives` and its sub-components).
5. Defines the shapes for technical analysis indicators, like pivot points and historical realized volatility (`Step5Technicals` and its sub-components).
6. Groups all of the above into one master schema definition (`MasterThesisMetrics`).

Configuration knobs
- Uses the `total=False` flag on several `TypedDict` definitions to indicate that some keys are optional and might not always appear in the dictionary, preventing the type checker from throwing false errors.

Outputs
Does not compute or return any actual data at runtime. It only outputs structural definitions used by developers and tools to understand the shape of the data.

Notes
This module has zero effect on how the code actually runs. Changing things here won't change the data produced by the calculator, but it will change how code editors and type checkers perceive that data. It was explicitly designed to be permissive, acknowledging that many keys are conditionally added based on logic branches in the actual calculator code.
"""

# Enable modern type hinting features, allowing types to be used before they are defined
from __future__ import annotations

# Import type hinting tools from the standard typing module to define dictionary structures
from typing import Any, Dict, Optional, TypedDict


# Define the structure for market cap divergence data, allowing some keys to be missing (total=False)
class MarketCapDivergence(TypedDict, total=False):
    # Our calculated market cap might be missing if we couldn't compute it
    derived_market_cap: Optional[float]
    # The vendor's reported market cap might be missing
    reported_market_cap: Optional[float]
    # The absolute dollar difference between the two might be missing
    market_cap_divergence_abs_usd: Optional[float]
    # The percentage difference between the two might be missing
    market_cap_divergence_pct: Optional[float]
    # A string label describing the state of this calculation (e.g., "CONFIRMED" or "DIVERGENT")
    market_cap_divergence_state: str
    # A string explaining the reason for the divergence
    market_cap_divergence_reason: str
    # A string explaining how we determined the market cap
    market_cap_basis_note: str


# Define the structure for the initial "step 0" check, requiring all keys to be present
class Step0Grounding(TypedDict):
    # The percentage difference between the last close and the current price, which could be missing
    session_gap_pct: Optional[float]
    # A string label describing the state (e.g., "GAP_COMPUTED" or "UNAVAILABLE")
    state: str
    # A string explaining what prices were used to calculate the gap
    session_gap_anchor: str


# Define the structure for fundamental data, allowing some keys to be conditionally missing
class Step1Fundamentals(TypedDict, total=False):
    # Always present.
    # Includes the previously defined market cap divergence structure
    market_cap_divergence: MarketCapDivergence
    # A string label describing the state of the earnings yield calculation
    earnings_yield_state: str
    # A string label describing if there's a mismatch between P/E and EPS
    pe_eps_disparity_state: str
    # A string label describing the dividend payout ratio calculation
    dividend_payout_ratio_state: str
    # A string describing if the dividend payout looks healthy or dangerous
    dividend_payout_ratio_health: str
    # An overall status string for this step
    state: str

    # Conditionally present.
    # The calculated earnings yield percentage, if available
    earnings_yield_pct: Optional[float]
    # The reason for the earnings yield state
    earnings_yield_reason: str
    # A note explaining how earnings yield was calculated
    earnings_yield_basis_note: str
    # A boolean indicating if the P/E and EPS data seem to be from different time periods
    pe_eps_vintage_disparity: Optional[bool]
    # A P/E ratio that we calculated ourselves based on the price and EPS
    implied_trailing_pe: float
    # The percentage difference between our calculated P/E and the vendor's P/E
    pe_eps_disparity_pct: float
    # A note explaining how we handled the P/E and EPS
    pe_basis_note: str
    # The calculated dividend payout ratio percentage, if available
    imputed_dividend_payout_ratio_pct: Optional[float]
    # The reason for the dividend payout ratio state
    dividend_payout_ratio_reason: str
    # A boolean flag indicating if the company is paying out more in dividends than it earns
    payout_exceeds_earnings: bool
    # By what percentage the dividend exceeds earnings
    dividend_deficit_pct: float
    # The difference between the vendor's dividend yield and our calculated yield
    div_yield_vendor_vs_computed_delta_pct: float
    # A string indicating how we verified the dividend yield
    divYield_basis_verified: str
    # A boolean flag indicating if we don't have enough data to calculate certain metrics
    coverage_unknown: bool
    # A boolean flag indicating we don't have enough data for capital coverage
    full_capital_coverage_unknown: bool
    # A boolean flag indicating we don't have enough data to check dividend distribution safety
    distribution_coverage_unknown: bool
    # A boolean flag indicating we don't have valid share count data
    share_count_coverage_unknown: bool
    # The reason why general coverage is unknown
    coverage_unknown_reason: str
    # A generic note about data coverage
    coverage_note: str
    # The specific reason why distribution coverage is unknown
    distribution_coverage_unknown_reason: str


# Define the structure for tracking where the current price came from
class SpotProvenance(TypedDict):
    # Where we got the price (e.g., "quote", "trades", "last_close")
    source: str
    # A label describing if the price is old or fresh (e.g., "STALE", "REAL_TIME")
    vintage_risk: str
    # The actual price number we decided to use
    observed_price: Optional[float]


# Define the structure for options flow data, allowing conditionally missing keys
class FlowRatios(TypedDict, total=False):
    # The ratio of put volume to call volume
    put_call_volume_ratio: Optional[float]
    # The ratio of put open interest to call open interest
    put_call_open_interest_ratio: Optional[float]
    # A label describing the volume activity level
    volume_regime: str
    # The overall state of the flow ratios
    state: str
    # The reason for that state
    reason: str
    # A note explaining the volume ratio calculation
    flow_ratios_note: str
    # A note explaining the open interest ratio calculation
    flow_oi_note: str


# Define the structure for 30-day implied volatility calculations
class ConstantMaturity30dIV(TypedDict, total=False):
    # The calculated 30-day implied volatility value
    constant_maturity_30d_iv: Optional[float]
    # The state of the calculation
    state: str
    # The reason for that state
    reason: str
    # The days-to-expiration (DTE) for the near-term options used in the calculation
    t1_dte: int
    # The days-to-expiration (DTE) for the far-term options used in the calculation
    t2_dte: int
    # The number of days between the near and far term options
    bracket_span_days: int
    # A label describing how good the options bracket is for calculation
    bracket_quality: str


# Define the structure for options skew calculations
class Skew30d(TypedDict, total=False):
    # The state of the skew calculation
    state: str
    # The reason for that state
    reason: str
    # Which "delta" value we used as the anchor point for the calculation (e.g., 25 delta)
    skew_delta_anchor: str
    # A label categorizing the shape or severity of the skew
    skew_regime: str

    # The days-to-expiration of the specific options used to calculate the skew
    skew_tenor_dte: int
    # The difference in implied volatility between the put and call wings
    skew_30d_iv_differential: Optional[float]
    # How far off the actual deltas were from our perfect target delta (symmetry gap)
    skew_delta_symmetry_gap: float
    # The actual delta of the put option we used
    skew_actual_put_delta: Optional[float]
    # The actual delta of the call option we used
    skew_actual_call_delta: Optional[float]
    # The reason we chose this specific delta anchor
    skew_anchor_reason: str

    # Where we got the bid/ask spread tolerance rules from
    spread_tolerance_source: str
    # The observed bid/ask spread for the put option
    observed_put_relative_spread: Optional[float]
    # The observed bid/ask spread for the call option
    observed_call_relative_spread: Optional[float]
    # Whether any of the options had a bid of exactly zero
    spread_zero_bid_flag: bool
    # If the spread was too wide, which side was rejected (put or call)
    rejected_wing: str
    # A reference string combining the days to expiration for the bracket used
    cmi_bracket_ref: str

    # The number of days spanning the two expirations if interpolation was used
    bracket_span_days: int
    # The quality of that interpolation bracket
    bracket_quality: str


# Define the structure for estimating the expected move using at-the-money straddles
class ATMEventStraddle(TypedDict, total=False):
    # The state of the calculation
    state: str
    # The reason for that state
    reason: str
    # The days-to-expiration for the options used
    front_expiry_dte: int
    # The exact strike price used for the straddle
    atm_strike: float
    # The total cost of buying the put and the call
    combined_straddle_cost: float
    # The percentage move up or down that the straddle cost implies
    expected_move_pct: Optional[float]
    # A note describing how the calculation was performed
    factor_basis: str


# Combine the options structures into a single derivatives grouping
class Step3And7Derivatives(TypedDict, total=False):
    # Include the price provenance structure
    spot_provenance: SpotProvenance
    # Include the volume/open interest flow ratios
    flow_ratios: FlowRatios
    # Include the 30-day implied volatility
    constant_maturity_30d_iv: ConstantMaturity30dIV
    # Include the 30-day volatility skew
    skew_30d: Skew30d
    # Include the at-the-money straddle calculation
    atm_event_straddle: ATMEventStraddle

    # Present only on the empty-chain early return branch.
    # An overall state for the derivatives step (used if we abort early because there are no options)
    state: str
    # The reason for aborting early
    reason: str


# Define the structure for classical floor pivot support/resistance levels
class ClassicalFloorPivots(TypedDict, total=False):
    # The main pivot point
    Pivot: float
    # Resistance level 1
    R1: float
    # Resistance level 2
    R2: float
    # Resistance level 3
    R3: float
    # Support level 1
    S1: float
    # Support level 2
    S2: float
    # Support level 3
    S3: float
    # The state of the calculation
    state: str
    # The reason for that state
    reason: str


# Define the structure for historical realized volatility calculations over a specific timeframe
class RealizedVolHorizon(TypedDict, total=False):
    # The overall state
    state: str
    # A more specific status indicator
    status: str
    # The reason for the state
    reason: str
    # How many days of data we wanted to use
    target_window_bars: int
    # How many days of data we actually found and used
    actual_sample_bars: int
    # How many daily price returns we observed
    return_observations: int
    # The final, chosen realized volatility percentage
    computed_realized_vol: float
    # Volatility calculated simply using closing prices
    close_to_close: Optional[float]
    # Volatility calculated using high/low prices (Parkinson method)
    parkinson: float
    # Volatility calculated using open/high/low/close prices (Garman-Klass method)
    garman_klass: float
    # The difference in percentage points between the different calculation methods
    estimator_dispersion_pp: float
    # A label describing if the methods agree or disagree significantly
    estimator_dispersion_regime: str
    # Which specific method was chosen for the final computed value
    estimator_methodology: str
    # A label indicating if the asset is too new to have enough history
    listing_seasoning: str
    # The total number of daily price bars available in the dataset
    total_available_bars: int
    # A note about the sample size used
    sample_bars_note: str
    # The raw dispersion before any caps/limits were applied
    unsuppressed_dispersion_pp: float
    # The raw Garman-Klass value before limits
    unsuppressed_garman_klass: float
    # The raw close-to-close value before limits
    unsuppressed_close_to_close: float


# Define a dictionary containing realized volatility calculated across three different timeframes
RealizedVolSuite = TypedDict(
    "RealizedVolSuite",
    {
        # Overall state for the suite
        "state": str,
        # Reason for that state
        "reason": str,
        # Short-term volatility (usually 10 days)
        "10d_tactical": RealizedVolHorizon,
        # Medium-term volatility (usually 30 days)
        "30d_intermediate": RealizedVolHorizon,
        # Long-term volatility (usually 252 days, or one trading year)
        "252d_macro": RealizedVolHorizon,
    },
    total=False,
)


# Combine the technical analysis structures into a single technicals grouping
class Step5Technicals(TypedDict):
    # Include the pivot points
    classical_floor_pivots: ClassicalFloorPivots
    # Include the realized volatility suite
    realized_volatility: RealizedVolSuite


# The master structure that holds everything output by the main calculator script
class MasterThesisMetrics(TypedDict):
    # The initial price gap check
    step_0_grounding: Step0Grounding
    # The fundamental analysis
    step_1_fundamentals_and_quality: Step1Fundamentals
    # The options data analysis
    step_3_and_7_derivatives_and_surface: Step3And7Derivatives
    # The technical analysis
    step_5_technicals_and_flows: Step5Technicals


# Create a simple, untyped alias for generic dictionaries for code that doesn't want to use strict types
MetricsDict = Dict[str, Any]