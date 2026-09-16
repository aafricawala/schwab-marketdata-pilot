"""
marketdata_pilot.py
-----------------------------------------------------------------------------
Orchestrator script for Schwab Market Data retrieval with Colab Secrets support.
-----------------------------------------------------------------------------
"""

import os
import sys

PROJECT_SRC = "/content/schwab-marketdata-pilot/src"
if PROJECT_SRC not in sys.path:
    sys.path.append(PROJECT_SRC)

try:
    from schwab_client import SchwabClient
except ImportError as err:
    raise ImportError(f"Unable to load SchwabClient from '{PROJECT_SRC}': {err}")


def _resolve_credential(env_key: str, prompt_label: str) -> str:
    """
    Attempts to read credential from:
    1. Google Colab Secrets (userdata)
    2. OS Environment Variables
    3. User input prompt
    """
    # 1. Try Google Colab Secrets
    try:
        from google.colab import userdata
        val = userdata.get(env_key)
        if val:
            return str(val).strip()
    except Exception:
        pass

    # 2. Try OS environment variables
    val = os.environ.get(env_key, "").strip()
    if val:
        return val

    # 3. Fallback to interactive prompt
    val = input(f"{prompt_label}: ").strip()
    os.environ[env_key] = val
    return val


def run_marketdata_flow(symbol: str = "AAPL") -> None:
    print("\n" + "=" * 60)
    print("SCHWAB MARKET DATA PILOT WORKFLOW")
    print("=" * 60)

    client_id = _resolve_credential("SCHWAB_CLIENT_ID", "Enter Schwab Client ID")
    client_secret = _resolve_credential("SCHWAB_CLIENT_SECRET", "Enter Schwab Client Secret")
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

    # Save to Drive if mounted, otherwise local runtime
    token_file = os.environ.get(
        "SCHWAB_TOKEN_PATH",
        "/content/drive/MyDrive/Colab Notebooks/schwab_market_data/schwab_token.json"
    )

    client = SchwabClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        token_file_path=token_file,
    )

    print(f"\nChecking for active cached session in: {token_file}")
    try:
        quote_data = client.get_quote(symbol)
        print(f"[Success] Session active. Quote received for {symbol}:")
        print(quote_data)
        print("\n" + "=" * 60)
        return
    except Exception as exc:
        print(f"[Info] Session invalid or expired ({exc}). Starting authorization...")

    print("\n" + "-" * 60)
    print("MANUAL AUTHORIZATION REQUIRED")
    print("-" * 60)
    print("1. Open this URL in your browser:\n")
    print(client.build_auth_url())
    print("\n2. Log in and paste the redirected URL (or code=...) below:")

    pasted_code = input("\nPaste code or redirect URL: ").strip()

    print("\nExchanging code for tokens...")
    client.exchange_code_for_token(pasted_code)
    print("Tokens acquired and saved to persistent storage.")

    print(f"\nFetching market data for: {symbol}")
    quote_data = client.get_quote(symbol)
    print("Quote response:")
    print(quote_data)

    print("\n" + "=" * 60)
    print("Workflow complete.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    target_symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    run_marketdata_flow(target_symbol)