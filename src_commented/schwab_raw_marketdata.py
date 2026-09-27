"""
schwab_raw_marketdata.py
---
Purpose
    This module serves as a central hub or "facade" for the project's market data functions. It does not contain its own logic, but instead gathers functions that were split into other files and provides them all in one place. This ensures that older code looking for these functions here will still work perfectly without needing to be updated.

Prerequisites
    None directly required for this file, though the modules it imports from may have their own requirements.

What this module does
    1. Enables advanced feature support by setting up modern Python behaviors.
    2. Gathers and exposes functions for handling responses from the vendor (resilience).
    3. Gathers and exposes functions for checking if the stock market is open.
    4. Gathers and exposes functions for dealing with paused or halted stocks.
    5. Gathers and exposes functions for retrieving past stock prices.
    6. Gathers and exposes functions for understanding the core details of a stock.
    7. Gathers and exposes functions for analyzing options contracts.
    8. Creates older, hidden versions of some function names just in case they are still being used by legacy systems.

Configuration knobs
    None.

Outputs
    This module makes several imported functions available to be used by other parts of the program.

Notes
    This file is meant purely for backward compatibility (keeping old code working) and easier organization.
"""
# Tell Python to allow newer style hints (annotations) for variable types, even in older Python versions
from __future__ import annotations

# ---------------------------------------------------------
# Public API re-exports
# (These lines grab functions from other files so they can be accessed here)
# ---------------------------------------------------------

# From the vendor resilience file, import functions that handle vendor responses and retrying failed calls
from schwab_vendor_resilience import (  # noqa: F401 (This comment tells the code checker to ignore that the function is imported but seemingly unused here)
    # Import the function that reads and understands what the vendor sent back
    parse_client_response,
    # Import the function that automatically tries again if a vendor call fails
    retry_vendor_call,
)

# From the market session file, import the function that figures out if the market is currently open
from schwab_market_session import extract_market_open_status  # noqa: F401 (Ignore unused import warning)

# From the grounding schema file, import the function that handles data when a stock's trading is paused
from schwab_grounding_schema import build_halted_grounding  # noqa: F401 (Ignore unused import warning)

# From the price history file, import the function that grabs past price data that is saved in memory
from schwab_price_history import extract_in_memory_price_history  # noqa: F401 (Ignore unused import warning)

# From the underlying grounding file, import the function that carefully grabs the fundamental data of a stock
from schwab_underlying_grounding import extract_strict_underlying_data  # noqa: F401 (Ignore unused import warning)

# From the option chain file, import functions that deal with lists of available option contracts
from schwab_option_chain import (  # noqa: F401 (Ignore unused import warning)
    # Import the function that extracts option chains saved in memory
    extract_in_memory_option_chains,
    # Import the function that extracts just the dates when options expire
    extract_in_memory_option_expirations,
    # Import the function that figures out the best expiration dates to look at
    resolve_optimal_expirations,
)

# ---------------------------------------------------------
# Backward-compatible private aliases (underscore names preserved for legacy callers)
# (These lines create alternative, older names for some functions just in case old code looks for them)
# ---------------------------------------------------------

# Create a private copy (starts with underscore) of the parse_client_response function so old code won't break
_parse_client_response = parse_client_response  # noqa: F401 (Ignore unused import warning)

# Create a private copy (starts with underscore) of the build_halted_grounding function so old code won't break
_build_halted_grounding = build_halted_grounding  # noqa: F401 (Ignore unused import warning)
