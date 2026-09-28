# Filename.py: schwab_client.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

# Filename.py: schwab_client.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

"""
# Execute this line of logic to process the data
schwab_client.py
"""

# Import specific components from a module
from __future__ import annotations

# Import the required external module
import base64
# Import the required external module
import email.utils
# Import the required external module
import json
# Import the required external module
import logging
# Import the required external module
import os
# Import the required external module
import threading
# Import the required external module
import time
# Import the required external module
import urllib.parse
# Import specific components from a module
from dataclasses import dataclass
# Import specific components from a module
from pathlib import Path
# Import specific components from a module
from typing import Any, Dict, List, Optional, Tuple, Union

# Import the required external module
import requests
# Import specific components from a module
from requests import Response, Session
# Import specific components from a module
from requests.adapters import HTTPAdapter
# Import specific components from a module
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# GATEWAY CONFIGURATION CONSTANTS
# ---------------------------------------------------------------------------
# Assign a value or initialize a variable
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
# Assign a value or initialize a variable
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
# Assign a value or initialize a variable
MARKETDATA_BASE = "https://api.schwabapi.com/marketdata/v1"

# Connect timeout: 3.05s (prevents TCP syn drop hang), Read timeout: 15.0s
# Assign a value or initialize a variable
DEFAULT_TIMEOUT: Tuple[float, float] = (3.05, 15.0)
# Assign a value or initialize a variable
DEFAULT_RETRIES = 3
# Assign a value or initialize a variable
DEFAULT_BACKOFF_FACTOR = 0.5
# Assign a value or initialize a variable
TOKEN_EXPIRY_BUFFER = 60  # Seconds before nominal expiry to proactively refresh

# Assign a value or initialize a variable
logger = logging.getLogger("schwab_client")
# Log an important message or event
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# CUSTOM EXCEPTION HIERARCHY
# ---------------------------------------------------------------------------
# Define a new data structure or class
class SchwabClientError(Exception):
    """Base exception for all Schwab client failures."""


# Define a new data structure or class
class TokenError(SchwabClientError):
    """Raised when token retrieval, decoding, persistence, or refresh fails."""


# Define a new data structure or class
class CallbackURLError(SchwabClientError):
    """Raised when the redirect_uri violates Schwab Developer Portal specifications."""


# Define a new data structure or class
class APIRequestError(SchwabClientError):
    """
    # Execute this line of logic to process the data
    Raised when an API endpoint returns an unrecoverable HTTP status.
    # Execute this line of logic to process the data
    Carries the HTTP status code, Schwab Correlation ID, and structured error details.
    """

    # Define a new function or method
    def __init__(
        # Execute this line of logic to process the data
        self,
        # Execute this line of logic to process the data
        message: str,
        # Assign a value or initialize a variable
        status_code: Optional[int] = None,
        # Assign a value or initialize a variable
        correl_id: Optional[str] = None,
        # Assign a value or initialize a variable
        error_details: Optional[str] = None,
    # Execute this line of logic to process the data
    ) -> None:
        # Execute this line of logic to process the data
        super().__init__(message)
        # Assign a value or initialize a variable
        self.status_code = status_code
        # Assign a value or initialize a variable
        self.correl_id = correl_id or "UNKNOWN"
        # Assign a value or initialize a variable
        self.error_details = error_details or ""


# ---------------------------------------------------------------------------
# IMMUTABLE TOKEN CONTAINER
# ---------------------------------------------------------------------------
# Assign a value or initialize a variable
@dataclass(frozen=True)
# Define a new data structure or class
class TokenPayload:
    """Thread-safe, immutable representation of OAuth credentials and lifecycle timestamps."""
    # Execute this line of logic to process the data
    access_token: str
    # Execute this line of logic to process the data
    token_type: str
    # Execute this line of logic to process the data
    expires_in: int
    # Execute this line of logic to process the data
    expires_at: float
    # Assign a value or initialize a variable
    refresh_token: Optional[str] = None
    # Assign a value or initialize a variable
    scope: Optional[str] = None

    # Apply a decorator to modify function behavior
    @classmethod
    # Define a new function or method
    def from_dict(cls, data: Dict[str, Any]) -> "TokenPayload":
        # Assign a value or initialize a variable
        now = time.time()
        # Assign a value or initialize a variable
        expires_in = int(data.get("expires_in", 1800))
        # Assign a value or initialize a variable
        expires_at = float(data.get("expires_at", now + expires_in))

        # Return the final computed result to the caller
        return cls(
            # Assign a value or initialize a variable
            access_token=data["access_token"],
            # Assign a value or initialize a variable
            token_type=data.get("token_type", "Bearer"),
            # Assign a value or initialize a variable
            expires_in=expires_in,
            # Assign a value or initialize a variable
            expires_at=expires_at,
            # Assign a value or initialize a variable
            refresh_token=data.get("refresh_token"),
            # Assign a value or initialize a variable
            scope=data.get("scope"),
        # Execute this line of logic to process the data
        )

    # Define a new function or method
    def to_dict(self) -> Dict[str, Any]:
        # Return the final computed result to the caller
        return {
            # Execute this line of logic to process the data
            "access_token": self.access_token,
            # Execute this line of logic to process the data
            "token_type": self.token_type,
            # Execute this line of logic to process the data
            "expires_in": self.expires_in,
            # Execute this line of logic to process the data
            "expires_at": self.expires_at,
            # Execute this line of logic to process the data
            "refresh_token": self.refresh_token,
            # Execute this line of logic to process the data
            "scope": self.scope,
        # Execute this line of logic to process the data
        }


# ---------------------------------------------------------------------------
# HARDENED SECURITY & VALIDATION HELPERS
# ---------------------------------------------------------------------------
# Define a new function or method
def validate_and_normalize_redirect_uri(uri: str) -> str:
    """
    # Execute this line of logic to process the data
    Validates and standardizes redirect_uri according to Schwab's Developer Portal rules:
      # Execute this line of logic to process the data
      1. Must be a non-empty string.
      # Execute this line of logic to process the data
      2. Must not exceed Schwab's maximum 255-character ceiling.
      # Execute this line of logic to process the data
      3. Must not contain whitespace characters.
      # Execute this line of logic to process the data
      4. Must declare a secure scheme ('https') as required by LMS.
      # Execute this line of logic to process the data
      5. Normalizes bare root paths (e.g., 'https://127.0.0.1/' -> 'https://127.0.0.1')
         # Execute this line of logic to process the data
         to prevent string-mismatch errors during token exchange.
    """
    # Check a conditional statement
    if not uri or not isinstance(uri, str):
        # Raise an error to stop execution
        raise CallbackURLError("redirect_uri must be a non-empty string.")

    # Assign a value or initialize a variable
    cleaned = uri.strip()

    # Check a conditional statement
    if len(cleaned) > 255:
        # Raise an error to stop execution
        raise CallbackURLError(
            # Execute this line of logic to process the data
            f"redirect_uri exceeds Schwab's 255-character ceiling ({len(cleaned)} chars): '{cleaned}'"
        # Execute this line of logic to process the data
        )

    # Check a conditional statement
    if any(c.isspace() for c in cleaned):
        # Raise an error to stop execution
        raise CallbackURLError(f"redirect_uri contains illegal whitespace characters: '{cleaned}'")

    # Assign a value or initialize a variable
    parsed = urllib.parse.urlparse(cleaned)

    # Check a conditional statement
    if parsed.scheme.lower() != "https":
        # Raise an error to stop execution
        raise CallbackURLError(
            # Execute this line of logic to process the data
            f"Invalid scheme '{parsed.scheme}' in redirect_uri '{cleaned}'. "
            # Execute this line of logic to process the data
            "Schwab Developer Portal requirements mandate the 'https://' scheme."
        # Execute this line of logic to process the data
        )

    # Check a conditional statement
    if parsed.path == "/" and not parsed.query and not parsed.fragment:
        # Assign a value or initialize a variable
        cleaned = f"{parsed.scheme}://{parsed.netloc}"

    # Return the final computed result to the caller
    return cleaned


# Define a new function or method
def _atomic_write_secure_json(target_path: Path, data: Dict[str, Any]) -> None:
    """
    # Execute this line of logic to process the data
    Atomically writes JSON payload to disk with POSIX 0o600 permissions.
    # Execute this line of logic to process the data
    Eliminates the umask vulnerability window using low-level os.open before writing.
    """
    # Assign a value or initialize a variable
    target_path.parent.mkdir(parents=True, exist_ok=True)
    # Assign a value or initialize a variable
    tmp_path = target_path.with_name(f"{target_path.name}.tmp.{os.getpid()}_{threading.get_ident()}")

    # Assign a value or initialize a variable
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    # Check a conditional statement
    if hasattr(os, "O_NOFOLLOW"):
        # Assign a value or initialize a variable
        flags |= os.O_NOFOLLOW

    # Assign a value or initialize a variable
    fd = os.open(tmp_path, flags, 0o600)
    # Start a try-catch block to handle potential errors
    try:
        # Assign a value or initialize a variable
        with open(fd, "w", encoding="utf-8", closefd=True) as f:
            # Assign a value or initialize a variable
            json.dump(data, f, indent=4)
            # Execute this line of logic to process the data
            f.flush()
            # Execute this line of logic to process the data
            os.fsync(f.fileno())
    # Catch and handle an exception
    except Exception:
        # Check a conditional statement
        if tmp_path.exists():
            # Execute this line of logic to process the data
            tmp_path.unlink()
        # Execute this line of logic to process the data
        raise

    # Execute this line of logic to process the data
    os.replace(tmp_path, target_path)


# Define a new function or method
def _safe_json_parse(resp: Response) -> Dict[str, Any]:
    """Safely extracts JSON payload without leaking internal gateway tokens on error."""
    # Start a try-catch block to handle potential errors
    try:
        # Return the final computed result to the caller
        return resp.json()
    # Catch and handle an exception
    except ValueError as exc:
        # Assign a value or initialize a variable
        correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
        # Raise an error to stop execution
        raise APIRequestError(
            # Execute this line of logic to process the data
            f"Invalid JSON returned from endpoint (HTTP {resp.status_code}). CorrelId: {correl_id}",
            # Assign a value or initialize a variable
            status_code=resp.status_code,
            # Assign a value or initialize a variable
            correl_id=correl_id,
        # Execute this line of logic to process the data
        ) from exc


# Define a new function or method
def _parse_schwab_error(resp: Response) -> str:
    """
    # Execute this line of logic to process the data
    Extracts detailed diagnostics from Schwab's structured JSON error schema:
    # Execute this line of logic to process the data
    {"errors": [{"status": 400, "title": "Bad Request", "detail": "...", "id": "guid"}]}
    # Execute this line of logic to process the data
    Falls back to sanitized raw text if payload does not match schema.
    """
    # Start a try-catch block to handle potential errors
    try:
        # Assign a value or initialize a variable
        data = resp.json()
        # Check a conditional statement
        if isinstance(data, dict) and "errors" in data and isinstance(data["errors"], list):
            # Assign a value or initialize a variable
            messages = []
            # Start a loop over the given collection
            for err in data["errors"]:
                # Check a conditional statement
                if isinstance(err, dict):
                    # Assign a value or initialize a variable
                    title = err.get("title", "")
                    # Assign a value or initialize a variable
                    detail = err.get("detail", "")
                    # Assign a value or initialize a variable
                    err_id = err.get("id", "")
                    # Assign a value or initialize a variable
                    elements = [e for e in (title, detail) if e]
                    # Assign a value or initialize a variable
                    msg = ": ".join(elements) if elements else "Unspecified Schwab error"
                    # Check a conditional statement
                    if err_id:
                        # Assign a value or initialize a variable
                        msg += f" (Error ID: {err_id})"
                    # Execute this line of logic to process the data
                    messages.append(msg)
            # Check a conditional statement
            if messages:
                # Return the final computed result to the caller
                return " | ".join(messages)
    # Catch and handle an exception
    except Exception:
        # Execute this line of logic to process the data
        pass

    # Return the final computed result to the caller
    return resp.text.strip()[:300] if resp.text else "No error payload returned by gateway."


# Define a new function or method
def _parse_retry_after(header_val: Optional[str], default_wait: float) -> float:
    """Parses RFC-7231 or integer seconds from HTTP Retry-After headers."""
    # Check a conditional statement
    if not header_val:
        # Return the final computed result to the caller
        return default_wait
    # Start a try-catch block to handle potential errors
    try:
        # Return the final computed result to the caller
        return max(0.0, float(header_val))
    # Catch and handle an exception
    except ValueError:
        # Execute this line of logic to process the data
        pass
    # Start a try-catch block to handle potential errors
    try:
        # Assign a value or initialize a variable
        date_tuple = email.utils.parsedate_tz(header_val)
        # Check a conditional statement
        if date_tuple:
            # Assign a value or initialize a variable
            target_time = email.utils.mktime_tz(date_tuple)
            # Return the final computed result to the caller
            return max(0.0, target_time - time.time())
    # Catch and handle an exception
    except Exception:
        # Execute this line of logic to process the data
        pass
    # Return the final computed result to the caller
    return default_wait


# ---------------------------------------------------------------------------
# CLIENT IMPLEMENTATION
# ---------------------------------------------------------------------------
# Define a new data structure or class
class SchwabClient:
    """
    # Execute this line of logic to process the data
    Thread-safe, institutional-grade market data client for Charles Schwab.
    # Execute this line of logic to process the data
    Handles automated token persistence, proactive background refresh, and endpoint queries.
    """

    # Define a new function or method
    def __init__(
        # Execute this line of logic to process the data
        self,
        # Assign a value or initialize a variable
        client_id: Optional[str] = None,
        # Assign a value or initialize a variable
        client_secret: Optional[str] = None,
        # Assign a value or initialize a variable
        redirect_uri: Optional[str] = None,
        # Assign a value or initialize a variable
        token_file_path: Optional[Union[str, Path]] = None,
        # Assign a value or initialize a variable
        session: Optional[Session] = None,
        # Assign a value or initialize a variable
        timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
        # Assign a value or initialize a variable
        max_retries: int = DEFAULT_RETRIES,
        # Assign a value or initialize a variable
        pool_connections: int = 50,
        # Assign a value or initialize a variable
        pool_maxsize: int = 50,
    # Execute this line of logic to process the data
    ) -> None:
        # Assign a value or initialize a variable
        self.client_id = (client_id or os.environ.get("SCHWAB_CLIENT_ID", "")).strip()
        # Assign a value or initialize a variable
        self.client_secret = (client_secret or os.environ.get("SCHWAB_CLIENT_SECRET", "")).strip()

        # Assign a value or initialize a variable
        raw_redirect = (redirect_uri or os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")).strip()
        # Assign a value or initialize a variable
        self.redirect_uri = validate_and_normalize_redirect_uri(raw_redirect)

        # Assign a value or initialize a variable
        raw_token_path = token_file_path or os.environ.get("SCHWAB_TOKEN_PATH", "schwab_tokens.json")
        # Assign a value or initialize a variable
        self.token_file_path = Path(raw_token_path).resolve()

        # Check a conditional statement
        if not self.client_id:
            # Raise an error to stop execution
            raise ValueError("Configuration missing: SCHWAB_CLIENT_ID must be provided.")

        # Assign a value or initialize a variable
        self.timeout = timeout
        # Assign a value or initialize a variable
        self.max_retries = max(0, max_retries)

        # Thread synchronization primitives
        # Assign a value or initialize a variable
        self._tokens_lock = threading.RLock()
        # Assign a value or initialize a variable
        self._token_payload: Optional[TokenPayload] = None

        # Build resilient connection pool
        # Check a conditional statement
        if session:
            # Assign a value or initialize a variable
            self.session = session
        # Execute this line of logic to process the data
        else:
            # Assign a value or initialize a variable
            self.session = requests.Session()
            # Assign a value or initialize a variable
            adapter = HTTPAdapter(
                # Assign a value or initialize a variable
                pool_connections=pool_connections,
                # Assign a value or initialize a variable
                pool_maxsize=pool_maxsize,
                # Assign a value or initialize a variable
                max_retries=Retry(total=0),  # Handled via custom exponential backoff engine
            # Execute this line of logic to process the data
            )
            # Execute this line of logic to process the data
            self.session.mount("https://", adapter)

        # Execute this line of logic to process the data
        self._load_tokens_from_disk()

    # -----------------------------------------------------------------------
    # TOKEN PERSISTENCE & CONCURRENCY
    # -----------------------------------------------------------------------
    # Define a new function or method
    def _load_tokens_from_disk(self) -> None:
        """Loads cached tokens into memory under thread lock."""
        # Execute this line of logic to process the data
        with self._tokens_lock:
            # Check a conditional statement
            if not self.token_file_path.exists():
                # Assign a value or initialize a variable
                self._token_payload = None
                # Execute this line of logic to process the data
                return

            # Start a try-catch block to handle potential errors
            try:
                # Assign a value or initialize a variable
                with self.token_file_path.open("r", encoding="utf-8") as f:
                    # Assign a value or initialize a variable
                    data = json.load(f)
                # Check a conditional statement
                if "access_token" in data:
                    # Assign a value or initialize a variable
                    self._token_payload = TokenPayload.from_dict(data)
                # Execute this line of logic to process the data
                else:
                    # Assign a value or initialize a variable
                    self._token_payload = None
            # Catch and handle an exception
            except Exception as exc:
                # Log an important message or event
                logger.warning("Unreadable token store at %s: %s", self.token_file_path, exc)
                # Assign a value or initialize a variable
                self._token_payload = None

    # Define a new function or method
    def _persist_tokens(self, token_data: Dict[str, Any]) -> TokenPayload:
        """Atomically caches new token sets to disk and updates in-memory reference."""
        # Execute this line of logic to process the data
        with self._tokens_lock:
            # Check a conditional statement
            if "refresh_token" not in token_data and self._token_payload and self._token_payload.refresh_token:
                # Assign a value or initialize a variable
                token_data["refresh_token"] = self._token_payload.refresh_token

            # Assign a value or initialize a variable
            expires_in = int(token_data.get("expires_in", 1800))
            # Assign a value or initialize a variable
            token_data["expires_at"] = time.time() + expires_in

            # Execute this line of logic to process the data
            _atomic_write_secure_json(self.token_file_path, token_data)
            # Assign a value or initialize a variable
            self._token_payload = TokenPayload.from_dict(token_data)
            # Return the final computed result to the caller
            return self._token_payload

    # Define a new function or method
    def _get_basic_auth_header(self) -> Dict[str, str]:
        """Builds HTTP Basic Authorization header: 'Basic base64(client_id:client_secret)'."""
        # Check a conditional statement
        if not self.client_secret:
            # Raise an error to stop execution
            raise ValueError("Operation requires SCHWAB_CLIENT_SECRET.")
        # Assign a value or initialize a variable
        raw_creds = f"{self.client_id}:{self.client_secret}"
        # Assign a value or initialize a variable
        encoded = base64.b64encode(raw_creds.encode("utf-8")).decode("utf-8")
        # Return the final computed result to the caller
        return {
            # Execute this line of logic to process the data
            "Authorization": f"Basic {encoded}",
            # Execute this line of logic to process the data
            "Content-Type": "application/x-www-form-urlencoded",
        # Execute this line of logic to process the data
        }

    # -----------------------------------------------------------------------
    # OAUTH TRANSACTIONS
    # -----------------------------------------------------------------------
    # Define a new function or method
    def build_auth_url(self, state: Optional[str] = None) -> str:
        """Constructs user consent URL with validated callback URI and optional CSRF state."""
        # Assign a value or initialize a variable
        params = {
            # Execute this line of logic to process the data
            "response_type": "code",
            # Execute this line of logic to process the data
            "client_id": self.client_id,
            # Execute this line of logic to process the data
            "redirect_uri": self.redirect_uri,
            # Execute this line of logic to process the data
            "scope": "api",
        # Execute this line of logic to process the data
        }
        # Check a conditional statement
        if state:
            # Assign a value or initialize a variable
            params["state"] = state
        # Return the final computed result to the caller
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    # Define a new function or method
    def exchange_code_for_token(
        # Execute this line of logic to process the data
        self,
        # Execute this line of logic to process the data
        code_or_url: str,
        # Assign a value or initialize a variable
        expected_state: Optional[str] = None,
    # Execute this line of logic to process the data
    ) -> TokenPayload:
        """
        # Execute this line of logic to process the data
        Exchanges the authorization code for access and refresh tokens.
        # Execute this line of logic to process the data
        Validates the returned CSRF 'state' token if expected_state was supplied.
        """
        # Assign a value or initialize a variable
        raw = code_or_url.strip()
        # Assign a value or initialize a variable
        extracted_state = None

        # Check a conditional statement
        if "code=" in raw:
            # Assign a value or initialize a variable
            query = raw.split("?", 1)[-1] if "?" in raw else raw
            # Assign a value or initialize a variable
            parsed = urllib.parse.parse_qs(query)
            # Assign a value or initialize a variable
            extracted_code = parsed.get("code", [None])[0]
            # Assign a value or initialize a variable
            extracted_state = parsed.get("state", [None])[0]
            # Check a conditional statement
            if not extracted_code:
                # Assign a value or initialize a variable
                extracted_code = raw.split("code=")[-1].split("&")[0]
        # Execute this line of logic to process the data
        else:
            # Assign a value or initialize a variable
            extracted_code = raw

        # Cryptographic state verification (RFC 6749 Section 10.12)
        # Check a conditional statement
        if expected_state:
            # Check a conditional statement
            if not extracted_state:
                # Raise an error to stop execution
                raise TokenError("Security Alert: Authorization response is missing the required 'state' parameter.")
            # Check a conditional statement
            if extracted_state != expected_state:
                # Raise an error to stop execution
                raise TokenError(
                    # Execute this line of logic to process the data
                    f"Security Alert: CSRF state mismatch detected! Expected '{expected_state}', got '{extracted_state}'."
                # Execute this line of logic to process the data
                )

        # Assign a value or initialize a variable
        sanitized_code = urllib.parse.unquote((extracted_code or "").strip())
        # Check a conditional statement
        if not sanitized_code:
            # Raise an error to stop execution
            raise TokenError("Failed to extract valid authorization code parameter.")

        # Assign a value or initialize a variable
        payload = {
            # Execute this line of logic to process the data
            "grant_type": "authorization_code",
            # Execute this line of logic to process the data
            "code": sanitized_code,
            # Execute this line of logic to process the data
            "redirect_uri": self.redirect_uri,
        # Execute this line of logic to process the data
        }

        # Assign a value or initialize a variable
        resp = self._raw_http_request("POST", TOKEN_URL, headers=self._get_basic_auth_header(), data=payload)
        # Check a conditional statement
        if resp.status_code != 200:
            # Assign a value or initialize a variable
            correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
            # Assign a value or initialize a variable
            err_msg = _parse_schwab_error(resp)
            # Raise an error to stop execution
            raise TokenError(
                # Execute this line of logic to process the data
                f"OAuth code exchange failed (HTTP {resp.status_code}). CorrelId: {correl_id} | Details: {err_msg}"
            # Execute this line of logic to process the data
            )

        # Return the final computed result to the caller
        return self._persist_tokens(_safe_json_parse(resp))

    # Define a new function or method
    def refresh_access_token(self) -> TokenPayload:
        """Executes a silent token refresh using double-checked thread synchronization."""
        # Execute this line of logic to process the data
        with self._tokens_lock:
            # Check a conditional statement
            if self._token_payload and time.time() < (self._token_payload.expires_at - TOKEN_EXPIRY_BUFFER):
                # Return the final computed result to the caller
                return self._token_payload

            # Check a conditional statement
            if not self._token_payload or not self._token_payload.refresh_token:
                # Raise an error to stop execution
                raise TokenError("No refresh token available. Interactive authorization required.")

            # Assign a value or initialize a variable
            payload = {
                # Execute this line of logic to process the data
                "grant_type": "refresh_token",
                # Execute this line of logic to process the data
                "refresh_token": self._token_payload.refresh_token,
            # Execute this line of logic to process the data
            }

            # Assign a value or initialize a variable
            resp = self._raw_http_request("POST", TOKEN_URL, headers=self._get_basic_auth_header(), data=payload)
            # Check a conditional statement
            if resp.status_code != 200:
                # Assign a value or initialize a variable
                correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
                # Assign a value or initialize a variable
                err_msg = _parse_schwab_error(resp)
                # Raise an error to stop execution
                raise TokenError(
                    # Execute this line of logic to process the data
                    f"Refresh token rejected by Schwab (HTTP {resp.status_code}). "
                    # Execute this line of logic to process the data
                    f"CorrelId: {correl_id} | Details: {err_msg}"
                # Execute this line of logic to process the data
                )

            # Return the final computed result to the caller
            return self._persist_tokens(_safe_json_parse(resp))

    # Define a new function or method
    def get_valid_access_token(self) -> str:
        """Fast-path thread-safe retrieval of validated access token."""
        # Assign a value or initialize a variable
        current = self._token_payload
        # Check a conditional statement
        if current and time.time() < (current.expires_at - TOKEN_EXPIRY_BUFFER):
            # Return the final computed result to the caller
            return current.access_token

        # Return the final computed result to the caller
        return self.refresh_access_token().access_token

    # -----------------------------------------------------------------------
    # RESILIENT HTTP EXECUTION ENGINE
    # -----------------------------------------------------------------------
    # Define a new function or method
    def _raw_http_request(
        # Execute this line of logic to process the data
        self,
        # Execute this line of logic to process the data
        method: str,
        # Execute this line of logic to process the data
        url: str,
        # Assign a value or initialize a variable
        headers: Optional[Dict[str, str]] = None,
        # Assign a value or initialize a variable
        params: Optional[Dict[str, Any]] = None,
        # Assign a value or initialize a variable
        data: Optional[Dict[str, Any]] = None,
    # Execute this line of logic to process the data
    ) -> Response:
        """Executes raw HTTP calls with entropy-jittered exponential backoff and 429 adherence."""
        # Assign a value or initialize a variable
        attempt = 0
        # Execute this line of logic to process the data
        while True:
            # Assign a value or initialize a variable
            attempt += 1
            # Start a try-catch block to handle potential errors
            try:
                # Assign a value or initialize a variable
                resp = self.session.request(
                    # Assign a value or initialize a variable
                    method=method,
                    # Assign a value or initialize a variable
                    url=url,
                    # Assign a value or initialize a variable
                    headers=headers,
                    # Assign a value or initialize a variable
                    params=params,
                    # Assign a value or initialize a variable
                    data=data,
                    # Assign a value or initialize a variable
                    timeout=self.timeout,
                # Execute this line of logic to process the data
                )
            # Catch and handle an exception
            except requests.RequestException as err:
                # Check a conditional statement
                if attempt > self.max_retries:
                    # Raise an error to stop execution
                    raise APIRequestError(f"Network transport failure after {attempt} attempts: {err}") from err
                # Assign a value or initialize a variable
                backoff = DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1))
                # Execute this line of logic to process the data
                time.sleep(backoff + (time.time() % 0.2))
                # Execute this line of logic to process the data
                continue

            # Handle rate limiting
            # Check a conditional statement
            if resp.status_code == 429:
                # Assign a value or initialize a variable
                correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
                # Assign a value or initialize a variable
                wait_time = _parse_retry_after(
                    # Execute this line of logic to process the data
                    resp.headers.get("Retry-After"),
                    # Execute this line of logic to process the data
                    DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1)),
                # Execute this line of logic to process the data
                )
                # Log an important message or event
                logger.warning(
                    # Execute this line of logic to process the data
                    "Schwab rate limit triggered (CorrelId: %s). Backing off for %.2f seconds.",
                    # Execute this line of logic to process the data
                    correl_id,
                    # Execute this line of logic to process the data
                    wait_time,
                # Execute this line of logic to process the data
                )
                # Check a conditional statement
                if attempt > self.max_retries:
                    # Raise an error to stop execution
                    raise APIRequestError(
                        # Execute this line of logic to process the data
                        f"Exceeded maximum retries on HTTP 429 Rate Limit. CorrelId: {correl_id}",
                        # Assign a value or initialize a variable
                        status_code=429,
                        # Assign a value or initialize a variable
                        correl_id=correl_id,
                    # Execute this line of logic to process the data
                    )
                # Execute this line of logic to process the data
                time.sleep(wait_time)
                # Execute this line of logic to process the data
                continue

            # Retry transient server errors
            # Check a conditional statement
            if 500 <= resp.status_code < 600:
                # Assign a value or initialize a variable
                correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
                # Check a conditional statement
                if attempt > self.max_retries:
                    # Assign a value or initialize a variable
                    err_msg = _parse_schwab_error(resp)
                    # Raise an error to stop execution
                    raise APIRequestError(
                        # Execute this line of logic to process the data
                        f"Persistent server failure (HTTP {resp.status_code}). "
                        # Execute this line of logic to process the data
                        f"CorrelId: {correl_id} | Details: {err_msg}",
                        # Assign a value or initialize a variable
                        status_code=resp.status_code,
                        # Assign a value or initialize a variable
                        correl_id=correl_id,
                        # Assign a value or initialize a variable
                        error_details=err_msg,
                    # Execute this line of logic to process the data
                    )
                # Assign a value or initialize a variable
                backoff = DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1))
                # Execute this line of logic to process the data
                time.sleep(backoff)
                # Execute this line of logic to process the data
                continue

            # Return the final computed result to the caller
            return resp

    # Define a new function or method
    def _execute_authenticated(
        # Execute this line of logic to process the data
        self,
        # Execute this line of logic to process the data
        endpoint_path: str,
        # Assign a value or initialize a variable
        params: Optional[Dict[str, Any]] = None,
    # Execute this line of logic to process the data
    ) -> Dict[str, Any]:
        """Base API handler with automatic 401 token recovery and diagnostic logging."""
        # Assign a value or initialize a variable
        target_url = f"{MARKETDATA_BASE}{endpoint_path}"

        # Start a loop over the given collection
        for is_recovery_attempt in (False, True):
            # Assign a value or initialize a variable
            token = self.get_valid_access_token()
            # Assign a value or initialize a variable
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

            # Assign a value or initialize a variable
            resp = self._raw_http_request("GET", target_url, headers=headers, params=params)

            # Self-healing on unexpected token invalidation
            # Check a conditional statement
            if resp.status_code == 401 and not is_recovery_attempt:
                # Assign a value or initialize a variable
                correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
                # Log an important message or event
                logger.warning("HTTP 401 received (CorrelId: %s). Forcing access token refresh.", correl_id)
                # Execute this line of logic to process the data
                self.refresh_access_token()
                # Execute this line of logic to process the data
                continue

            # Check a conditional statement
            if resp.status_code != 200:
                # Assign a value or initialize a variable
                correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
                # Assign a value or initialize a variable
                version = resp.headers.get("Schwab-Resource-Version", "1")
                # Assign a value or initialize a variable
                err_msg = _parse_schwab_error(resp)

                # Raise an error to stop execution
                raise APIRequestError(
                    # Execute this line of logic to process the data
                    f"API request failed on {endpoint_path} (HTTP {resp.status_code}). "
                    # Execute this line of logic to process the data
                    f"CorrelId: {correl_id} | Version: {version} | Details: {err_msg}",
                    # Assign a value or initialize a variable
                    status_code=resp.status_code,
                    # Assign a value or initialize a variable
                    correl_id=correl_id,
                    # Assign a value or initialize a variable
                    error_details=err_msg,
                # Execute this line of logic to process the data
                )

            # Return the final computed result to the caller
            return _safe_json_parse(resp)

        # Assign a value or initialize a variable
        correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
        # Raise an error to stop execution
        raise APIRequestError(
            # Execute this line of logic to process the data
            f"Request failed after re-authentication recovery attempt. CorrelId: {correl_id}",
            # Assign a value or initialize a variable
            status_code=401,
            # Assign a value or initialize a variable
            correl_id=correl_id,
        # Execute this line of logic to process the data
        )

    # -----------------------------------------------------------------------
    # ALL 7 SCHWAB MARKET DATA ENDPOINT FAMILIES (FULLY PARAMETERIZED)
    # -----------------------------------------------------------------------
    # Define a new function or method
    def get_quotes(
        # Execute this line of logic to process the data
        self,
        # Execute this line of logic to process the data
        symbols: Union[str, List[str]],
        # Assign a value or initialize a variable
        fields: Optional[str] = None,
    # Execute this line of logic to process the data
    ) -> Dict[str, Any]:
        """
        # Execute this line of logic to process the data
        1. Quotes: Real-time/delayed quotes for single or multiple symbols.
        # Execute this line of logic to process the data
        Parameters:
            # Execute this line of logic to process the data
            symbols: Single ticker or list/comma-delimited tickers.
            # Execute this line of logic to process the data
            fields: Comma-separated subset filter: 'quote,fundamental,extended,reference,regular'.
        """
        # Check a conditional statement
        if isinstance(symbols, list):
            # Assign a value or initialize a variable
            clean_syms = ",".join(str(s).strip().upper() for s in symbols if str(s).strip())
        # Execute this line of logic to process the data
        else:
            # Assign a value or initialize a variable
            clean_syms = ",".join(str(s).strip().upper() for s in str(symbols).split(",") if str(s).strip())

        # Check a conditional statement
        if not clean_syms:
            # Raise an error to stop execution
            raise ValueError("Parameter 'symbols' must contain at least one valid ticker symbol.")

        # Assign a value or initialize a variable
        params: Dict[str, Any] = {"symbols": clean_syms}
        # Check a conditional statement
        if fields:
            # Assign a value or initialize a variable
            params["fields"] = fields.strip()
        # Assign a value or initialize a variable
        return self._execute_authenticated("/quotes", params=params)

    # Define a new function or method
    def get_quote(
        # Execute this line of logic to process the data
        self,
        # Execute this line of logic to process the data
        symbol: str,
        # Assign a value or initialize a variable
        fields: Optional[str] = None,
    # Execute this line of logic to process the data
    ) -> Dict[str, Any]:
        """
        # Execute this line of logic to process the data
        Convenience method: Retrieves quote breakdown for a single isolated symbol.
        """
        # Check a conditional statement
        if not symbol or not str(symbol).strip():
            # Raise an error to stop execution
            raise ValueError("Parameter 'symbol' must be a non-empty string.")

        # Assign a value or initialize a variable
        clean_sym = str(symbol).strip().upper()
        # Assign a value or initialize a variable
        payload = self.get_quotes(symbols=clean_sym, fields=fields)
        # Return the final computed result to the caller
        return payload.get(clean_sym, payload)

    # Define a new function or method
    def get_price_history(
        # Execute this line of logic to process the data
        self,
        # Execute this line of logic to process the data
        symbol: str,
        # Assign a value or initialize a variable
        period_type: str = "year",
        # Assign a value or initialize a variable
        period: int = 1,
        # Assign a value or initialize a variable
        frequency_type: str = "daily",
        # Assign a value or initialize a variable
        frequency: int = 1,
        # Assign a value or initialize a variable
        start_date: Optional[int] = None,
        # Assign a value or initialize a variable
        end_date: Optional[int] = None,
        # Assign a value or initialize a variable
        need_extended_hours: bool = False,
    # Execute this line of logic to process the data
    ) -> Dict[str, Any]:
        """
        # Execute this line of logic to process the data
        2. Price History: Historical OHLCV candle bars across custom time horizons.
        # Execute this line of logic to process the data
        Parameters:
            # Execute this line of logic to process the data
            symbol: Ticker symbol.
            # Execute this line of logic to process the data
            period_type: 'day', 'month', 'year', or 'ytd'.
            # Assign a value or initialize a variable
            period: Lookback units (e.g., period=20 with period_type='year' pulls 20 years).
            # Execute this line of logic to process the data
            frequency_type: 'minute', 'daily', 'weekly', or 'monthly'.
            # Execute this line of logic to process the data
            frequency: Frequency multiplier (e.g., 1 for 1-day candles, 5 for 5-minute candles).
            # Execute this line of logic to process the data
            start_date: Start epoch in milliseconds.
            # Execute this line of logic to process the data
            end_date: End epoch in milliseconds.
            # Execute this line of logic to process the data
            need_extended_hours: Includes pre- and post-market trading sessions.
        """
        # Check a conditional statement
        if not symbol or not str(symbol).strip():
            # Raise an error to stop execution
            raise ValueError("Parameter 'symbol' must be a non-empty string.")

        # Assign a value or initialize a variable
        params: Dict[str, Any] = {
            # Execute this line of logic to process the data
            "symbol": str(symbol).strip().upper(),
            # Execute this line of logic to process the data
            "periodType": period_type.lower(),
            # Execute this line of logic to process the data
            "period": period,
            # Execute this line of logic to process the data
            "frequencyType": frequency_type.lower(),
            # Execute this line of logic to process the data
            "frequency": frequency,
            # Execute this line of logic to process the data
            "needExtendedHoursData": str(need_extended_hours).lower(),
        # Execute this line of logic to process the data
        }
        # Check a conditional statement
        if start_date is not None:
            # Assign a value or initialize a variable
            params["startDate"] = start_date
        # Check a conditional statement
        if end_date is not None:
            # Assign a value or initialize a variable
            params["endDate"] = end_date
        # Assign a value or initialize a variable
        return self._execute_authenticated("/pricehistory", params=params)

    # Define a new function or method
    def get_option_chain(
        # Execute this line of logic to process the data
        self,
        # Execute this line of logic to process the data
        symbol: str,
        # Assign a value or initialize a variable
        contract_type: str = "ALL",
        # Assign a value or initialize a variable
        strike_count: Optional[int] = None,
        # Assign a value or initialize a variable
        include_underlying_quote: bool = True,
        # Assign a value or initialize a variable
        strategy: str = "SINGLE",
        # Assign a value or initialize a variable
        interval: Optional[float] = None,
        # Assign a value or initialize a variable
        strike: Optional[float] = None,
        # Assign a value or initialize a variable
        from_date: Optional[str] = None,
        # Assign a value or initialize a variable
        to_date: Optional[str] = None,
    # Execute this line of logic to process the data
    ) -> Dict[str, Any]:
        """
        # Execute this line of logic to process the data
        3. Option Chains: Real-time strike matrix with implied volatility and Greeks.
        # Execute this line of logic to process the data
        Parameters:
            # Execute this line of logic to process the data
            symbol: Underlying ticker symbol.
            # Execute this line of logic to process the data
            contract_type: 'CALL', 'PUT', or 'ALL'.
            # Execute this line of logic to process the data
            strike_count: Number of strikes above/below ATM. Pass None for full unbounded chain.
            # Execute this line of logic to process the data
            strategy: 'SINGLE', 'ANALYTICAL', 'COVERED', 'VERTICAL', etc.
            # Execute this line of logic to process the data
            interval: Strike interval filter.
            # Execute this line of logic to process the data
            strike: Exact strike price filter.
            # Execute this line of logic to process the data
            from_date: Expiration filter start (YYYY-MM-DD).
            # Execute this line of logic to process the data
            to_date: Expiration filter end (YYYY-MM-DD).
        """
        # Check a conditional statement
        if not symbol or not str(symbol).strip():
            # Raise an error to stop execution
            raise ValueError("Parameter 'symbol' must be a non-empty string.")

        # Assign a value or initialize a variable
        params: Dict[str, Any] = {
            # Execute this line of logic to process the data
            "symbol": str(symbol).strip().upper(),
            # Execute this line of logic to process the data
            "contractType": contract_type.upper(),
            # Execute this line of logic to process the data
            "includeUnderlyingQuote": str(include_underlying_quote).lower(),
            # Execute this line of logic to process the data
            "strategy": strategy.upper(),
        # Execute this line of logic to process the data
        }
        # Check a conditional statement
        if strike_count is not None:
            # Assign a value or initialize a variable
            params["strikeCount"] = strike_count
        # Check a conditional statement
        if interval is not None:
            # Assign a value or initialize a variable
            params["interval"] = interval
        # Check a conditional statement
        if strike is not None:
            # Assign a value or initialize a variable
            params["strike"] = strike
        # Check a conditional statement
        if from_date:
            # Assign a value or initialize a variable
            params["fromDate"] = from_date
        # Check a conditional statement
        if to_date:
            # Assign a value or initialize a variable
            params["toDate"] = to_date

        # Assign a value or initialize a variable
        return self._execute_authenticated("/chains", params=params)

    # Define a new function or method
    def get_option_expirations(self, symbol: str) -> Dict[str, Any]:
        """
        # Execute this line of logic to process the data
        4. Option Expiration Chain: Calendar list of active expiration dates and days-to-expiration (DTE).
        # Execute this line of logic to process the data
        Parameters:
            # Execute this line of logic to process the data
            symbol: Underlying ticker symbol.
        """
        # Check a conditional statement
        if not symbol or not str(symbol).strip():
            # Raise an error to stop execution
            raise ValueError("Parameter 'symbol' must be a non-empty string.")

        # Return the final computed result to the caller
        return self._execute_authenticated(
            # Execute this line of logic to process the data
            "/expirationchain",
            # Assign a value or initialize a variable
            params={"symbol": str(symbol).strip().upper()},
        # Execute this line of logic to process the data
        )

    # Define a new function or method
    def get_instruments(self, symbol: str, projection: str = "fundamental") -> Dict[str, Any]:
        """
        # Execute this line of logic to process the data
        5. Instruments: Asset profiles, CUSIP identifiers, and fundamental balance sheet metrics.
        # Execute this line of logic to process the data
        Parameters:
            # Execute this line of logic to process the data
            symbol: Ticker symbol.
            # Execute this line of logic to process the data
            projection: 'symbol-search', 'symbol-regex', 'desc-search', or 'fundamental'.
        """
        # Check a conditional statement
        if not symbol or not str(symbol).strip():
            # Raise an error to stop execution
            raise ValueError("Parameter 'symbol' must be a non-empty string.")

        # Assign a value or initialize a variable
        params = {
            # Execute this line of logic to process the data
            "symbol": str(symbol).strip().upper(),
            # Execute this line of logic to process the data
            "projection": projection.lower(),
        # Execute this line of logic to process the data
        }
        # Assign a value or initialize a variable
        return self._execute_authenticated("/instruments", params=params)

    # Define a new function or method
    def get_movers(
        # Execute this line of logic to process the data
        self,
        # Execute this line of logic to process the data
        index_symbol: str,
        # Assign a value or initialize a variable
        sort_by: str = "VOLUME",
        # Assign a value or initialize a variable
        frequency: int = 0,
    # Execute this line of logic to process the data
    ) -> Dict[str, Any]:
        """
        # Execute this line of logic to process the data
        6. Movers: Top market movers across benchmark indices ($SPX, $COMPX, $DJI).
        # Execute this line of logic to process the data
        Parameters:
            # Execute this line of logic to process the data
            index_symbol: Index ticker (e.g., '$SPX', '$COMPX', '$DJI'). Required; no default.
            # Execute this line of logic to process the data
            sort_by: 'VOLUME', 'TRADES', 'PERCENT_CHANGE_UP', or 'PERCENT_CHANGE_DOWN'.
            # Execute this line of logic to process the data
            frequency: 0 (all day) or interval minutes (1, 5, 10, 30, 60).
        """
        # Check a conditional statement
        if not index_symbol or not str(index_symbol).strip():
            # Raise an error to stop execution
            raise ValueError("Parameter 'index_symbol' must be a non-empty string.")

        # Assign a value or initialize a variable
        valid_indices = {"$SPX", "$COMPX", "$DJI"}
        # Assign a value or initialize a variable
        target = str(index_symbol).strip().upper()
        # Check a conditional statement
        if target not in valid_indices:
            # Raise an error to stop execution
            raise ValueError(f"index_symbol must be one of {valid_indices}, got '{index_symbol}'")

        # Assign a value or initialize a variable
        params = {"sort": sort_by.upper(), "frequency": frequency}
        # Assign a value or initialize a variable
        encoded_index = urllib.parse.quote(target)
        # Assign a value or initialize a variable
        return self._execute_authenticated(f"/movers/{encoded_index}", params=params)

    # Define a new function or method
    def get_market_hours(self, markets: str = "equity,option") -> Dict[str, Any]:
        """
        # Execute this line of logic to process the data
        7. Market Hours: Trading session windows across equity, option, bond, and forex markets.
        # Execute this line of logic to process the data
        Parameters:
            # Execute this line of logic to process the data
            markets: Comma-separated list ('equity', 'option', 'bond', 'forex').
        """
        # Assign a value or initialize a variable
        return self._execute_authenticated("/markets", params={"markets": markets.lower().strip()})

    # -----------------------------------------------------------------------
    # RESOURCE MANAGEMENT
    # -----------------------------------------------------------------------
    # Define a new function or method
    def close(self) -> None:
        """Gracefully tears down underlying HTTP session adapters and connections."""
        # Start a try-catch block to handle potential errors
        try:
            # Execute this line of logic to process the data
            self.session.close()
        # Catch and handle an exception
        except Exception:
            # Execute this line of logic to process the data
            pass

    # Define a new function or method
    def __enter__(self) -> "SchwabClient":
        # Return the final computed result to the caller
        return self

    # Define a new function or method
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Execute this line of logic to process the data
        self.close()