"""
schwab_client.py
-----------------------------------------------------------------------------
Client module for Charles Schwab OAuth2 and Market Data APIs.
No keys, secrets, or active tokens are stored in this file.
-----------------------------------------------------------------------------
"""

import base64
import json
import os
import time
import urllib.parse
from typing import Any, Dict, Optional
import requests

AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
MARKETDATA_BASE = "https://api.schwabapi.com/marketdata/v1"
DEFAULT_TIMEOUT = 30  # seconds


class SchwabClient:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        token_file_path: Optional[str] = None,
    ) -> None:
        self.client_id = client_id or os.environ.get("SCHWAB_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("SCHWAB_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri or os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")
        self.token_file_path = token_file_path or os.environ.get(
            "SCHWAB_TOKEN_PATH", "schwab_tokens.json"
        )

        if not self.client_id:
            raise ValueError("Client ID is required. Pass client_id or set SCHWAB_CLIENT_ID.")

        self.tokens: Dict[str, Any] = {}
        self._load_tokens_from_disk()

    def _load_tokens_from_disk(self) -> None:
        if os.path.exists(self.token_file_path):
            try:
                with open(self.token_file_path, "r", encoding="utf-8") as f:
                    self.tokens = json.load(f)
            except (json.JSONDecodeError, IOError) as err:
                print(f"[Warning] Could not load tokens from {self.token_file_path}: {err}")
                self.tokens = {}

    def _save_tokens_to_disk(self, token_data: Dict[str, Any]) -> None:
        # 30-minute access token lifespan with a 60-second early refresh buffer
        expires_in = token_data.get("expires_in", 1800)
        token_data["expires_at"] = time.time() + expires_in - 60

        # Preserve the refresh token if the new payload omits it
        if "refresh_token" not in token_data and "refresh_token" in self.tokens:
            token_data["refresh_token"] = self.tokens["refresh_token"]

        self.tokens = token_data

        token_dir = os.path.dirname(self.token_file_path)
        if token_dir and not os.path.exists(token_dir):
            os.makedirs(token_dir, exist_ok=True)

        with open(self.token_file_path, "w", encoding="utf-8") as f:
            json.dump(self.tokens, f, indent=4)

    def _get_basic_auth_header(self, secret: Optional[str] = None) -> Dict[str, str]:
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
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "api",
        }
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code_for_token(
        self,
        code: str,
        client_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        secret = client_secret or self.client_secret
        if secret and not self.client_secret:
            self.client_secret = secret

        # Robust extraction: handles full URL or raw code string
        raw_code = code.strip()
        if "code=" in raw_code:
            # Extract whatever is after 'code=' up to the next '&' or end of string
            query_str = raw_code.split("?", 1)[-1] if "?" in raw_code else raw_code
            parsed_params = urllib.parse.parse_qs(query_str)
            if "code" in parsed_params:
                raw_code = parsed_params["code"][0]
            else:
                raw_code = raw_code.split("code=")[-1].split("&")[0]

        # Schwab codes often end in %40 (@); decode to raw symbol
        clean_code = urllib.parse.unquote(raw_code)

        headers = self._get_basic_auth_header(secret)
        payload = {
            "grant_type": "authorization_code",
            "code": clean_code,
            "redirect_uri": self.redirect_uri,
        }

        resp = requests.post(TOKEN_URL, headers=headers, data=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code != 200:
            print(f"[OAuth Exchange Error {resp.status_code}]: {resp.text}")

        resp.raise_for_status()
        token_data = resp.json()
        self._save_tokens_to_disk(token_data)
        return token_data

    def refresh_access_token(self) -> str:
        refresh_token = self.tokens.get("refresh_token")
        if not refresh_token:
            raise ValueError("No refresh token available. Manual authorization required.")

        headers = self._get_basic_auth_header()
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        resp = requests.post(TOKEN_URL, headers=headers, data=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code != 200:
            print(f"[Token Refresh Error {resp.status_code}]: {resp.text}")

        resp.raise_for_status()
        new_token_data = resp.json()
        self._save_tokens_to_disk(new_token_data)
        return new_token_data["access_token"]

    def get_valid_access_token(self) -> str:
        if not self.tokens or "access_token" not in self.tokens:
            raise RuntimeError("No tokens found. Run the authorization flow first.")

        if time.time() >= self.tokens.get("expires_at", 0):
            print("Access token expired. Refreshing token silently...")
            return self.refresh_access_token()

        return self.tokens["access_token"]

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        token = self.get_valid_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        url = f"{MARKETDATA_BASE}/quotes"
        params = {"symbols": symbol.upper().strip()}

        resp = requests.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()