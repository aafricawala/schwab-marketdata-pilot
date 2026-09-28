"""
schwab_vertical_spread_screener.py

Purpose:
This module is a screener and analytics engine for vertical debit option spreads (Bull Call
and Bear Put Spreads) using data from the Charles Schwab API. It evaluates combinations of
long and short option strikes for a given stock and expiration date, calculating key risk
metrics, pricing, and capital efficiency.

Prerequisites:
- A configured `schwab_auth` module to handle API authentication.
- The `schwab_client` and `schwab_raw_marketdata` modules for API interaction and symbol validation.
- Valid API credentials (client ID, secret, and valid OAuth token).

What this module does:
1. Validates the target stock symbol and requested strike prices.
2. Connects to the Schwab API to fetch real-time option chains for the target symbol.
3. Extracts the current underlying stock price, handling various API fallback structures if the primary price is missing.
4. Parses the option chain to extract pricing (bid, ask, mark) and Greeks (Delta, Theta, Vega, Gamma) for the requested strikes.
5. Synthesizes vertical spreads by pairing valid long and short strikes.
6. Calculates net pricing, breakeven points, maximum profit, and cost-to-width ratios.
7. Ranks the generated spreads by capital efficiency (cost-to-width ratio).

Configuration knobs:
- `strategy_type`: Whether to screen "CALL" or "PUT" spreads.
- `cost_to_width_pass_pct`: The threshold percentage to flag a spread as passing efficiency tests (default: 40.0).
- CLI arguments for symbol, expiration, long strikes, and short strikes.

Outputs:
- A structured dictionary containing underlying details, parsed option legs, and a ranked list of spread evaluations.
- When run as a CLI tool, prints the results as formatted JSON and optionally saves them to a specified file.

Notes:
- The module rejects illogical spreads, such as those indicating negative costs (arbitrage) or guaranteed losses.
- It robustly handles missing "mark" prices by falling back to the synthetic midpoint of bid and ask.
"""

# Enable modern Python type hints.
from __future__ import annotations

# Import the argparse library to handle command-line arguments.
import argparse
# Import the inspect library to examine function signatures dynamically.
import inspect
# Import the json library to parse and create JSON strings.
import json
# Import the logging library to output warnings and information.
import logging
# Import the Path object for robust file path handling across operating systems.
from pathlib import Path
# Import sys to manipulate the Python path.
import sys
# Import typing helpers to describe data structures and function signatures.
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

# ------------------------------------------------------------------------------
# 1. Workspace Path Alignment & Module Imports
# ------------------------------------------------------------------------------
# Determine the root source directory for imports.
PROJECT_SRC = (
    # Use the current file's directory if running directly.
    Path(__file__).resolve().parent
    # Check if the script is being run as a file rather than interactively.
    if "__file__" in locals()
    # Otherwise, use a hardcoded default path (useful for Colab notebooks).
    else Path("/content/schwab-marketdata-pilot/src")
# Close the path resolution logic.
)
# If our source directory is not already in Python's search path...
if str(PROJECT_SRC) not in sys.path:
    # ...insert it at the very beginning so our custom modules are found first.
    sys.path.insert(0, str(PROJECT_SRC))

# Create a dedicated logger for the vertical spread engine.
logger = logging.getLogger("VerticalSpreadEngine")
# Add a null handler to prevent errors if logging isn't configured by the caller.
logger.addHandler(logging.NullHandler())

# Start a try block to import internal auth modules safely.
try:
    # Import necessary tools from the authentication module.
    from schwab_auth import (
        # Import specific error types for better handling.
        CredentialResolutionError,
        # Import general orchestrator error type.
        OrchestratorError,
        # Import the factory function that creates API clients.
        build_schwab_client,
        # Import the utility that finds the OAuth token.
        resolve_secure_token_path,
    )
    # Import a utility function to ensure stock symbols are clean.
    from schwab_raw_marketdata import sanitize_and_validate_symbols
# Catch the error if any of these critical internal modules are missing.
except ImportError as err:
    # Raise a clear, fatal error telling the user exactly what went wrong.
    raise ImportError(
        # Print the path we tried to load from.
        f"FATAL: Unable to load modules from '{PROJECT_SRC}'. "
        # Suggest the most likely fix.
        f"Ensure schwab_auth.py and schwab_raw_marketdata.py are present. Detail: {err}"
    # Chain the original error for debugging.
    ) from err

# Start a try block to import internal auth modules safely.
try:
    # Try to import the main Schwab API client.
    from schwab_client import SchwabClient
# Catch the error if any of these critical internal modules are missing.
except ImportError as err:
    # Raise a clear, fatal error telling the user exactly what went wrong.
    raise ImportError(
        # Warn the user if the client module is missing.
        f"FATAL: Unable to load 'schwab_client.py' from '{PROJECT_SRC}'. "
        # Provide fixing advice.
        f"Ensure the module is in your Python path. Detail: {err}"
    # Chain the original error for debugging.
    ) from err


# ------------------------------------------------------------------------------
# 2. Market Data & Spread Analytics Engine
# ------------------------------------------------------------------------------
# Define the main function to evaluate vertical spreads based on user parameters.
def evaluate_vertical_spreads(
    # The target stock symbol.
    symbol: str,
    # The target expiration date.
    expiration: str,
    # The list of long strikes to evaluate.
    long_strikes: Sequence[float],
    # The list of short strikes to evaluate.
    short_strikes: Sequence[float],
    # Force all subsequent arguments to be keyword-only.
    *,
    # The strategy type (CALL or PUT).
    strategy_type: str = "CALL",
    # The maximum cost-to-width ratio to consider a 'pass'.
    cost_to_width_pass_pct: float = 40.0,
    # An optional pre-authenticated API client.
    client: Optional[SchwabClient] = None,
    # An optional specific API client ID.
    client_id: Optional[str] = None,
    # An optional API secret.
    client_secret: Optional[str] = None,
    # An optional OAuth redirect URI.
    redirect_uri: Optional[str] = None,
    # An optional custom path to the auth token.
    token_path: Optional[Union[Path, str]] = None,
    # Whether to allow interactive login prompts.
    interactive: bool = True,
    # Whether to force a fresh login.
    force_reauth: bool = False,
    # An optional secure secret provider.
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
# Declare that this returns a dictionary of evaluations.
) -> Dict[str, Any]:
    """
    Evaluates vertical debit spreads over target strike sets and expiration dates.
    Integrates defensive quote extraction, Greek netting, and institutional efficiency gates.
    """
    # Clean up and validate the provided stock symbol.
    target_symbol = sanitize_and_validate_symbols(symbol)

    # Remove extra spaces from the strategy type and convert it to uppercase.
    strat_type = strategy_type.strip().upper()
    # Ensure the strategy type is supported.
    if strat_type not in {"CALL", "PUT"}:
        # Raise an error if the strategy type is invalid.
        raise ValueError(f"Invalid strategy_type: '{strategy_type}'. Must be 'CALL' or 'PUT'.")

    # Remove extra spaces from the provided expiration date string.
    target_expiration = expiration.strip()
    # Convert long strikes to positive floats, remove duplicates, and sort them.
    sorted_longs = sorted(list(set(float(k) for k in long_strikes if float(k) > 0)))
    # Convert short strikes to positive floats, remove duplicates, and sort them.
    sorted_shorts = sorted(list(set(float(k) for k in short_strikes if float(k) > 0)))

    # Check if either list of strikes ended up empty.
    if not sorted_longs or not sorted_shorts:
        # Raise an error if we lack valid strikes.
        raise ValueError("Long strikes and short strikes must contain valid, positive numbers.")

    # Combine all unique strikes into one sorted list we need data for.
    required_strikes = sorted(list(set(sorted_longs + sorted_shorts)))

    # Acquire or initialize API client via standard schwab_auth factory
    # Use the provided API client, or build a new one using the auth factory.
    managed_client = client or build_schwab_client(
        # Pass the token path to the auth factory.
        token_file_path=token_path,
        # Pass the interactive flag.
        interactive=interactive,
        # Pass the secret provider.
        secret_provider=secret_provider,
    )

    # Use a context manager to safely handle the API client session.
    with managed_client as cli:
        # Dynamic query introspection
        # Inspect the 'get_option_chain' method to see what arguments it expects (handling API version differences).
        chain_sig = inspect.signature(cli.get_option_chain)
        # Get the dictionary of parameters accepted by the method.
        params = chain_sig.parameters
        # Initialize an empty dictionary to hold the arguments we will pass to the API call.
        query_kwargs: Dict[str, Any] = {}

        # Check if the method expects a snake_case parameter for contract type.
        if "contract_type" in params:
            # Add the strategy type to our arguments using snake_case.
            query_kwargs["contract_type"] = strat_type
        # Check if it expects a camelCase parameter or variable kwargs.
        elif "contractType" in params or any(
            # Look for **kwargs definition in the signature.
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        ):
            # Add the strategy type to our arguments using camelCase.
            query_kwargs["contractType"] = strat_type

        # Check if the method expects a snake_case parameter for the start date.
        if "from_date" in params:
            # Set the start date using snake_case.
            query_kwargs["from_date"] = target_expiration
            # Set the end date using snake_case to narrow the search to exactly one day.
            query_kwargs["to_date"] = target_expiration
        # Check for camelCase date parameters.
        elif "fromDate" in params or any(
            # Look for **kwargs definition in the signature.
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        ):
            # Set the start date using camelCase.
            query_kwargs["fromDate"] = target_expiration
            # Set the end date using camelCase.
            query_kwargs["toDate"] = target_expiration

        # Check if the method accepts a 'strategy' parameter.
        if "strategy" in params or any(
            # Look for **kwargs definition in the signature.
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        ):
            # Tell the API we want single leg option data.
            query_kwargs["strategy"] = "SINGLE"

        # Check if the method accepts a snake_case flag to include stock data.
        if "include_underlying_quote" in params:
            # Set the underlying quote flag.
            query_kwargs["include_underlying_quote"] = True
        # Check for the camelCase underlying quote flag.
        elif "includeUnderlyingQuote" in params or any(
            # Look for **kwargs definition in the signature.
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        ):
            # Set the underlying quote flag using camelCase.
            query_kwargs["includeUnderlyingQuote"] = True

        # Start a try block to import internal auth modules safely.
        try:
            # Call the API, passing the symbol and unpacking our customized arguments.
            chain_payload = cli.get_option_chain(symbol=target_symbol, **query_kwargs)
        # If the customized API call fails...
        except Exception as req_err:
            # ...log a warning that the specific query failed.
            logger.warning("Parameterized get_option_chain failed (%s). Retrying unconstrained...", req_err)
            # ...and retry the API call using only the stock symbol (requesting the entire massive chain).
            chain_payload = cli.get_option_chain(target_symbol)

        # Multi-tier Spot Price Fallback
        # Initialize the underlying stock price variable.
        spot_px: Optional[float] = None
        # Try to extract the 'underlying' data block from the API response.
        underlying_dict = chain_payload.get("underlying") or {}

        # Verify that we got a valid dictionary for the underlying data.
        if underlying_dict and isinstance(underlying_dict, dict):
            # Try to determine the current stock price...
            spot_px = (
                # ...by looking at the mark price first...
                underlying_dict.get("mark")
                # ...then the last traded price...
                or underlying_dict.get("last")
                # ...and finally the bid price.
                or underlying_dict.get("bid")
            )

        # If we still haven't found a price...
        if spot_px is None:
            # ...check the root payload for 'underlyingPrice'.
            spot_px = chain_payload.get("underlyingPrice")

        # If we still lack a valid price...
        if spot_px is None or float(spot_px) <= 0:
            # ...log that we are using the generic quote endpoint as a fallback.
            logger.info("Resolving underlying spot quote via get_quotes fallback endpoint...")
            # Start a try block to import internal auth modules safely.
            try:
                # Make a separate API call just to get the current stock quote.
                quote_resp = cli.get_quotes(target_symbol)
                # Extract the specific quote data for our target symbol.
                sym_quote = quote_resp.get(target_symbol, {}).get("quote", {})
                # Try to determine the current stock price...
                spot_px = (
                    # Look for the mark price...
                    sym_quote.get("mark")
                    # ...then the last price...
                    or sym_quote.get("lastPrice")
                    # ...then the bid price.
                    or sym_quote.get("bidPrice")
                )
                # Rebuild the underlying dictionary with the fresh quote data.
                underlying_dict = {
                    # Store the primary spot price.
                    "spot": float(spot_px or 0.0),
                    # Store the bid.
                    "bid": float(sym_quote.get("bidPrice", 0.0)),
                    # Store the ask.
                    "ask": float(sym_quote.get("askPrice", 0.0)),
                    # Store the mark.
                    "mark": float(sym_quote.get("mark", spot_px or 0.0)),
                    # Store the volume.
                    "volume": int(sym_quote.get("totalVolume", 0)),
                }
            # Catch errors from the fallback quote call.
            except Exception as quote_err:
                # Log a warning if the fallback failed.
                logger.warning("Fallback get_quotes query failed: %s", quote_err)

        # If all attempts to find a valid stock price failed...
        if not spot_px or float(spot_px) <= 0:
            # ...raise a critical error, as we cannot evaluate spreads without a stock price.
            raise OrchestratorError(
                # Explain which ticker failed.
                f"Spot price resolution failed for ticker '{target_symbol}'. "
                # Explain why this is fatal.
                "Unable to compute relative moneyness or breakeven hurdles."
            )

        # Convert the final valid spot price to a float.
        spot_float = float(spot_px)

        # Strike Surface & Greeks Parsing
        # Determine whether to look in the calls or puts map.
        exp_map_key = "callExpDateMap" if strat_type == "CALL" else "putExpDateMap"
        # Extract the expiration map from the payload.
        exp_map = chain_payload.get(exp_map_key, {})
        # Find the exact dictionary key that contains our target expiration date.
        target_exp_key = next((k for k in exp_map.keys() if target_expiration in k), None)

        # If the requested expiration date was not found...
        if not target_exp_key:
            # ...grab a sample of available dates to show the user.
            available_expirations = list(exp_map.keys())[:10]
            raise ValueError(
                # Detail what was missing.
                f"Expiration '{target_expiration}' not found in {exp_map_key}. "
                # Print the available alternatives.
                f"Available expiration cycles: {available_expirations}"
            )

        # Start a try block to import internal auth modules safely.
        try:
            # Try to extract the 'Days To Expiration' integer from the expiration key string.
            dte_val = int(target_exp_key.split(":")[1])
        # If extraction fails...
        except Exception:
            # ...default to 0 days to expiration.
            dte_val = 0

        # Initialize a dictionary to store parsed contract data indexed by strike price.
        contracts_db: Dict[float, Dict[str, Any]] = {}
        # Extract the raw strike data for our chosen expiration.
        raw_strikes = exp_map[target_exp_key]

        # Loop through every strike price listed.
        for strk_str, contract_arr in raw_strikes.items():
            # Start a try block to import internal auth modules safely.
            try:
                # Convert the strike price string to a float.
                k_val = float(strk_str)
                # Process this strike only if it's one we requested and has data.
                if k_val in required_strikes and contract_arr:
                    # Grab the first contract object (usually the only one) for this strike.
                    c_obj = contract_arr[0]
                    # Extract the bid price.
                    c_bid = float(c_obj.get("bid") or 0.0)
                    # Extract the ask price.
                    c_ask = float(c_obj.get("ask") or 0.0)
                    # Extract the mark price.
                    c_mark = c_obj.get("mark")

                    # Robust mark price fallback
                    # If the API provided a valid positive mark price...
                    if c_mark is not None and float(c_mark) > 0:
                        # ...use it.
                        mark_clean = float(c_mark)
                    # Otherwise, if we have valid bid/ask prices...
                    elif (c_bid + c_ask) > 0:
                        # ...calculate the synthetic midpoint as the mark.
                        mark_clean = (c_bid + c_ask) / 2.0
                    else:
                        # ...fall back to the last traded price as a last resort.
                        mark_clean = float(c_obj.get("last") or 0.0)

                    # Save the parsed contract metrics into our database dictionary.
                    contracts_db[k_val] = {
                        # Store the strike.
                        "strike": k_val,
                        # Store the rounded bid.
                        "bid": round(c_bid, 2),
                        # Store the rounded ask.
                        "ask": round(c_ask, 2),
                        # Store the rounded mark.
                        "mark": round(mark_clean, 2),
                        # Store the delta Greek.
                        "delta": round(float(c_obj.get("delta") or 0.0), 4),
                        # Store the theta Greek.
                        "theta": round(float(c_obj.get("theta") or 0.0), 4),
                        # Store the vega Greek.
                        "vega": round(float(c_obj.get("vega") or 0.0), 4),
                        # Store the gamma Greek.
                        "gamma": round(float(c_obj.get("gamma") or 0.0), 4),
                        # Store the implied volatility.
                        "iv": round(float(c_obj.get("volatility") or 0.0), 2),
                        # Store the open interest.
                        "open_interest": int(c_obj.get("openInterest") or 0),
                        # Store the trading volume.
                        "volume": int(c_obj.get("totalVolume") or 0),
                    }
            # Catch data parsing errors for specific strikes.
            except (ValueError, TypeError) as parse_err:
                # Log a debug message and skip the broken strike.
                logger.debug("Skipping unparseable strike %s: %s", strk_str, parse_err)
                # Continue to the next strike.
                continue

        # Spread Synthesis & Risk Modeling
        # Initialize an empty list to store the final evaluated spreads.
        spread_evaluations: List[Dict[str, Any]] = []

        # Iterate through every requested long strike.
        for k_long in sorted_longs:
            # For each long strike, iterate through every requested short strike.
            for k_short in sorted_shorts:
                # Structural validity:
                # Bull Call Spread: Long strike < Short strike
                # Bear Put Spread: Long strike > Short strike
                # Bull Call Spreads require the short strike to be higher than the long strike.
                if strat_type == "CALL" and k_short <= k_long:
                    continue
                # Bear Put Spreads require the long strike to be higher than the short strike.
                if strat_type == "PUT" and k_long <= k_short:
                    continue

                # Verify we have data for both legs of the potential spread.
                if k_long not in contracts_db or k_short not in contracts_db:
                    continue

                # Retrieve the data for the long leg.
                leg_l = contracts_db[k_long]
                # Retrieve the data for the short leg.
                leg_s = contracts_db[k_short]
                # Calculate the width of the spread.
                spread_width = round(abs(k_short - k_long), 2)
                # Calculate the theoretical cost to enter the spread using midpoint mark prices.
                net_debit_mark = round(leg_l["mark"] - leg_s["mark"], 2)
                # Calculate the natural execution cost (buying at the ask, selling at the bid).
                net_debit_nat = round(leg_l["ask"] - leg_s["bid"], 2)

                # Edge Case: Reject non-debit spreads, arbitrage quotes, or negative expectancy
                # Reject spreads that generate a credit (or zero cost) or have zero width.
                if net_debit_mark <= 0 or spread_width <= 0:
                    continue
                # Reject spreads where the cost exceeds the maximum possible payout (guaranteed loss).
                if net_debit_mark >= spread_width:
                    continue  # Debit >= width guarantees capital loss at maximum gain

                # Calculate the maximum potential profit per share.
                max_profit = round(spread_width - net_debit_mark, 2)
                # Calculate the theoretical maximum Return on Capital percentage.
                roc_pct = round((max_profit / net_debit_mark) * 100, 2)
                # Calculate the capital efficiency metric (how much of the spread's width is consumed by cost).
                cost_to_width = round((net_debit_mark / spread_width) * 100, 2)

                # Calculate the stock price required at expiration to break even on the trade.
                breakeven = (
                    # For call spreads, breakeven is the long strike plus the net debit.
                    round(k_long + net_debit_mark, 2)
                    # Apply call spread math.
                    if strat_type == "CALL"
                    # For put spreads, breakeven is the long strike minus the net debit.
                    else round(k_long - net_debit_mark, 2)
                )
                # Calculate the percentage distance the stock must move to reach the breakeven point.
                be_dist_pct = round(((breakeven - spot_float) / spot_float) * 100, 2)

                # Add all the calculated metrics for this spread to our list.
                spread_evaluations.append(
                    {
                        # Create a human-readable title for the trade structure.
                        "structure": (
                            # Format for call spreads.
                            f"${k_long:.0f} /${k_short:.0f} Bull Call Spread"
                            # Apply call spread math.
                            if strat_type == "CALL"
                            else f"${k_long:.0f} /${k_short:.0f} Bear Put Spread"
                        ),
                        # Record the strategy type.
                        "strategy_type": strat_type,
                        # Record the long strike.
                        "long_strike": k_long,
                        # Record the short strike.
                        "short_strike": k_short,
                        # Record the total spread width.
                        "gross_width": spread_width,
                        # Group pricing metrics together.
                        "pricing": {
                            # Midpoint cost.
                            "net_debit_mark": net_debit_mark,
                            # Natural execution cost.
                            "net_debit_natural": net_debit_nat,
                            # Efficiency ratio.
                            "cost_to_width_pct": cost_to_width,
                            # Determine if the spread passes our efficiency criteria.
                            "efficiency_status": (
                                # It passes if...
                                "PASS"
                                # ...the cost ratio is below our acceptable threshold.
                                if cost_to_width <= cost_to_width_pass_pct
                                # Otherwise it fails.
                                else "FAIL"
                            ),
                            # Max profit.
                            "max_profit_per_share": max_profit,
                            # Max return on capital.
                            "max_roc_pct": roc_pct,
                            # Price to break even.
                            "breakeven_price": breakeven,
                            # Distance to break even.
                            "breakeven_pct_from_spot": be_dist_pct,
                        },
                        # Group calculated net risk metrics together.
                        "net_greeks": {
                            # Calculate net delta exposure.
                            "net_delta": round(leg_l["delta"] - leg_s["delta"], 4),
                            # Calculate net theta (time decay) exposure.
                            "net_theta": round(leg_l["theta"] - leg_s["theta"], 4),
                            # Calculate net vega (volatility) exposure.
                            "net_vega": round(leg_l["vega"] - leg_s["vega"], 4),
                            # Calculate net gamma (delta velocity) exposure.
                            "net_gamma": round(leg_l["gamma"] - leg_s["gamma"], 4),
                        },
                        # Attach the raw data for the long leg.
                        "long_leg": leg_l,
                        # Attach the raw data for the short leg.
                        "short_leg": leg_s,
                    }
                )

        # Rank by ascending cost-to-width ratio (capital efficiency)
        # Sort the list of valid spreads from most capital-efficient to least.
        spread_evaluations.sort(key=lambda x: x["pricing"]["cost_to_width_pct"])

        # Return a master dictionary with context and all evaluated spreads.
        return {
            # The evaluated ticker.
            "as_of_ticker": target_symbol,
            # The current stock price used.
            "spot_price": spot_float,
            # Additional stock data.
            "underlying_details": underlying_dict,
            # The evaluated expiration date.
            "expiration": target_expiration,
            # The days to expiration.
            "dte": dte_val,
            # A flat list of all individual options analyzed.
            "contracts_extracted": list(contracts_db.values()),
            # The ranked list of viable vertical spreads.
            "spread_evaluations": spread_evaluations,
        }


# ------------------------------------------------------------------------------
# 3. CLI Execution Interface
# ------------------------------------------------------------------------------
# Define a function to configure command-line arguments.
def _build_arg_parser() -> argparse.ArgumentParser:
    # Create a new argument parser.
    parser = argparse.ArgumentParser(
        # Provide a description for the tool's help menu.
        description="Institutional Vertical Debit Spread Screener (Schwab API)",
        # Make the help menu display default values.
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Add an argument for the stock symbol.
    parser.add_argument("--symbol", "-s", type=str, required=True, help="Target underlying ticker (e.g. GOOGL)")
    # Add an argument for the expiration date.
    parser.add_argument("--expiration", "-e", type=str, required=True, help="Expiration date (YYYY-MM-DD)")
    # Add an argument that accepts multiple long strikes.
    parser.add_argument("--long-strikes", "-l", type=float, nargs="+", required=True, help="Candidate long strikes")
    # Add an argument that accepts multiple short strikes.
    parser.add_argument("--short-strikes", "-k", type=float, nargs="+", required=True, help="Candidate short strikes")
    # Add an optional argument to configure the efficiency pass threshold.
    parser.add_argument("--cost-to-width-max", type=float, default=40.0, help="Max cost-to-width %% for PASS tag")
    # Add an argument to pick between calls and puts.
    parser.add_argument("--strategy-type", choices=["CALL", "PUT"], default="CALL", help="Spread contract right")
    # Add a flag to force re-authentication.
    parser.add_argument("--force-reauth", action="store_true", help="Evict cached token and re-run OAuth handshake")
    # Add a flag to prevent terminal login prompts.
    parser.add_argument("--non-interactive", action="store_true", help="Fail fast if token is expired/missing")
    # Add an argument to override where the auth token is stored.
    parser.add_argument("--token-path", type=str, default=None, help="Custom token storage path override")
    # Add an argument to specify an output file for the results.
    parser.add_argument("--out", type=str, default=None, help="File path to write JSON results")
    # Return the configured parser.
    return parser


# Define the main entry point for the CLI script.
def main() -> None:
    # Configure terminal logging output.
    logging.basicConfig(
        # Set the logging level to show standard information.
        level=logging.INFO,
        # Format log messages with timestamps and severity.
        format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        # Set the time format for logs.
        datefmt="%H:%M:%S",
    )
    # Build the argument parser.
    parser = _build_arg_parser()
    # Parse the arguments provided by the user.
    args = parser.parse_args()

    # Execute the main evaluation engine with the parsed arguments.
    result = evaluate_vertical_spreads(
        # Pass the symbol.
        symbol=args.symbol,
        # Pass the expiration date.
        expiration=args.expiration,
        # Pass the candidate long strikes.
        long_strikes=args.long_strikes,
        # Pass the candidate short strikes.
        short_strikes=args.short_strikes,
        # Pass the efficiency threshold.
        cost_to_width_pass_pct=args.cost_to_width_max,
        # Pass the strategy type.
        strategy_type=args.strategy_type,
        # Pass the interactively flag (inverted).
        interactive=not args.non_interactive,
        # Pass the reauth flag.
        force_reauth=args.force_reauth,
        # Pass the custom token path.
        token_path=args.token_path,
    )

    # Convert the final result dictionary to a pretty-printed JSON string.
    json_str = json.dumps(result, indent=2)
    # If the user requested to save the output to a file...
    if args.out:
        # ...write the JSON text to the specified file path.
        Path(args.out).write_text(json_str, encoding="utf-8")
        # Log a confirmation message.
        logger.info("Output saved to %s", args.out)

    # Print the JSON result to the terminal.
    print(json_str)


# If this file is run directly from the command line (not imported)...
if __name__ == "__main__":
    # ...execute the main CLI function.
    main()