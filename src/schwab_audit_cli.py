"""
schwab_audit_cli.py
========================================================================================
CHARLES SCHWAB MARKET DATA CLI & 7-ENDPOINT AUDIT DIAGNOSTIC TOOL
========================================================================================

WHAT THIS SCRIPT DOES:
----------------------
This file acts as a standalone Command-Line Interface (CLI) testing and diagnostics
utility for the Charles Schwab Market Data API. It does not perform mathematical modeling
or generate portfolio strategy recommendations; instead, its primary job is to test
connectivity, manage interactive OAuth logins, and inspect or audit raw API responses.

WHEN AND HOW IT GETS CALLED:
----------------------------
This script is executed primarily from the terminal or shell prompt (or Colab bash cell)
to verify system health, diagnose broken API permissions, or pull ad-hoc quotes.

Common Usage Scenarios:
1. Quick Quote Lookup:
   $ python schwab_audit_cli.py AAPL
   Queries and prints real-time quote data for a specific ticker.

2. Multiple Symbol Lookup:
   $ python schwab_audit_cli.py AAPL,MSFT,NVDA
   Extracts combined quotes across a list of target tickers.

3. Full 7-Endpoint Inspection Audit:
   $python schwab_audit_cli.py MSFT --audit-catalog --benchmark$SPX
   Fires structured requests across all 7 supported Schwab Market Data families
   to confirm endpoint availability, latency, permissions, and schema structure.

4. Administrative Re-Authentication:
   $ python schwab_audit_cli.py AAPL --force-reauth
   Wipes the existing cached token file and forces a full interactive OAuth browser
   consent login workflow.

5. Headless/Automated Execution:
   $ python schwab_audit_cli.py AAPL --non-interactive
   Attempts to authenticate using only stored refresh tokens, failing immediately
   if manual browser login is required (useful for cron jobs or automated runners).

KEY FUNCTIONS AND HIGH-LEVEL RESPONSIBILITIES:
---------------------------------------------
1. run_marketdata_flow(symbols, ...)
   - Orchestrates single- or multi-symbol quote extraction with dual-tier OAuth support.
   - Tier 1: Proactively attempts to run the request using cached/silently refreshed tokens.
   - Tier 2: If the session has expired or requires re-consent, generates a cryptographically
     secure CSRF state nonce, prints the browser authorization link, accepts the redirected
     callback URL from the user, exchanges it for fresh tokens, and executes the query.
   - Returns an immutable `RunResult` dataclass object holding the response payload or error.

2. run_full_marketdata_catalog(symbol, benchmark_index, ...)
   - Executes a comprehensive diagnostic health check against all 7 Schwab API endpoints:
       * Quotes (/quotes)
       * Price History (/pricehistory)
       * Option Chains (/chains)
       * Option Expirations (/expirationchain)
       * Instruments (/instruments)
       * Movers (/movers/{index_symbol})
       * Market Hours (/markets)
   - Renders a clean ASCII tabular summary directly to the terminal showing HTTP status
     codes, record counts, and key baseline parameters for each endpoint family.

3. _build_arg_parser()
   - Configures and returns standard CLI arguments (e.g., target symbols, --audit-catalog,
     --benchmark, --force-reauth, --non-interactive, --token-path, and --log-level).

4. main(argv=None)
   - Standard POSIX-compliant CLI entrypoint that configures logging, evaluates parsed
     flags, routes execution to either `run_marketdata_flow` or `run_full_marketdata_catalog`,
     and returns standard shell exit codes (0 = Success, 1 = API Error, 2/3 = Setup/Fatal Error).

IMPORTANT ARCHITECTURAL & SECURITY PRACTICES:
---------------------------------------------
- Zero Hard-Coded Credentials: App keys and secrets are resolved ephemerally via secure
  vaults (Google Colab secrets, OS environment variables, or masked terminal inputs)
  and are never saved back to global tables or disk.
- Safe Path Isolation: Respects POSIX 0o700 restricted permission folders when storing
  the persistent OAuth token file (`schwab_token.json`).
- Standalone Decoupling: Separating this CLI runner from `schwab_raw_marketdata.py` prevents
  command-line argument parsing and terminal display routines from polluting downstream
  production modeling pipelines or notebook imports.
========================================================================================
"""

from __future__ import annotations

import argparse
import json
import logging
import secrets
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from schwab_auth import (
    CredentialResolutionError,
    OrchestratorError,
    build_schwab_client,
    resolve_credential,
    resolve_secure_token_path,
)
from schwab_client import APIRequestError, SchwabClient, TokenError
from schwab_raw_marketdata import RunResult, sanitize_and_validate_symbols

logger = logging.getLogger("schwab_orchestrator")


def run_marketdata_flow(
    symbols: Union[str, List[str]],
    *,
    fields: Optional[str] = None,
    interactive: bool = True,
    force_reauth: bool = False,
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
    token_file_path: Optional[Union[str, Path]] = None,
    client_kwargs: Optional[Dict[str, Any]] = None,
) -> RunResult:
    """Executes the standard market data retrieval lifecycle with full dual-tier OAuth support."""
    validated_symbols = sanitize_and_validate_symbols(symbols)
    resolved_token_path = (
        Path(token_file_path).resolve() if token_file_path else resolve_secure_token_path()
    )

    if force_reauth and resolved_token_path.exists():
        logger.info("force_reauth=True: Evicting cached token file at %s", resolved_token_path)
        try:
            resolved_token_path.unlink()
        except OSError as exc:
            logger.warning("Failed to evict cached token file: %s", exc)

    client_id = resolve_credential(
        "SCHWAB_CLIENT_ID",
        "Enter Schwab Client ID (App Key)",
        is_secret=False,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    client_secret = resolve_credential(
        "SCHWAB_CLIENT_SECRET",
        "Enter Schwab Client Secret",
        is_secret=True,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

    kwargs = client_kwargs.copy() if client_kwargs else {}

    with SchwabClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        token_file_path=resolved_token_path,
        **kwargs,
    ) as client:
        if not force_reauth:
            try:
                quote_payload = client.get_quotes(validated_symbols, fields=fields)
                logger.info("Successfully fetched quotes for [%s] via active session.", validated_symbols)
                return RunResult(
                    success=True,
                    symbol=validated_symbols,
                    data=quote_payload,
                    session_resumed=True,
                    forced_restart=False,
                )
            except TokenError as te:
                logger.info("Cached token invalid or refresh expired: %s. Initiating OAuth restart.", te)
            except APIRequestError as ae:
                if getattr(ae, "status_code", None) == 401:
                    logger.warning("Gateway returned HTTP 401 Unauthorized. Forcing OAuth restart.")
                else:
                    logger.error("API gateway failure for [%s]: %s", validated_symbols, ae)
                    return RunResult(
                        success=False,
                        symbol=validated_symbols,
                        error_message=f"API Request Failure: {ae}",
                        session_resumed=False,
                        forced_restart=False,
                    )

        if not interactive:
            err_msg = (
                "Execution halted: Session expired or OAuth restart required, "
                "but interactive authentication is disabled."
            )
            logger.error(err_msg)
            return RunResult(
                success=False,
                symbol=validated_symbols,
                error_message=err_msg,
                session_resumed=False,
                forced_restart=force_reauth,
            )

        try:
            session_state = secrets.token_urlsafe(16)
            auth_url = client.build_auth_url(state=session_state)

            print("\n" + "=" * 78)
            print("SCHWAB FULL OAUTH RESTART (LMS CONSENT & ACCOUNT SELECTION)")
            print("=" * 78)
            print("1. Open this URL in your browser to authorize application access:\n")
            print(auth_url)
            print("\n2. Log in, select/verify your accounts, and paste the redirected URL below.")
            print("-" * 78)

            auth_code = input("\nPaste Redirect URL or Code: ").strip()
            if not auth_code:
                raise OrchestratorError("No authorization code provided. Workflow aborted.")

            print("\nExchanging code for token pair with CSRF state verification...")
            client.exchange_code_for_token(auth_code, expected_state=session_state)

            quote_payload = client.get_quotes(validated_symbols, fields=fields)
            return RunResult(
                success=True,
                symbol=validated_symbols,
                data=quote_payload,
                session_resumed=False,
                forced_restart=force_reauth,
            )
        except (TokenError, APIRequestError, OrchestratorError) as exc:
            logger.error("OAuth handshake failed: %s", exc)
            return RunResult(
                success=False,
                symbol=validated_symbols,
                error_message=str(exc),
                session_resumed=False,
                forced_restart=force_reauth,
            )
        except Exception as exc:
            logger.exception("Catastrophic error during OAuth handshake: %s", exc)
            raise OrchestratorError(f"Handshake pipeline failure: {exc}") from exc


def run_full_marketdata_catalog(
    symbol: str,
    benchmark_index: str,
    *,
    strike_count: Optional[int] = None,
    period_type: str = "day",
    period: int = 5,
    frequency_type: str = "minute",
    frequency: int = 30,
    interactive: bool = True,
    force_reauth: bool = False,
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
    token_file_path: Optional[Union[str, Path]] = None,
    client_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Audits and queries all 7 Schwab Market Data endpoint families for a given asset."""
    clean_symbol = sanitize_and_validate_symbols(symbol)
    resolved_token_path = (
        Path(token_file_path).resolve() if token_file_path else resolve_secure_token_path()
    )

    if force_reauth and resolved_token_path.exists():
        logger.info("force_reauth=True: Evicting cached token file at %s", resolved_token_path)
        try:
            resolved_token_path.unlink()
        except OSError as exc:
            logger.warning("Failed to evict cached token file: %s", exc)

    client_id = resolve_credential(
        "SCHWAB_CLIENT_ID",
        "Enter Schwab Client ID",
        is_secret=False,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    client_secret = resolve_credential(
        "SCHWAB_CLIENT_SECRET",
        "Enter Schwab Client Secret",
        is_secret=True,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

    kwargs = client_kwargs.copy() if client_kwargs else {}

    with SchwabClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        token_file_path=resolved_token_path,
        **kwargs,
    ) as client:
        try:
            client.get_valid_access_token()
        except TokenError:
            if not interactive:
                raise OrchestratorError("Authentication missing and interactive mode is disabled.")
            session_state = secrets.token_urlsafe(16)
            auth_url = client.build_auth_url(state=session_state)
            print("\nAuthorization required. Complete consent flow:\n", auth_url)
            auth_code = input("\nPaste Redirect URL or Code: ").strip()
            client.exchange_code_for_token(auth_code, expected_state=session_state)

        print("\n" + "=" * 82)
        print(f"SCHWAB MARKET DATA 7-ENDPOINT AUDIT SNAPSHOT: {clean_symbol}")
        print("=" * 82)

        audit_plan = [
            ("Quotes", lambda: client.get_quotes(clean_symbol)),
            (
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
                "OptionChains",
                lambda: client.get_option_chain(clean_symbol, strike_count=strike_count),
            ),
            (
                "OptionExpirations",
                lambda: client.get_option_expirations(clean_symbol),
            ),
            (
                "Instruments",
                lambda: client.get_instruments(clean_symbol, projection="fundamental"),
            ),
            (
                "Movers",
                lambda: client.get_movers(index_symbol=benchmark_index),
            ),
            (
                "MarketHours",
                lambda: client.get_market_hours("equity,option"),
            ),
        ]

        snapshot: Dict[str, Any] = {"symbol": clean_symbol, "endpoints": {}}

        print(f"{'Endpoint':<20} | {'Status':<10} | {'Summary Data Points'}")
        print("-" * 82)

        for endpoint_name, query_func in audit_plan:
            try:
                payload = query_func()
                summary_text = ""

                if endpoint_name == "Quotes":
                    q = payload.get(clean_symbol, {}).get("quote", {})
                    summary_text = f"Last: ${q.get('lastPrice', 'N/A')} | Vol: {q.get('totalVolume', 0):,}"
                elif endpoint_name == "PriceHistory":
                    candles = payload.get("candles", [])
                    summary_text = f"{len(candles)} candle bars returned ({period_type}={period})"
                elif endpoint_name == "OptionChains":
                    call_map = payload.get("callExpDateMap", {})
                    summary_text = f"Underlying: ${payload.get('underlyingPrice', 'N/A')} | Expiries: {len(call_map)}"
                elif endpoint_name == "OptionExpirations":
                    exps = payload.get("expirationList", [])
                    summary_text = f"{len(exps)} active expiration cycles discovered"
                elif endpoint_name == "Instruments":
                    insts = payload.get("instruments", [])
                    cusip = insts[0].get("cusip", "N/A") if insts else "N/A"
                    summary_text = f"CUSIP: {cusip} | Records: {len(insts)}"
                elif endpoint_name == "Movers":
                    screeners = payload.get("screeners", [])
                    summary_text = f"{len(screeners)} index mover securities ({benchmark_index})"
                elif endpoint_name == "MarketHours":
                    summary_text = f"Trading markets: {', '.join(payload.keys())}"

                snapshot["endpoints"][endpoint_name] = {"available": True, "data": payload}
                print(f"{endpoint_name:<20} | 200 OK     | {summary_text}")

            except APIRequestError as err:
                status_code = getattr(err, "status_code", "ERR")
                snapshot["endpoints"][endpoint_name] = {"available": False, "error": str(err)}
                print(f"{endpoint_name:<20} | HTTP {status_code:<4} | Request rejected: {err}")
            except Exception as err:
                snapshot["endpoints"][endpoint_name] = {"available": False, "error": str(err)}
                print(f"{endpoint_name:<20} | FAILED     | {err}")

        print("-" * 82 + "\n")
        return snapshot


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Institutional Charles Schwab Market Data Orchestration Engine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "symbols",
        help="Ticker symbol or comma-separated symbols (e.g., AAPL or SPY,QQQ,NVDA)",
    )
    parser.add_argument(
        "--audit-catalog",
        action="store_true",
        help="Execute full 7-endpoint inspection audit instead of single quote query",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default=None,
        choices=["$SPX", "$COMPX", "$DJI"],
        help="Benchmark index symbol for movers analysis (required if --audit-catalog is set)",
    )
    parser.add_argument(
        "--force-reauth",
        action="store_true",
        help="Evict cached token and execute full interactive OAuth restart",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Disable interactive login prompts (fails fast if session is expired)",
    )
    parser.add_argument(
        "--token-path",
        type=str,
        default=None,
        help="Explicit file path for reading and persisting tokens",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Application logging verbosity level",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        if args.audit_catalog:
            if not args.benchmark:
                print(
                    "[ERROR] Argument --benchmark ($SPX, $COMPX, $DJI) is required when --audit-catalog is enabled.",
                    file=sys.stderr,
                )
                return 2

            run_full_marketdata_catalog(
                symbol=args.symbols,
                benchmark_index=args.benchmark,
                interactive=not args.non_interactive,
                force_reauth=args.force_reauth,
                token_file_path=args.token_path,
            )
            return 0

        res = run_marketdata_flow(
            symbols=args.symbols,
            interactive=not args.non_interactive,
            force_reauth=args.force_reauth,
            token_file_path=args.token_path,
        )

        if res.success:
            session_state = "Resumed Active Session" if res.session_resumed else "Newly Authenticated"
            print(f"\n[OK] Market data retrieved ({session_state}) for: {res.symbol}")
            if logger.isEnabledFor(logging.DEBUG) and res.data:
                print(json.dumps(res.data, indent=2))
            return 0
        else:
            print(f"\n[ERROR] Pipeline failure: {res.error_message}", file=sys.stderr)
            return 1

    except CredentialResolutionError as exc:
        print(f"\n[CREDENTIAL CONFIGURATION ERROR] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\n[FATAL ORCHESTRATOR FAILURE] {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())