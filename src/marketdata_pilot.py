"""
marketdata_pilot.py
------------------------------------------------------------
This module contains the full workflow previously inside
schwab-marketdata-pilot_main.ipynb, rewritten as a clean,
importable Python script that can be executed from your
schwab-devops.ipynb notebook using:

    %run /content/schwab-marketdata-pilot/src/marketdata_pilot.py

or:

    from marketdata_pilot import run_marketdata_flow
    run_marketdata_flow()

All code executes inside the SAME Colab runtime.
------------------------------------------------------------
"""

import os
import sys
from typing import Optional

# ------------------------------------------------------------
# PROJECT PATH SETUP
# ------------------------------------------------------------
# Ensure Python can find your SchwabClient module.
# This assumes your repo structure:
# /content/schwab-marketdata-pilot/src/schwab_client.py

PROJECT_SRC = "/content/schwab-marketdata-pilot/src"
if PROJECT_SRC not in sys.path:
    sys.path.append(PROJECT_SRC)

try:
    from schwab_client import SchwabClient
except Exception as e:
    raise ImportError(f"Failed to import SchwabClient: {e}")


# ------------------------------------------------------------
# HELPER: READ ENV VAR OR PROMPT USER
# ------------------------------------------------------------
def get_env_or_prompt(key: str, prompt_text: str) -> str:
    """
    Returns environment variable if set, otherwise prompts user.
    """
    value = os.environ.get(key)
    if value is None or value.strip() == "":
        value = input(prompt_text)
        os.environ[key] = value
    return value


# ------------------------------------------------------------
# MAIN WORKFLOW
# ------------------------------------------------------------
def run_marketdata_flow(symbol: str = "AAPL") -> None:
    """
    Executes the full Schwab Market Data OAuth + Quote retrieval flow.
    This function is the main entry point for your script.
    """

    print("\n------------------------------------------------------------")
    print("STEP 1: Load Schwab OAuth Credentials")
    print("------------------------------------------------------------")

    client_id = get_env_or_prompt("SCHWAB_CLIENT_ID", "Enter Schwab Client ID: ")
    client_secret = get_env_or_prompt("SCHWAB_CLIENT_SECRET", "Enter Schwab Client Secret: ")

    # Redirect URI must match your Schwab Developer App configuration
    redirect_uri = "https://127.0.0.1"
    os.environ["SCHWAB_REDIRECT_URI"] = redirect_uri

    print("Credentials loaded.")


    print("\n------------------------------------------------------------")
    print("STEP 2: Initialize SchwabClient")
    print("------------------------------------------------------------")

    client = SchwabClient(
        client_id=client_id,
        redirect_uri=redirect_uri
    )

    print("SchwabClient initialized.")


    print("\n------------------------------------------------------------")
    print("STEP 3: Build Authorization URL")
    print("------------------------------------------------------------")

    auth_url = client.build_auth_url()
    print("Open this URL in your browser to authorize the application:")
    print(auth_url)

    print("\nAfter logging in, copy the 'code=' value from the redirect URL.")
    auth_code = input("Paste authorization code: ").strip()


    print("\n------------------------------------------------------------")
    print("STEP 4: Exchange Authorization Code for Access Token")
    print("------------------------------------------------------------")

    token_data = client.exchange_code_for_token(
        code=auth_code,
        client_secret=client_secret
    )

    print("Token response received:")
    print(token_data)


    print("\n------------------------------------------------------------")
    print(f"STEP 5: Retrieve Market Data for {symbol}")
    print("------------------------------------------------------------")

    quote = client.get_quote(symbol)
    print("Quote data:")
    print(quote)

    print("\n------------------------------------------------------------")
    print("Workflow complete.")
    print("------------------------------------------------------------\n")


# ------------------------------------------------------------
# OPTIONAL: Allow script execution via `%run`
# ------------------------------------------------------------
if __name__ == "__main__":
    # Default symbol is AAPL unless user specifies otherwise
    run_marketdata_flow()
