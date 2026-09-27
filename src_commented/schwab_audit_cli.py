"""
Filename: schwab_audit_cli.py
Purpose: Provides a command-line interface (CLI) to fetch and orchestrate market data from the Charles Schwab API.
Prerequisites: Requires valid Charles Schwab API credentials (client ID and secret) and an active internet connection.
What this module does:
1. Executes a standard market data retrieval flow.
2. Performs a full catalog audit across seven different endpoints.
3. Manages OAuth authorization, including interactive login and token caching.
4. Parses command-line arguments to trigger various execution modes.
Configuration knobs:
- SCHWAB_CLIENT_ID: The environment variable for the application key.
- SCHWAB_CLIENT_SECRET: The environment variable for the application secret.
- SCHWAB_REDIRECT_URI: The OAuth callback URL.
Outputs: Prints market data details or audit summaries to the console, and returns integer exit codes.
Notes: It can be run non-interactively if a valid token is already cached; otherwise, it requires a browser and manual input.
"""
# Import the annotations feature from future to allow modern type hinting syntax
from __future__ import annotations

# Import the argparse module to handle parsing of command-line arguments
import argparse
# Import the json module to format output data structures as JSON strings
import json
# Import the logging module to record diagnostic information, warnings, and errors
import logging
# Import the secrets module to generate secure random tokens for state verification
import secrets
# Import the sys module to access system-specific parameters and application exit functions
import sys
# Import the Path class from pathlib to work with file system paths easily
from pathlib import Path
# Import various typing constructs for defining function signatures and data structures
from typing import Any, Callable, Dict, List, Optional, Union
# Import the os module to read environment variables
import os

# Import custom authentication errors and credential resolution functions from the auth module
from schwab_auth import (
    CredentialResolutionError,
    OrchestratorError,
    build_schwab_client,
    resolve_credential,
    resolve_secure_token_path,
)
# Import client classes and network-level exceptions from the schwab client module
from schwab_client import APIRequestError, SchwabClient, TokenError
# Import result data structures and symbol validation utilities from the raw market data module
from schwab_raw_marketdata import RunResult, sanitize_and_validate_symbols

# Initialize a logger specific to the orchestrator to record its activities during runtime
logger = logging.getLogger("schwab_orchestrator")


# Define a function to execute the primary market data flow for a given set of symbols
def run_marketdata_flow(
    # Accept a single symbol string or a list of ticker symbols
    symbols: Union[str, List[str]],
    # Force all subsequent arguments to be specified as keyword arguments
    *,
    # Accept an optional comma-separated string specifying specific fields to fetch
    fields: Optional[str] = None,
    # Accept a boolean to enable or disable interactive prompts (defaults to True)
    interactive: bool = True,
    # Accept a boolean to force re-authentication by ignoring cached tokens (defaults to False)
    force_reauth: bool = False,
    # Accept an optional callable to securely provide secrets dynamically without prompts
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
    # Accept an optional explicit file path for reading or writing the OAuth token file
    token_file_path: Optional[Union[str, Path]] = None,
    # Accept an optional dictionary of extra keyword arguments to pass to the Schwab client
    client_kwargs: Optional[Dict[str, Any]] = None,
# Return a structured RunResult object containing the outcome and data of the flow
) -> RunResult:
    """Executes the standard market data retrieval lifecycle with full dual-tier OAuth support."""
    # Clean up the provided input symbols and validate them to ensure API compatibility
    validated_symbols = sanitize_and_validate_symbols(symbols)
    # Determine the final token file path, resolving a provided path or using the default secure path
    resolved_token_path = (
        Path(token_file_path).resolve() if token_file_path else resolve_secure_token_path()
    )

    # Check if a forced re-authentication is requested and if a token file already exists
    if force_reauth and resolved_token_path.exists():
        # Log an informational message that the cached token file is being evicted
        logger.info("force_reauth=True: Evicting cached token file at %s", resolved_token_path)
        # Start a try block to handle potential file system errors during deletion
        try:
            # Delete the existing token file from the disk
            resolved_token_path.unlink()
        # Catch any OS-level exceptions that occur if the file cannot be deleted
        except OSError as exc:
            # Log a warning message indicating the file eviction failed
            logger.warning("Failed to evict cached token file: %s", exc)

    # Resolve the Schwab Client ID, prompting the user interactively if it's not found in the environment
    client_id = resolve_credential(
        "SCHWAB_CLIENT_ID",
        "Enter Schwab Client ID (App Key)",
        is_secret=False,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    # Resolve the Schwab Client Secret securely, prompting the user if it's missing
    client_secret = resolve_credential(
        "SCHWAB_CLIENT_SECRET",
        "Enter Schwab Client Secret",
        is_secret=True,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    # Read the OAuth redirect URI from environment variables, or fall back to a local loopback address
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

    # Create a copy of the extra client arguments if provided, otherwise initialize an empty dictionary
    kwargs = client_kwargs.copy() if client_kwargs else {}

    # Initialize the SchwabClient as a context manager to ensure network sessions are closed safely
    with SchwabClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        token_file_path=resolved_token_path,
        **kwargs,
    # Bind the active client instance to the variable 'client'
    ) as client:
        # Check if we are attempting to use existing credentials (i.e., not forcing a re-auth)
        if not force_reauth:
            # Start a try block for the primary data fetching attempt using existing/cached tokens
            try:
                # Request market data quotes for the validated symbols using the specified fields
                quote_payload = client.get_quotes(validated_symbols, fields=fields)
                # Log a success message indicating quotes were fetched seamlessly via an active session
                logger.info("Successfully fetched quotes for [%s] via active session.", validated_symbols)
                # Return a successful RunResult containing the fetched quote data
                return RunResult(
                    success=True,
                    symbol=validated_symbols,
                    data=quote_payload,
                    session_resumed=True,
                    forced_restart=False,
                )
            # Catch token-related errors, which indicate expiration or an invalid cached token
            except TokenError as te:
                # Log an informational message that the token is invalid and an OAuth restart is necessary
                logger.info("Cached token invalid or refresh expired: %s. Initiating OAuth restart.", te)
            # Catch API-level errors, indicating a failed network request to the gateway
            except APIRequestError as ae:
                # Check if the API error specifically indicates an HTTP 401 Unauthorized status
                if getattr(ae, "status_code", None) == 401:
                    # Log a warning that the gateway rejected the token, requiring an OAuth restart
                    logger.warning("Gateway returned HTTP 401 Unauthorized. Forcing OAuth restart.")
                # Handle all other types of API errors (e.g., 500 Server Error)
                else:
                    # Log a severe error message detailing the API gateway failure
                    logger.error("API gateway failure for [%s]: %s", validated_symbols, ae)
                    # Return a failed RunResult containing the specific API error message
                    return RunResult(
                        success=False,
                        symbol=validated_symbols,
                        error_message=f"API Request Failure: {ae}",
                        session_resumed=False,
                        forced_restart=False,
                    )

        # Check if interactive mode is disabled, meaning we cannot prompt the user for a new login
        if not interactive:
            # Construct a detailed error message explaining why execution cannot proceed autonomously
            err_msg = (
                "Execution halted: Session expired or OAuth restart required, "
                "but interactive authentication is disabled."
            )
            # Log the execution halt error message
            logger.error(err_msg)
            # Return a failed RunResult because the flow is blocked
            return RunResult(
                success=False,
                symbol=validated_symbols,
                error_message=err_msg,
                session_resumed=False,
                forced_restart=force_reauth,
            )

        # Start a try block to handle the full interactive OAuth re-authentication process
        try:
            # Generate a secure, random state token to protect against CSRF attacks during the OAuth flow
            session_state = secrets.token_urlsafe(16)
            # Ask the client to construct the authorization URL containing the client ID and state token
            auth_url = client.build_auth_url(state=session_state)

            # Print a blank line followed by a visual separator to the console
            print("\n" + "=" * 78)
            # Print a header indicating a full OAuth restart and user consent flow is beginning
            print("SCHWAB FULL OAUTH RESTART (LMS CONSENT & ACCOUNT SELECTION)")
            # Print another visual separator line
            print("=" * 78)
            # Print instructions telling the user to open the provided URL in their web browser
            print("1. Open this URL in your browser to authorize application access:\n")
            # Print the actual authorization URL
            print(auth_url)
            # Print instructions telling the user to complete the login and copy the resulting redirect URL
            print("\n2. Log in, select/verify your accounts, and paste the redirected URL below.")
            # Print a dashed visual separator line
            print("-" * 78)

            # Prompt the user to input the redirect URL or authorization code, stripping any surrounding whitespace
            auth_code = input("\nPaste Redirect URL or Code: ").strip()
            # Check if the user failed to provide any input at the prompt
            if not auth_code:
                # Raise an OrchestratorError because we cannot continue the flow without the authorization code
                raise OrchestratorError("No authorization code provided. Workflow aborted.")

            # Print a message indicating the code exchange and verification process is starting
            print("\nExchanging code for token pair with CSRF state verification...")
            # Instruct the client to exchange the code for access tokens, validating the expected CSRF state
            client.exchange_code_for_token(auth_code, expected_state=session_state)

            # Request the market data quotes again using the newly obtained credentials
            quote_payload = client.get_quotes(validated_symbols, fields=fields)
            # Return a successful RunResult containing the newly fetched data
            return RunResult(
                success=True,
                symbol=validated_symbols,
                data=quote_payload,
                session_resumed=False,
                forced_restart=force_reauth,
            )
        # Catch expected errors related to token issues, API failures, or orchestrator aborts
        except (TokenError, APIRequestError, OrchestratorError) as exc:
            # Log an error message detailing why the OAuth handshake failed
            logger.error("OAuth handshake failed: %s", exc)
            # Return a failed RunResult containing the exception message
            return RunResult(
                success=False,
                symbol=validated_symbols,
                error_message=str(exc),
                session_resumed=False,
                forced_restart=force_reauth,
            )
        # Catch any other unexpected, severe exceptions that might occur during the handshake
        except Exception as exc:
            # Log the full exception stack trace to diagnose the catastrophic failure
            logger.exception("Catastrophic error during OAuth handshake: %s", exc)
            # Raise a new OrchestratorError encapsulating the original exception to halt the program
            raise OrchestratorError(f"Handshake pipeline failure: {exc}") from exc


# Define a function to perform an audit query across all seven Schwab market data endpoints
def run_full_marketdata_catalog(
    # Accept a single ticker symbol string to query across the endpoints
    symbol: str,
    # Accept a benchmark index string required for market movers analysis
    benchmark_index: str,
    # Force all subsequent arguments to be specified as keyword arguments
    *,
    # Accept an optional integer defining the number of strikes to request for option chains
    strike_count: Optional[int] = None,
    # Accept a string specifying the period type (e.g., "day", "month"), defaulting to "day"
    period_type: str = "day",
    # Accept an integer specifying the period duration, defaulting to 5
    period: int = 5,
    # Accept a string specifying the frequency type of the data points, defaulting to "minute"
    frequency_type: str = "minute",
    # Accept an integer specifying the frequency interval, defaulting to 30
    frequency: int = 30,
    # Accept a boolean to enable or disable interactive prompts during authentication
    interactive: bool = True,
    # Accept a boolean to force a complete re-authentication by evicting cached tokens
    force_reauth: bool = False,
    # Accept an optional callable to securely supply secrets without user prompts
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
    # Accept an optional explicit file path for token persistence
    token_file_path: Optional[Union[str, Path]] = None,
    # Accept an optional dictionary of extra arguments for the Schwab client constructor
    client_kwargs: Optional[Dict[str, Any]] = None,
# Return a comprehensive dictionary containing the complete audit snapshot from all endpoints
) -> Dict[str, Any]:
    """Audits and queries all 7 Schwab Market Data endpoint families for a given asset."""
    # Clean and validate the input symbol to ensure it meets API formatting requirements
    clean_symbol = sanitize_and_validate_symbols(symbol)
    # Resolve the final token path, preferring a user-provided path or falling back to the default
    resolved_token_path = (
        Path(token_file_path).resolve() if token_file_path else resolve_secure_token_path()
    )

    # Check if forced re-authentication is required and if the token file currently exists on disk
    if force_reauth and resolved_token_path.exists():
        # Log an informational message indicating the cached token file is being deleted
        logger.info("force_reauth=True: Evicting cached token file at %s", resolved_token_path)
        # Start a try block to handle potential OS errors during file deletion
        try:
            # Delete the token file from the file system
            resolved_token_path.unlink()
        # Catch any OS-level errors that might occur (e.g., permission denied)
        except OSError as exc:
            # Log a warning if the token file could not be successfully deleted
            logger.warning("Failed to evict cached token file: %s", exc)

    # Resolve the Schwab Client ID securely, prompting the user if it is not configured
    client_id = resolve_credential(
        "SCHWAB_CLIENT_ID",
        "Enter Schwab Client ID",
        is_secret=False,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    # Resolve the Schwab Client Secret securely, prompting the user if it is not configured
    client_secret = resolve_credential(
        "SCHWAB_CLIENT_SECRET",
        "Enter Schwab Client Secret",
        is_secret=True,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    # Read the OAuth redirect URI from the environment, defaulting to localhost
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

    # Create a copy of the extra client arguments, or initialize an empty dictionary if none provided
    kwargs = client_kwargs.copy() if client_kwargs else {}

    # Initialize the SchwabClient as a context manager to ensure proper cleanup of network resources
    with SchwabClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        token_file_path=resolved_token_path,
        **kwargs,
    # Bind the active client instance to the variable 'client'
    ) as client:
        # Start a try block to attempt retrieving a valid access token (using cache/refresh if possible)
        try:
            # Attempt to retrieve a valid token, which may trigger an automatic token refresh under the hood
            client.get_valid_access_token()
        # Catch a TokenError if no valid token could be obtained (e.g., refresh token expired)
        except TokenError:
            # Check if interactive mode is disabled, preventing a user prompt
            if not interactive:
                # Raise an error because authentication is required but interactive prompts are turned off
                raise OrchestratorError("Authentication missing and interactive mode is disabled.")
            # Generate a secure, random state token to protect the interactive OAuth flow
            session_state = secrets.token_urlsafe(16)
            # Ask the client to build the authorization URL embedding the state token
            auth_url = client.build_auth_url(state=session_state)
            # Print a message to the console containing the authorization URL
            print("\nAuthorization required. Complete consent flow:\n", auth_url)
            # Prompt the user to input the redirect URL or authorization code, stripping whitespace
            auth_code = input("\nPaste Redirect URL or Code: ").strip()
            # Instruct the client to exchange the code for access tokens, verifying the CSRF state
            client.exchange_code_for_token(auth_code, expected_state=session_state)

        # Print a blank line followed by a thick separator line to the console
        print("\n" + "=" * 82)
        # Print a header indicating the start of the 7-endpoint audit for the specified symbol
        print(f"SCHWAB MARKET DATA 7-ENDPOINT AUDIT SNAPSHOT: {clean_symbol}")
        # Print another thick separator line
        print("=" * 82)

        # Define a list of tuples outlining the audit plan: each tuple contains an endpoint name and a lambda function to execute the query
        audit_plan = [
            # Tuple for querying the 'Quotes' endpoint for the clean symbol
            ("Quotes", lambda: client.get_quotes(clean_symbol)),
            (
                # Tuple for querying the 'PriceHistory' endpoint with the specified time parameters
                "PriceHistory",
                lambda: client.get_price_history(
                    clean_symbol,
                    period_type=period_type,
                    period=period,
                    frequency_type=frequency_type,
                    frequency=frequency,
                ),
            ),
            (
                # Tuple for querying the 'OptionChains' endpoint, passing the requested strike count limit
                "OptionChains",
                lambda: client.get_option_chain(clean_symbol, strike_count=strike_count),
            ),
            (
                # Tuple for querying the 'OptionExpirations' endpoint for the symbol
                "OptionExpirations",
                lambda: client.get_option_expirations(clean_symbol),
            ),
            (
                # Tuple for querying the 'Instruments' endpoint, requesting fundamental projection data
                "Instruments",
                lambda: client.get_instruments(clean_symbol, projection="fundamental"),
            ),
            (
                # Tuple for querying the 'Movers' endpoint, utilizing the specified benchmark index
                "Movers",
                lambda: client.get_movers(index_symbol=benchmark_index),
            ),
            (
                # Tuple for querying the 'MarketHours' endpoint for both equity and option markets
                "MarketHours",
                lambda: client.get_market_hours("equity,option"),
            ),
        ]

        # Initialize a dictionary to store the final, aggregated audit snapshot results
        snapshot: Dict[str, Any] = {"symbol": clean_symbol, "endpoints": {}}

        # Print table headers for the formatted terminal output display
        print(f"{'Endpoint':<20} | {'Status':<10} | {'Summary Data Points'}")
        # Print a thin separator line below the table headers
        print("-" * 82)

        # Iterate sequentially over each endpoint name and its associated lambda query function in the plan
        for endpoint_name, query_func in audit_plan:
            # Start a try block to handle potential network or API errors during individual endpoint queries
            try:
                # Execute the specific query function to retrieve the data payload from the API
                payload = query_func()
                # Initialize an empty string variable to hold a brief summary of the payload data
                summary_text = ""

                # Check if the current endpoint being processed is the 'Quotes' endpoint
                if endpoint_name == "Quotes":
                    # Extract the nested quote data dictionary for the specific symbol
                    q = payload.get(clean_symbol, {}).get("quote", {})
                    # Format a summary string showing the last traded price and total volume
                    summary_text = f"Last: ${q.get('lastPrice', 'N/A')} | Vol: {q.get('totalVolume', 0):,}"
                # Check if the current endpoint being processed is the 'PriceHistory' endpoint
                elif endpoint_name == "PriceHistory":
                    # Extract the list of historical candle bars from the payload
                    candles = payload.get("candles", [])
                    # Format a summary string showing the total number of candles returned and the period parameters
                    summary_text = f"{len(candles)} candle bars returned ({period_type}={period})"
                # Check if the current endpoint being processed is the 'OptionChains' endpoint
                elif endpoint_name == "OptionChains":
                    # Extract the mapping of call options by expiration date from the payload
                    call_map = payload.get("callExpDateMap", {})
                    # Format a summary string showing the underlying asset price and the number of expiration dates returned
                    summary_text = f"Underlying: ${payload.get('underlyingPrice', 'N/A')} | Expiries: {len(call_map)}"
                # Check if the current endpoint being processed is the 'OptionExpirations' endpoint
                elif endpoint_name == "OptionExpirations":
                    # Extract the list of available expiration dates from the payload
                    exps = payload.get("expirationList", [])
                    # Format a summary string showing the total count of active expiration cycles discovered
                    summary_text = f"{len(exps)} active expiration cycles discovered"
                # Check if the current endpoint being processed is the 'Instruments' endpoint
                elif endpoint_name == "Instruments":
                    # Extract the list of instrument objects from the payload
                    insts = payload.get("instruments", [])
                    # Retrieve the CUSIP identifier from the first instrument if available, otherwise default to 'N/A'
                    cusip = insts[0].get("cusip", "N/A") if insts else "N/A"
                    # Format a summary string showing the CUSIP and the total number of instrument records returned
                    summary_text = f"CUSIP: {cusip} | Records: {len(insts)}"
                # Check if the current endpoint being processed is the 'Movers' endpoint
                elif endpoint_name == "Movers":
                    # Extract the list of screener results (movers) from the payload
                    screeners = payload.get("screeners", [])
                    # Format a summary string showing the number of movers returned for the specified benchmark index
                    summary_text = f"{len(screeners)} index mover securities ({benchmark_index})"
                # Check if the current endpoint being processed is the 'MarketHours' endpoint
                elif endpoint_name == "MarketHours":
                    # Format a summary string listing the names of the trading markets returned in the payload keys
                    summary_text = f"Trading markets: {', '.join(payload.keys())}"

                # Store the successful data payload and a boolean availability flag in the final snapshot dictionary
                snapshot["endpoints"][endpoint_name] = {"available": True, "data": payload}
                # Print the endpoint result row to the console, indicating HTTP 200 success and displaying the summary
                print(f"{endpoint_name:<20} | 200 OK     | {summary_text}")

            # Catch APIRequestError exceptions, which indicate the API rejected the request for this specific endpoint
            except APIRequestError as err:
                # Retrieve the HTTP status code from the error object, or default to a generic "ERR" string
                status_code = getattr(err, "status_code", "ERR")
                # Store the failure flag and the stringified error message in the snapshot dictionary
                snapshot["endpoints"][endpoint_name] = {"available": False, "error": str(err)}
                # Print the endpoint result row to the console, indicating the HTTP error code and the rejection reason
                print(f"{endpoint_name:<20} | HTTP {status_code:<4} | Request rejected: {err}")
            # Catch any other unexpected exceptions that might occur during query execution or processing
            except Exception as err:
                # Store the failure flag and the stringified exception message in the snapshot dictionary
                snapshot["endpoints"][endpoint_name] = {"available": False, "error": str(err)}
                # Print the endpoint result row to the console, indicating a generic failure state
                print(f"{endpoint_name:<20} | FAILED     | {err}")

        # Print a final thin separator line followed by a newline to conclude the table output
        print("-" * 82 + "\n")
        # Return the fully populated audit snapshot dictionary back to the caller
        return snapshot


# Define a function to build and configure the command-line argument parser for the CLI
def _build_arg_parser() -> argparse.ArgumentParser:
    # Instantiate the argument parser, providing a description and enabling default value display in the help text
    parser = argparse.ArgumentParser(
        description="Institutional Charles Schwab Market Data Orchestration Engine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    # Add a required positional argument for the target symbols
    parser.add_argument(
        "symbols",
        help="Ticker symbol or comma-separated symbols (e.g., AAPL or SPY,QQQ,NVDA)",
    )
    # Add an optional flag to trigger the full 7-endpoint catalog audit instead of a simple quote query
    parser.add_argument(
        "--audit-catalog",
        action="store_true",
        help="Execute full 7-endpoint inspection audit instead of single quote query",
    )
    # Add an optional argument to specify a benchmark index, which is required if the audit catalog is enabled
    parser.add_argument(
        "--benchmark",
        type=str,
        default=None,
        choices=["$SPX", "$COMPX", "$DJI"],
        help="Benchmark index symbol for movers analysis (required if --audit-catalog is set)",
    )
    # Add an optional flag to force re-authentication by evicting cached tokens
    parser.add_argument(
        "--force-reauth",
        action="store_true",
        help="Evict cached token and execute full interactive OAuth restart",
    )
    # Add an optional flag to disable interactive prompts, failing fast if authentication is needed
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Disable interactive login prompts (fails fast if session is expired)",
    )
    # Add an optional argument to specify an explicit custom file path for token persistence
    parser.add_argument(
        "--token-path",
        type=str,
        default=None,
        help="Explicit file path for reading and persisting tokens",
    )
    # Add an optional argument to set the application logging verbosity level
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Application logging verbosity level",
    )
    # Return the fully configured argument parser object
    return parser


# Define the main entry point function for the script, accepting an optional list of argument strings
def main(argv: Optional[List[str]] = None) -> int:
    # Build the configured argument parser by calling the helper function
    parser = _build_arg_parser()
    # Parse the provided command-line arguments (uses sys.argv automatically if argv is None)
    args = parser.parse_args(argv)

    # Configure the global logging module with the specified log level and formatting style
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Start a high-level try block to catch and handle any orchestrator failures or configuration errors
    try:
        # Check if the user requested the full audit catalog via command-line arguments
        if args.audit_catalog:
            # Verify that a benchmark index was provided, as it is required for the audit catalog
            if not args.benchmark:
                # Print an error message directly to the standard error stream indicating the missing argument
                print(
                    "[ERROR] Argument --benchmark ($SPX, $COMPX, $DJI) is required when --audit-catalog is enabled.",
                    file=sys.stderr,
                )
                # Return an exit code of 2 to indicate incorrect command-line usage
                return 2

            # Execute the full market data catalog audit using the parsed command-line arguments
            run_full_marketdata_catalog(
                symbol=args.symbols,
                benchmark_index=args.benchmark,
                interactive=not args.non_interactive,
                force_reauth=args.force_reauth,
                token_file_path=args.token_path,
            )
            # Return an exit code of 0 indicating successful completion of the audit
            return 0

        # Execute the standard market data flow (simple quotes) using the parsed command-line arguments
        res = run_marketdata_flow(
            symbols=args.symbols,
            interactive=not args.non_interactive,
            force_reauth=args.force_reauth,
            token_file_path=args.token_path,
        )

        # Check if the standard market data flow returned a successful result
        if res.success:
            # Determine a descriptive session state string based on whether an existing session was resumed
            session_state = "Resumed Active Session" if res.session_resumed else "Newly Authenticated"
            # Print a success message to the standard output console
            print(f"\n[OK] Market data retrieved ({session_state}) for: {res.symbol}")
            # Check if DEBUG logging is enabled and if data payload is present in the result
            if logger.isEnabledFor(logging.DEBUG) and res.data:
                # Print the formatted JSON data payload to the console for inspection
                print(json.dumps(res.data, indent=2))
            # Return an exit code of 0 indicating successful data retrieval
            return 0
        # If the standard market data flow was not successful
        else:
            # Print an error message detailing the pipeline failure to the standard error stream
            print(f"\n[ERROR] Pipeline failure: {res.error_message}", file=sys.stderr)
            # Return an exit code of 1 indicating an operational failure occurred
            return 1

    # Catch errors specifically related to missing, invalid, or improperly configured credentials
    except CredentialResolutionError as exc:
        # Print the credential error message to the standard error stream
        print(f"\n[CREDENTIAL CONFIGURATION ERROR] {exc}", file=sys.stderr)
        # Return an exit code of 2 indicating configuration or authentication issues
        return 2
    # Catch any other unhandled fatal exceptions that bubble up to the main function
    except Exception as exc:
        # Print a generic fatal error message to the standard error stream
        print(f"\n[FATAL ORCHESTRATOR FAILURE] {exc}", file=sys.stderr)
        # Return an exit code of 3 indicating a severe or unexpected crash
        return 3


# Check if this Python script is being run directly as the primary executable module
if __name__ == "__main__":
    # Call the main entry point function and immediately exit the interpreter with its returned status code
    sys.exit(main())
