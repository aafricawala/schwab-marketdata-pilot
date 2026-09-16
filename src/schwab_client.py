"""
schwab_client.py

This module defines the SchwabClient class, which manages:
1. Building the OAuth authorization URL.
2. Exchanging the initial authorization code for access and refresh tokens.
3. Caching and loading tokens to/from a local JSON file.
4. Automatically refreshing expired access tokens using the refresh token.
5. Making authenticated requests to Schwab's Market Data API.

SECURITY:
- No API keys, secrets, or tokens are hardcoded.
- Credentials must be passed via function arguments or environment variables.
- This file is safe to commit to version control.
"""

import base64
import json
import os
import time
import urllib.parse
from typing import Any, Dict, Optional

import requests

# Schwab OAuth endpoints
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"

# Schwab Market Data API base endpoint
MARKETDATA_BASE = "https://api.schwabapi.com/marketdata/v1"


class SchwabClient:
    """
    Client interface for Schwab OAuth2 and Market Data APIs.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: str = "https://127.0.0.1",
        token_file_path: str = "schwab_tokens.json",
    ) -> None:
        """
        Initialize the SchwabClient.

        Credentials fall back to environment variables if not passed explicitly:
        - SCHWAB_CLIENT_ID
        - SCHWAB_CLIENT_SECRET
        - SCHWAB_REDIRECT_URI
        - SCHWAB_TOKEN_PATH
        """
        self.client_id = client_id or os.environ.get("SCHWAB_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("SCHWAB_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri or os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")
        self.token_file_path = token_file_path or os.environ.get("SCHWAB_TOKEN_PATH", "schwab_tokens.json")

        if not self.client_id:
            raise ValueError("Client ID is required. Pass client_id or set SCHWAB_CLIENT_ID.")

        # In-memory token cache
        self.tokens: Dict[str, Any] = {}

        # Attempt to load existing tokens from the specified cache file
        self._load_tokens_from_disk()

    # ----------------------------------------------------------------------
    # TOKEN STORAGE & SERIALIZATION
    # ----------------------------------------------------------------------

    def _load_tokens_from_disk(self) -> None:
        """
        Attempts to read tokens from the configured JSON file path.
        """
        if os.path.exists(self.token_file_path):
            try:
                with open(self.token_file_path, "r", encoding="utf-8") as f:
                    self.tokens = json.load(f)
            except (json.JSONDecodeError, IOError) as err:
                print(f"Warning: Could not load tokens from {self.token_file_path}: {err}")
                self.tokens = {}

    def _save_tokens_to_disk(self, token_data: Dict[str, Any]) -> None:
        """
        Saves updated token payloads to disk with calculated expiration times.
        """
        # Schwab access tokens generally expire in 1800 seconds (30 mins).
        # We store 'expires_at' with a 60-second safety buffer.
        expires_in = token_data.get("expires_in", 1800)
        token_data["expires_at"] = time.time() + expires_in - 60

        # Preserve the refresh token if the new response omits it
        if "refresh_token" not in token_data and "refresh_token" in self.tokens:
            token_data["refresh_token"] = self.tokens["refresh_token"]

        self.tokens = token_data

        # Ensure target directory exists before writing
        token_dir = os.path.dirname(self.token_file_path)
        if token_dir and not os.path.exists(token_dir):
            os.makedirs(token_dir, exist_ok=True)

        with open(self.token_file_path, "w", encoding="utf-8") as f:
            json.dump(self.tokens, f, indent=4)

    # ----------------------------------------------------------------------
    # AUTHENTICATION HELPERS & HEADERS
    # ----------------------------------------------------------------------

    def _get_basic_auth_header(self, secret: Optional[str] = None) -> Dict[str, str]:
        """
        Generates the HTTP Basic Authorization header required by Schwab.
        Header Format: 'Authorization: Basic base64(client_id:client_secret)'
        """
        effective_secret = secret or self.client_secret
        if not effective_secret:
            raise ValueError("Client Secret is required for token requests.")

        credentials = f"{self.client_id}:{effective_secret}"
        encoded_creds = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

        return {
            "Authorization": f"Basic {encoded_creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def build_auth_url(self) -> str:
        """
        Constructs the interactive browser URL for the user to grant access.
        """
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "api",
        }
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    # ----------------------------------------------------------------------
    # TOKEN EXCHANGE & AUTOMATED REFRESH
    # ----------------------------------------------------------------------

    def exchange_code_for_token(
        self,
        code: str,
        client_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Exchanges the authorization code from the browser redirect for an access token.

        Key fixes applied:
        - URL-decodes the auth code to resolve '%40' issues.
        - Attaches HTTP Basic Auth headers instead of passing secret in form body only.
        - Caches returned tokens to disk.
        """
        secret = client_secret or self.client_secret
        if secret and not self.client_secret:
            self.client_secret = secret

        # Authorization codes copied from browser bars frequently include URL-encoded
        # entities (such as %40). URL-decoding ensures the clean string is posted.
        clean_code = urllib.parse.unquote(code.strip())

        headers = self._get_basic_auth_header(secret)
        payload = {
            "grant_type": "authorization_code",
            "code": clean_code,
            "redirect_uri": self.redirect_uri,
        }

        resp = requests.post(TOKEN_URL, headers=headers, data=payload)

        if resp.status_code != 200:
            # Output error details to assist troubleshooting if the request fails
            print(f"OAuth Exchange Error [{resp.status_code}]: {resp.text}")

        resp.raise_for_status()

        token_data = resp.json()
        self._save_tokens_to_disk(token_data)
        return token_data

    def refresh_access_token(self) -> str:
        """
        Exchanges the existing refresh_token for a new access_token without user interaction.
        Schwab refresh tokens are valid for 7 days.
        """
        refresh_token = self.tokens.get("refresh_token")
        if not refresh_token:
            raise ValueError(
                "No refresh token available. An initial interactive login is required."
            )

        headers = self._get_basic_auth_header()
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        resp = requests.post(TOKEN_URL, headers=headers, data=payload)

        if resp.status_code != 200:
            print(f"Token Refresh Error [{resp.status_code}]: {resp.text}")

        resp.raise_for_status()

        new_token_data = resp.json()
        self._save_tokens_to_disk(new_token_data)
        return new_token_data["access_token"]

    def get_valid_access_token(self) -> str:
        """
        Returns an active access token. If the cached access token is expired
        or within 60 seconds of expiry, it automatically triggers a silent refresh.
        """
        # If no tokens loaded, manual login is required
        if not self.tokens or "access_token" not in self.tokens:
            raise RuntimeError("No tokens found. Run the initial OAuth flow first.")

        # If current time is past expiration, fetch a fresh access token
        if time.time() >= self.tokens.get("expires_at", 0):
            print("Access token expired or expiring soon. Refreshing token silently...")
            return self.refresh_access_token()

        return self.tokens["access_token"]

    # ----------------------------------------------------------------------
    # MARKET DATA ENDPOINTS
    # ----------------------------------------------------------------------

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Retrieves real-time or delayed market quotes for a specified ticker symbol.
        Uses the valid or auto-refreshed access token.
        """
        token = self.get_valid_access_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        # Schwab's marketdata quotes endpoint expects query param: ?symbols=SYMBOL
        url = f"{MARKETDATA_BASE}/quotes"
        params = {"symbols": symbol.upper().strip()}

        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()

        return resp.json()