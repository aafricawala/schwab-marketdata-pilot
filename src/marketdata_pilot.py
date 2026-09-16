"""
marketdata_pilot.py
-----------------------------------------------------------------------------
Main execution orchestrator for the Schwab Market Data Pilot.

Workflow:
1. Ensures module import paths are configured.
2. Gathers required OAuth credentials without hardcoding values.
3. Instantiates SchwabClient with a persistent token file.
4. Attempts silent API execution via cached/refreshed tokens.
5. If no active session exists (or refresh token expired after 7 days),
   gracefully initiates the manual authorization prompt.
6. Retrieves and displays quote data for the chosen symbol.
-----------------------------------------------------------------------------
"""

import os
import sys

# ---------------------------------------------------------------------------
# RUNTIME PATH SETUP
# ---------------------------------------------------------------------------
PROJECT_SRC = "/content/schwab-marketdata-pilot/src"
if PROJECT_SRC not in sys.path:
    sys.path.append(PROJECT_SRC)

try:
    from schwab_client import SchwabClient
except ImportError as err:
    raise ImportError(
        f"Unable to load SchwabClient from '{PROJECT_SRC}'. "
        f"Verify file placement. Detail: {err}"
    )


# ---------------------------------------------------------------------------
# CREDENTIAL RETRIEVAL HELPER
# ---------------------------------------------------------------------------
def _resolve_credential(env_key: str, prompt_label: str) -> str:
    """
    Returns the environment variable if present; otherwise prompts via standard input.
    """
    val = os.environ.get(env_key, "").strip()
    if not val:
        val = input(f"{prompt_label}: ").strip()
        os.environ[env_key] = val
    return val


# ---------------------------------------------------------------------------
# MAIN FLOW ORCHESTRATOR
# ---------------------------------------------------------------------------
def run_marketdata_flow(symbol: str = "AAPL") -> None:
    """
    Executes the market data query flow with automated session resumption.

    Parameters:
        symbol (str): The equity or index ticker to fetch (default: 'AAPL').
    """
    print("\n" + "=" * 60)
    print("SCHWAB MARKET DATA PILOT WORKFLOW")
    print("=" * 60)

    # 1. Resolve credentials dynamically without hardcoding
    client_id = _resolve_credential("SCHWAB_CLIENT_ID", "Enter Schwab Client ID")
    client_secret = _resolve_credential("SCHWAB_CLIENT_SECRET", "Enter Schwab Client Secret")
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

    # Persistent cache path (points to mounted Drive or local working directory)
    token_file = os.environ.get("SCHWAB_TOKEN_PATH", "/content/schwab_tokens.json")

    # 2. Initialize the client
    client = SchwabClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        token_file_path=token_file,
    )

    # 3. Attempt silent execution using existing cached or refreshed tokens
    print(f"\nChecking for active cached session in: {token_file}")
    try:
        quote_data = client.get_quote(symbol)
        print(f"[Success] Session resumed. Quote received for {symbol}:")
        print(quote_data)
        print("\n" + "=" * 60)
        return
    except Exception as exc:
        print(f"[Info] Active session unavailable ({exc}). Proceeding to manual authorization.")

    # 4. Fallback: Manual OAuth handshake (required once every 7 days)
    print("\n" + "-" * 60)
    print("MANUAL AUTHORIZATION REQUIRED (Every 7 Days)")
    print("-" * 60)
    auth_url = client.build_auth_url()
    print("1. Open the following URL in your browser:\n")
    print(auth_url)
    print("\n2. Log in, grant permissions, and copy the full redirected URL (or code=...)")

    pasted_code = input("\nPaste code or full redirect URL: ").strip()

    # 5. Exchange code for fresh access and refresh tokens
    print("\nExchanging code for token pair...")
    client.exchange_code_for_token(pasted_code)
    print("Tokens successfully acquired and cached to disk.")

    # 6. Retrieve quote with new access token
    print(f"\nRequesting market data for: {symbol}")
    quote_data = client.get_quote(symbol)
    print("Quote response:")
    print(quote_data)

    print("\n" + "=" * 60)
    print("Workflow completed successfully.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    # Default execution symbol if run directly via python or %run
    target_symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    run_marketdata_flow(target_symbol)