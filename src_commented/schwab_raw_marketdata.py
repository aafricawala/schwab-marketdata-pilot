"""
schwab_raw_marketdata.py

Facade / backward-compatibility layer. Implementation has been factored into
schwab_* submodules; this module re-exports the public API so existing imports
continue to resolve unchanged.
"""
from __future__ import annotations

# Public API re-exports
from schwab_vendor_resilience import (  # noqa: F401
    parse_client_response,
    retry_vendor_call,
)
from schwab_market_session import extract_market_open_status  # noqa: F401
from schwab_grounding_schema import build_halted_grounding  # noqa: F401
from schwab_price_history import extract_in_memory_price_history  # noqa: F401
from schwab_underlying_grounding import extract_strict_underlying_data  # noqa: F401
from schwab_option_chain import (  # noqa: F401
    extract_in_memory_option_chains,
    extract_in_memory_option_expirations,
    resolve_optimal_expirations,
)

# Backward-compatible private aliases (underscore names preserved for legacy callers)
_parse_client_response = parse_client_response  # noqa: F401
_build_halted_grounding = build_halted_grounding  # noqa: F401