"""
schwab_raw_marketdata.py
---
Purpose
Acts as a central access point (facade) for various market data functions that have been moved to other specialized files. It ensures that older code that imports from this file will still work without needing to be rewritten.

Prerequisites
Requires the various submodule files to be present in the same directory or Python path (e.g., `schwab_vendor_resilience`, `schwab_market_session`, `schwab_grounding_schema`, `schwab_price_history`, `schwab_underlying_grounding`, `schwab_option_chain`).

What this module does
1. Imports key functions from newly created, highly specific submodules.
2. Re-exports these functions so that if another part of the program imports from `schwab_raw_marketdata.py`, it still gets the correct function seamlessly.
3. Provides aliases (alternative names) for certain functions to maintain compatibility with older code that might have used underscores in the function names.

Configuration knobs
- None. This is strictly a routing/re-exporting file.

Outputs
Does not generate any new data or perform logic. It outputs (exposes) functions imported from other modules.

Notes
This is a standard Python pattern called a "facade" or "barrel" file. The `# noqa: F401` comments tell code-checking tools to ignore the fact that these imported functions aren't used directly inside this specific file, because their purpose is to be exported for others to use.
"""

# Enable modern type hinting features, allowing types to be used before they are defined
from __future__ import annotations

# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

# Import specific networking and retry functions from the vendor resilience module
from schwab_vendor_resilience import (  # noqa: F401 (Ignore unused import warning, as this is meant to be exported)
    parse_client_response,
    retry_vendor_call,
)
# Import the function that checks if the market is open from the market session module
from schwab_market_session import extract_market_open_status  # noqa: F401

# Import the function that builds a basic data schema for halted assets
from schwab_grounding_schema import build_halted_grounding  # noqa: F401

# Import the function that gets historical price data from the price history module
from schwab_price_history import extract_in_memory_price_history  # noqa: F401

# Import the function that pulls out detailed fundamental data for a stock from the underlying grounding module
from schwab_underlying_grounding import extract_strict_underlying_data  # noqa: F401

# Import functions related to options trading (like expiration dates and chains) from the option chain module
from schwab_option_chain import (  # noqa: F401
    extract_in_memory_option_chains,
    extract_in_memory_option_expirations,
    resolve_optimal_expirations,
)

# ---------------------------------------------------------------------------
# Backward-compatible private aliases
# ---------------------------------------------------------------------------
# Create a private-looking name (_parse_client_response) that points to the imported parse_client_response function,
# just in case older legacy code is still trying to call the private version.
_parse_client_response = parse_client_response  # noqa: F401

# Create a private-looking name (_build_halted_grounding) that points to the imported build_halted_grounding function,
# again, to ensure older code doesn't break.
_build_halted_grounding = build_halted_grounding  # noqa: F401