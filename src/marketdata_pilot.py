"""
marketdata_pilot.py
-----------------------------------------------------------------------------
Institutional-Grade Orchestrator for Schwab Market Data Pipeline.

Security & Architectural Guarantees:
- Zero Secret Pollution: Never modifies global process environment (os.environ).
- Masked Secret Input: Uses getpass to prevent shoulder surfing and DOM leakage.
- Precise Error Disambiguation: Differentiates between authentication failures
  (which trigger re-auth) and business/network errors (which fail fast).
- Cross-Platform Path Isolation: Dynamically anchors token stores to Google Drive
  (in Colab) or secure OS user home directories with POSIX 0o700 isolation.
- Deterministic Resource Cleanup: Enforces context-managed HTTP session teardown.
-----------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

# ---------------------------------------------------------------------------
# PATH RESOLUTION & SAFE IMPORT GUARD
# ---------------------------------------------------------------------------
PROJECT_SRC = Path(__file__).resolve().parent if "__file__" in locals() else Path("/content/schwab-marketdata-pilot/src")
if str(PROJECT_SRC) not in sys.path:
    sys.path.append(str(PROJECT_SRC))

try:
    from schwab_client import APIRequestError, SchwabClient, SchwabClientError, TokenError
except ImportError as exc:
    raise ImportError(f"FATAL: Unable to load hardened SchwabClient from '{PROJECT_SRC}': {exc}") from exc

# Application logger configuration
logger = logging.getLogger("marketdata_orchestrator")
logger.addHandler(logging.NullHandler())

# Strict ticker symbol regex (handles equities, ETFs, and indices with $, ., or /)
SYMBOL_REGEX = re.compile(r"^[$A-Z0-9./\-_]{1,14}$")


# ---------------------------------------------------------------------------
# DATA STRUCTURES & CUSTOM EXCEPTIONS
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RunResult:
    """Immutable structured result returned by the orchestrator."""
    success: bool
    symbol: str
    data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    session_resumed: bool = False


class OrchestratorError(SchwabClientError):
    """Base exception for pipeline orchestration failures."""


class CredentialResolutionError(OrchestratorError):
    """Raised when required credentials cannot be resolved securely."""


# ---------------------------------------------------------------------------
# HARDENED CREDENTIAL RESOLUTION
# ---------------------------------------------------------------------------
def _get_colab_secret(key: str) -> Optional[str]:
    """Retrieves secrets from Google Colab userdata vault without printing errors."""
    try:
        from google.colab import userdata  # type: ignore
        val = userdata.get(key)
        return str(val).strip() if val else None
    except Exception:
        return None


def _resolve_credential(
    key: str,
    prompt_label: str,
    *,
    is_secret: bool = False,
    interactive: bool = True,
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> str:
    """
    Resolves credentials deterministically through an enterprise precedence hierarchy.
    Crucially, does NOT inject resolved secrets back into os.environ.
    """
    # 1. Enterprise secret manager callback
    if secret_provider:
        try:
            val = secret_provider(key)
            if val and val.strip():
                return val.strip()
        except Exception as exc:
            logger.debug("Enterprise secret provider failed for key '%s': %s", key, exc)

    # 2. Google Colab User Data Vault
    colab_val = _get_colab_secret(key)
    if colab_val:
        return colab_val

    # 3. Environment Variable (Read-only lookup)
    env_val = os.environ.get(key)
    if env_val and env_val.strip():
        return env_val.strip()

    # 4. Interactive fallback with terminal masking
    if interactive:
        try:
            if is_secret:
                # Suppress terminal echo to prevent credential exposure in logs/DOM
                user_val = getpass.getpass(prompt=f"{prompt_label}: ").strip()
            else:
                user_val = input(f"{prompt_label}: ").strip()

            if user_val:
                return user_val
        except (EOFError, KeyboardInterrupt) as exc:
            raise CredentialResolutionError(f"Interactive credential input aborted for '{key}'.") from exc

    raise CredentialResolutionError(
        f"Required credential '{key}' could not be resolved. "
        "Provide via Colab Secrets, environment variable, or secret provider."
    )


# ---------------------------------------------------------------------------
# SECURE STORAGE PATH RESOLUTION
# ---------------------------------------------------------------------------
def resolve_secure_token_path() -> Path:
    """
    Determines an isolated, permission-controlled path for token caching.
    Enforces directory permission mask (0o700) on POSIX platforms.
    """
    explicit_path = os.environ.get("SCHWAB_TOKEN_PATH")
    if explicit_path and explicit_path.strip():
        target = Path(explicit_path).expanduser().resolve()
    else:
        # Check if Google Drive is mounted
        drive_dir = Path("/content/drive/MyDrive/Colab Notebooks/schwab_market_data")
        if drive_dir.exists() and drive_dir.is_dir():
            target = drive_dir / "schwab_token.json"
        else:
            # Multi-platform local fallback: ~/.schwab/tokens.json
            target = Path.home() / ".schwab" / "schwab_tokens.json"

    # Enforce owner-only directory permissions (rwx------)
    parent_dir = target.parent
    parent_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(parent_dir, 0o700)
    except OSError:
        pass

    return target


def _sanitize_and_validate_symbols(raw_symbol: Union[str, List[str]]) -> str:
    """Validates ticker format to block injection and format anomalies."""
    if isinstance(raw_symbol, list):
        candidates = [s.strip().upper() for s in raw_symbol if s and isinstance(s, str)]
    elif isinstance(raw_symbol, str):
        candidates = [s.strip().upper() for s in raw_symbol.split(",") if s.strip()]
    else:
        raise ValueError("Symbol parameter must be a non-empty string or list of strings.")

    if not candidates:
        raise ValueError("No valid symbols supplied after sanitization.")

    for sym in candidates:
        if not SYMBOL_REGEX.match(sym):
            raise ValueError(f"Security validation failed: Symbol '{sym}' contains invalid characters.")

    return ",".join(candidates)


# ---------------------------------------------------------------------------
# PIPELINE ORCHESTRATOR
# ---------------------------------------------------------------------------
def run_marketdata_flow(
    symbol: Union[str, List[str]] = "AAPL",
    *,
    interactive: bool = True,
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
    token_file_path: Optional[Union[str, Path]] = None,
    client_kwargs: Optional[Dict[str, Any]] = None,
) -> RunResult:
    """
    Executes the market data retrieval lifecycle.

    Guarantees:
    - Only token/auth exceptions fall back to browser authorization.
    - Upstream network errors or invalid symbol queries fail fast.
    - All network sessions are terminated deterministically.
    """
    validated_symbols = _sanitize_and_validate_symbols(symbol)
    resolved_token_path = Path(token_file_path).resolve() if token_file_path else resolve_secure_token_path()

    # Resolve credentials
    client_id = _resolve_credential(
        "SCHWAB_CLIENT_ID",
        "Enter Schwab Client ID (App Key)",
        is_secret=False,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    client_secret = _resolve_credential(
        "SCHWAB_CLIENT_SECRET",
        "Enter Schwab Client Secret",
        is_secret=True,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

    kwargs = client_kwargs.copy() if client_kwargs else {}

    # Initialize client within context manager for deterministic socket teardown
    with SchwabClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        token_file_path=resolved_token_path,
        **kwargs,
    ) as client:

        # Step 1: Attempt execution via existing cached or refreshed session
        try:
            quote_payload = client.get_quotes(validated_symbols)
            logger.info("Successfully fetched quotes for [%s] via cached credentials.", validated_symbols)
            return RunResult(
                success=True,
                symbol=validated_symbols,
                data=quote_payload,
                session_resumed=True,
            )
        except TokenError as te:
            logger.info("Cached token unavailable or expired: %s. Handshake required.", te)
        except APIRequestError as ae:
            # If rejected with 401 specifically, allow re-auth; all other errors must fail fast
            if getattr(ae, "status_code", None) == 401:
                logger.warning("Gateway returned HTTP 401 Unauthorized. Triggering interactive handshake.")
            else:
                logger.error("Upstream API failure for symbols [%s]: %s", validated_symbols, ae)
                return RunResult(
                    success=False,
                    symbol=validated_symbols,
                    error_message=f"API request failure: {ae}",
                )

        # Step 2: Fallback to manual authorization flow if interactive
        if not interactive:
            err_msg = "Execution halted: Active session expired and interactive authorization is disabled."
            logger.error(err_msg)
            return RunResult(success=False, symbol=validated_symbols, error_message=err_msg)

        try:
            auth_url = client.build_auth_url()
            print("\n" + "=" * 70)
            print("SCHWAB OAUTH HANDSHAKE REQUIRED")
            print("=" * 70)
            print("1. Open this URL in your browser to authorize access:\n")
            print(auth_url)
            print("\n2. Log in and paste the redirected URL (or code parameter) below:")

            auth_code = input("\nPaste Redirect URL or Code: ").strip()
            if not auth_code:
                raise OrchestratorError("No authorization code provided; workflow aborted.")

            print("\nExchanging code for token payload...")
            client.exchange_code_for_token(auth_code)

            # Step 3: Execute query with freshly minted access token
            quote_payload = client.get_quotes(validated_symbols)
            return RunResult(
                success=True,
                symbol=validated_symbols,
                data=quote_payload,
                session_resumed=False,
            )

        except (TokenError, APIRequestError, OrchestratorError) as exc:
            logger.error("Authentication handshake failed: %s", exc)
            return RunResult(success=False, symbol=validated_symbols, error_message=str(exc))
        except Exception as exc:
            logger.exception("Unexpected catastrophic error in authorization pipeline: %s", exc)
            raise OrchestratorError(f"Handshake pipeline crashed: {exc}") from exc


# ---------------------------------------------------------------------------
# CLI INTERFACE
# ---------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Institutional Charles Schwab Market Data Execution Engine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("symbol", nargs="?", default="SPY", help="Ticker symbol(s), comma-separated (e.g. AAPL,MSFT,NVDA)")
    parser.add_argument("--non-interactive", action="store_true", help="Disallow manual browser login prompts")
    parser.add_argument("--token-path", type=str, default=None, help="Explicit token storage file path")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Logging level")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint conforming to standard POSIX exit status codes."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )

    try:
        res = run_marketdata_flow(
            symbol=args.symbol,
            interactive=not args.non_interactive,
            token_file_path=args.token_path,
        )

        if res.success:
            session_type = "Cached" if res.session_resumed else "Newly Authenticated"
            print(f"\n[OK] Market data retrieved ({session_type}) for symbols: {res.symbol}")
            if logger.isEnabledFor(logging.DEBUG) and res.data:
                import json as _json
                print(_json.dumps(res.data, indent=2))
            return 0
        else:
            print(f"\n[ERROR] Pipeline failed: {res.error_message}", file=sys.stderr)
            return 1

    except CredentialResolutionError as exc:
        print(f"\n[CREDENTIAL ERROR] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\n[FATAL SYSTEM ERROR] {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())