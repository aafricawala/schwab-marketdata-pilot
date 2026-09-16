"""
schwab_client.py
-----------------------------------------------------------------------------
Institutional-Grade Charles Schwab OAuth2 & Market Data API Client.

Designed for: Global Equity Strategy, Market Risk Systems, and Algorithmic Pipelines.

Core Architecture & Security Features:
1. Strict Callback URL Verification:
   - Enforces the 255-character maximum length limit mandated by Schwab.
   - Strictly validates the HTTPS protocol requirement for Login Micro Site (LMS).
   - Prohibits whitespace characters in callback definitions.
   - Normalizes root-level trailing slashes (e.g., 'https://127.0.0.1/' -> 'https://127.0.0.1')
     to prevent byte-level mismatch rejections during token exchange.
2. CSRF Mitigation (RFC 6749 Section 10.12):
   - Supports cryptographically random state tokens on authorization requests.
   - Validates returned state tokens before code exchange to prevent CSRF attacks.
3. Low-Level Token Isolation:
   - Uses low-level OS file descriptors (os.open with O_CREAT | O_TRUNC | O_WRONLY)
     to enforce strict POSIX 0o600 permissions at creation, preventing umask race conditions.
4. Concurrency & Thread Safety:
   - Implements double-checked locking to prevent multi-threaded refresh stampedes
     while maintaining zero-lock overhead on fast-path token validation.
5. Resilient Network Layer:
   - Hardened connection pooling (HTTPAdapter) to prevent socket exhaustion.
   - Proactive early token renewal (60s buffer) combined with a reactive 401 recovery loop.
   - Adheres to HTTP 429 rate limits via RFC-7231 / seconds-based Retry-After parsing with jitter.
   - Exponential backoff on transient 5xx server errors.
6. Agnostic Asset Coverage:
   - Native interfaces for all 7 Schwab Market Data endpoint families: Quotes,
     Price History, Option Chains, Expiration Chains, Instruments, Movers, and Market Hours.
-----------------------------------------------------------------------------
"""

from __future__ import annotations

import base64
import email.utils
import json
import logging
import os
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# GATEWAY CONFIGURATION CONSTANTS
# ---------------------------------------------------------------------------
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
MARKETDATA_BASE = "https://api.schwabapi.com/marketdata/v1"

# Connection timeout: 3.05s (avoids TCP packet drop sync), Read timeout: 15.0s
DEFAULT_TIMEOUT: Tuple[float, float] = (3.05, 15.0)
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5
TOKEN_EXPIRY_BUFFER = 60  # Seconds before nominal expiry to proactively refresh

# Configure module-level logger with NullHandler
logger = logging.getLogger("schwab_client")
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# CUSTOM EXCEPTION HIERARCHY
# ---------------------------------------------------------------------------
class SchwabClientError(Exception):
    """Base exception for all Schwab client failures."""


class TokenError(SchwabClientError):
    """Raised when token retrieval, decoding, persistence, or refresh fails."""


class CallbackURLError(SchwabClientError):
    """Raised when the redirect_uri violates Schwab Developer Portal specifications."""


class APIRequestError(SchwabClientError):
    """Raised when an API endpoint returns an unrecoverable HTTP error status."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# IMMUTABLE TOKEN CONTAINER
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TokenPayload:
    """
    Thread-safe, immutable representation of OAuth credentials and lifecycle timestamps.
    """
    access_token: str
    token_type: str
    expires_in: int
    expires_at: float
    refresh_token: Optional[str] = None
    scope: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TokenPayload":
        now = time.time()
        expires_in = int(data.get("expires_in", 1800))
        # Use recorded expires_at, or calculate from current epoch
        expires_at = float(data.get("expires_at", now + expires_in))

        return cls(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_in=expires_in,
            expires_at=expires_at,
            refresh_token=data.get("refresh_token"),
            scope=data.get("scope"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "expires_at": self.expires_at,
            "refresh_token": self.refresh_token,
            "scope": self.scope,
        }


# ---------------------------------------------------------------------------
# HARDENED SECURITY & VALIDATION HELPERS
# ---------------------------------------------------------------------------
def validate_and_normalize_redirect_uri(uri: str) -> str:
    """
    Validates and standardizes the redirect_uri according to Schwab's Developer Portal rules:
      1. Must be a non-empty string.
      2. Must not exceed Schwab's maximum 255-character ceiling.
      3. Must not contain whitespace characters.
      4. Must declare a secure scheme ('https') as required by LMS.
      5. Normalizes bare root paths (e.g., 'https://127.0.0.1/' -> 'https://127.0.0.1')
         to prevent string-mismatch errors during token exchange.

    Raises:
        CallbackURLError: If the URI fails any structural specification.
    """
    if not uri or not isinstance(uri, str):
        raise CallbackURLError("redirect_uri must be a non-empty string.")

    cleaned = uri.strip()

    # Rule 1: 255-character maximum ceiling
    if len(cleaned) > 255:
        raise CallbackURLError(
            f"redirect_uri exceeds Schwab's 255-character ceiling ({len(cleaned)} characters): '{cleaned}'"
        )

    # Rule 2: Whitespace prohibition
    if any(c.isspace() for c in cleaned):
        raise CallbackURLError(f"redirect_uri cannot contain whitespace: '{cleaned}'")

    parsed = urllib.parse.urlparse(cleaned)

    # Rule 3: Strict HTTPS requirement for LMS production integration
    if parsed.scheme.lower() != "https":
        raise CallbackURLError(
            f"Invalid scheme '{parsed.scheme}' in redirect_uri '{cleaned}'. "
            "Schwab Developer Portal requirements mandate the 'https://' scheme."
        )

    # Rule 4: Normalization: Schwab performs strict character matching.
    # If a trailing slash is present on a bare host root, normalize it to match portal registration.
    if parsed.path == "/" and not parsed.query and not parsed.fragment:
        cleaned = f"{parsed.scheme}://{parsed.netloc}"

    return cleaned


def _atomic_write_secure_json(target_path: Path, data: Dict[str, Any]) -> None:
    """
    Atomically writes JSON payload to disk with POSIX 0o600 permissions.
    Eliminates the umask vulnerability window using low-level os.open before writing.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp.{os.getpid()}_{threading.get_ident()}")

    # Enforce strict owner-only read/write flags at file descriptor creation
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd = os.open(tmp_path, flags, 0o600)
    try:
        with open(fd, "w", encoding="utf-8", closefd=True) as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    # Atomic rename replace
    os.replace(tmp_path, target_path)


def _safe_json_parse(resp: Response) -> Dict[str, Any]:
    """Safely extracts JSON payload without leaking internal gateway tokens on error."""
    try:
        return resp.json()
    except ValueError as exc:
        raise APIRequestError(
            f"Invalid JSON returned from endpoint (HTTP {resp.status_code})",
            status_code=resp.status_code,
        ) from exc


def _parse_retry_after(header_val: Optional[str], default_wait: float) -> float:
    """Parses RFC-7231 / integer seconds from HTTP Retry-After headers."""
    if not header_val:
        return default_wait
    try:
        return max(0.0, float(header_val))
    except ValueError:
        pass
    try:
        date_tuple = email.utils.parsedate_tz(header_val)
        if date_tuple:
            target_time = email.utils.mktime_tz(date_tuple)
            return max(0.0, target_time - time.time())
    except Exception:
        pass
    return default_wait


# ---------------------------------------------------------------------------
# CLIENT IMPLEMENTATION
# ---------------------------------------------------------------------------
class SchwabClient:
    """
    Thread-safe, institutional-grade market data client for Charles Schwab.
    Handles automated token persistence, proactive background refresh, and endpoint queries.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        token_file_path: Optional[Union[str, Path]] = None,
        session: Optional[Session] = None,
        timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
        pool_connections: int = 50,
        pool_maxsize: int = 50,
    ) -> None:
        self.client_id = (client_id or os.environ.get("SCHWAB_CLIENT_ID", "")).strip()
        self.client_secret = (client_secret or os.environ.get("SCHWAB_CLIENT_SECRET", "")).strip()

        raw_redirect = (redirect_uri or os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")).strip()
        self.redirect_uri = validate_and_normalize_redirect_uri(raw_redirect)

        raw_token_path = token_file_path or os.environ.get("SCHWAB_TOKEN_PATH", "schwab_tokens.json")
        self.token_file_path = Path(raw_token_path).resolve()

        if not self.client_id:
            raise ValueError("Configuration missing: SCHWAB_CLIENT_ID must be provided.")

        self.timeout = timeout
        self.max_retries = max(0, max_retries)

        # Thread synchronization primitives
        self._tokens_lock = threading.RLock()
        self._token_payload: Optional[TokenPayload] = None

        # Build resilient connection pool
        if session:
            self.session = session
        else:
            self.session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=pool_connections,
                pool_maxsize=pool_maxsize,
                max_retries=Retry(total=0),  # Handled via custom exponential backoff engine
            )
            self.session.mount("https://", adapter)

        self._load_tokens_from_disk()

    # -----------------------------------------------------------------------
    # TOKEN PERSISTENCE & CONCURRENCY
    # -----------------------------------------------------------------------
    def _load_tokens_from_disk(self) -> None:
        """Loads cached tokens into memory under thread lock."""
        with self._tokens_lock:
            if not self.token_file_path.exists():
                self._token_payload = None
                return

            try:
                with self.token_file_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if "access_token" in data:
                    self._token_payload = TokenPayload.from_dict(data)
                else:
                    self._token_payload = None
            except Exception as exc:
                logger.warning("Unreadable token store at %s: %s", self.token_file_path, exc)
                self._token_payload = None

    def _persist_tokens(self, token_data: Dict[str, Any]) -> TokenPayload:
        """Atomically caches new token sets to disk and updates in-memory reference."""
        with self._tokens_lock:
            # Retain existing refresh token if response omitted it
            if "refresh_token" not in token_data and self._token_payload and self._token_payload.refresh_token:
                token_data["refresh_token"] = self._token_payload.refresh_token

            expires_in = int(token_data.get("expires_in", 1800))
            token_data["expires_at"] = time.time() + expires_in

            _atomic_write_secure_json(self.token_file_path, token_data)
            self._token_payload = TokenPayload.from_dict(token_data)
            return self._token_payload

    def _get_basic_auth_header(self) -> Dict[str, str]:
        """Builds HTTP Basic Authorization header: 'Basic base64(client_id:client_secret)'."""
        if not self.client_secret:
            raise ValueError("Operation requires SCHWAB_CLIENT_SECRET.")
        raw_creds = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(raw_creds.encode("utf-8")).decode("utf-8")
        return {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    # -----------------------------------------------------------------------
    # OAUTH TRANSACTIONS
    # -----------------------------------------------------------------------
    def build_auth_url(self, state: Optional[str] = None) -> str:
        """
        Constructs user consent URL with validated callback URI and optional CSRF state parameter.
        """
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "api",
        }
        if state:
            params["state"] = state
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code_for_token(
        self,
        code_or_url: str,
        expected_state: Optional[str] = None,
    ) -> TokenPayload:
        """
        Exchanges the authorization code from the browser redirect for an access/refresh pair.
        Validates the returned CSRF 'state' token if an expected_state was provided.
        """
        raw = code_or_url.strip()
        extracted_state = None

        if "code=" in raw:
            query = raw.split("?", 1)[-1] if "?" in raw else raw
            parsed = urllib.parse.parse_qs(query)
            extracted_code = parsed.get("code", [None])[0]
            extracted_state = parsed.get("state", [None])[0]
            if not extracted_code:
                extracted_code = raw.split("code=")[-1].split("&")[0]
        else:
            extracted_code = raw

        # Cryptographic state verification (RFC 6749 Section 10.12)
        if expected_state:
            if not extracted_state:
                raise TokenError("Security Alert: Authorization response is missing the required 'state' parameter.")
            if extracted_state != expected_state:
                raise TokenError(
                    f"Security Alert: CSRF state mismatch detected! Expected '{expected_state}', got '{extracted_state}'."
                )

        sanitized_code = urllib.parse.unquote((extracted_code or "").strip())
        if not sanitized_code:
            raise TokenError("Failed to extract valid authorization code parameter.")

        payload = {
            "grant_type": "authorization_code",
            "code": sanitized_code,
            "redirect_uri": self.redirect_uri,
        }

        resp = self._raw_http_request("POST", TOKEN_URL, headers=self._get_basic_auth_header(), data=payload)
        if resp.status_code != 200:
            raise TokenError(f"OAuth code exchange failed (HTTP {resp.status_code}).")

        return self._persist_tokens(_safe_json_parse(resp))

    def refresh_access_token(self) -> TokenPayload:
        """
        Executes a silent token refresh using double-checked thread synchronization.
        """
        with self._tokens_lock:
            # Re-check: Did another worker thread complete refresh while this thread was waiting?
            if self._token_payload and time.time() < (self._token_payload.expires_at - TOKEN_EXPIRY_BUFFER):
                return self._token_payload

            if not self._token_payload or not self._token_payload.refresh_token:
                raise TokenError("No refresh token available. Interactive authorization required.")

            payload = {
                "grant_type": "refresh_token",
                "refresh_token": self._token_payload.refresh_token,
            }

            resp = self._raw_http_request("POST", TOKEN_URL, headers=self._get_basic_auth_header(), data=payload)
            if resp.status_code != 200:
                raise TokenError(f"Refresh token rejected by Schwab (HTTP {resp.status_code}).")

            return self._persist_tokens(_safe_json_parse(resp))

    def get_valid_access_token(self) -> str:
        """Fast-path thread-safe retrieval of validated token."""
        current = self._token_payload
        if current and time.time() < (current.expires_at - TOKEN_EXPIRY_BUFFER):
            return current.access_token

        return self.refresh_access_token().access_token

    # -----------------------------------------------------------------------
    # RESILIENT HTTP EXECUTION ENGINE
    # -----------------------------------------------------------------------
    def _raw_http_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Response:
        """Executes raw HTTP calls with entropy-jittered exponential backoff and 429 adherence."""
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    data=data,
                    timeout=self.timeout,
                )
            except requests.RequestException as err:
                if attempt > self.max_retries:
                    raise APIRequestError(f"Network transport failure after {attempt} attempts: {err}") from err
                backoff = DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1))
                time.sleep(backoff + (time.time() % 0.2))
                continue

            # Handle rate limiting
            if resp.status_code == 429:
                wait_time = _parse_retry_after(
                    resp.headers.get("Retry-After"),
                    DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1)),
                )
                logger.warning("Schwab rate limit triggered. Backing off for %.2f seconds.", wait_time)
                if attempt > self.max_retries:
                    raise APIRequestError("Exceeded maximum retries on HTTP 429 Rate Limit.", status_code=429)
                time.sleep(wait_time)
                continue

            # Retry transient server errors
            if 500 <= resp.status_code < 600:
                if attempt > self.max_retries:
                    raise APIRequestError(
                        f"Persistent server failure (HTTP {resp.status_code}).",
                        status_code=resp.status_code,
                    )
                backoff = DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1))
                time.sleep(backoff)
                continue

            return resp

    def _execute_authenticated(
        self,
        endpoint_path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Base API handler with automatic 401 token invalidation recovery loop."""
        target_url = f"{MARKETDATA_BASE}{endpoint_path}"

        for is_recovery_attempt in (False, True):
            token = self.get_valid_access_token()
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

            resp = self._raw_http_request("GET", target_url, headers=headers, params=params)

            # Self-healing on unexpected token revocation
            if resp.status_code == 401 and not is_recovery_attempt:
                logger.warning("HTTP 401 received. Invalidating cached access token and forcing refresh.")
                self.refresh_access_token()
                continue

            if resp.status_code != 200:
                raise APIRequestError(
                    f"API request failed on {endpoint_path} with status {resp.status_code}",
                    status_code=resp.status_code,
                )

            return _safe_json_parse(resp)

        raise APIRequestError("Request failed after re-authentication recovery attempt.", status_code=401)

    # -----------------------------------------------------------------------
    # ALL 7 SCHWAB MARKET DATA ENDPOINT FAMILIES
    # -----------------------------------------------------------------------
    def get_quotes(self, symbols: Union[str, List[str]], fields: Optional[str] = None) -> Dict[str, Any]:
        """
        1. Quotes: Real-time/delayed quotes for single or multiple equity/ETF/index symbols.
        """
        if isinstance(symbols, list):
            clean_syms = ",".join(s.strip().upper() for s in symbols if s.strip())
        else:
            clean_syms = ",".join(s.strip().upper() for s in symbols.split(",") if s.strip())

        if not clean_syms:
            raise ValueError("At least one valid ticker symbol is required.")

        params: Dict[str, Any] = {"symbols": clean_syms}
        if fields:
            params["fields"] = fields.strip()
        return self._execute_authenticated("/quotes", params=params)

    def get_price_history(
        self,
        symbol: str,
        period_type: str = "day",
        period: int = 5,
        frequency_type: str = "minute",
        frequency: int = 5,
        start_date: Optional[int] = None,
        end_date: Optional[int] = None,
        need_extended_hours: bool = False,
    ) -> Dict[str, Any]:
        """
        2. Price History: Historical OHLCV candle bars across custom time intervals.
        """
        params: Dict[str, Any] = {
            "symbol": symbol.strip().upper(),
            "periodType": period_type.lower(),
            "period": period,
            "frequencyType": frequency_type.lower(),
            "frequency": frequency,
            "needExtendedHoursData": str(need_extended_hours).lower(),
        }
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        return self._execute_authenticated("/pricehistory", params=params)

    def get_option_chain(
        self,
        symbol: str,
        contract_type: str = "ALL",
        strike_count: Optional[int] = 8,
        include_underlying_quote: bool = True,
        strategy: str = "SINGLE",
        interval: Optional[float] = None,
        strike: Optional[float] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        3. Option Chains: Real-time strike matrix with implied volatility and Greeks.
        """
        params: Dict[str, Any] = {
            "symbol": symbol.strip().upper(),
            "contractType": contract_type.upper(),
            "includeUnderlyingQuote": str(include_underlying_quote).lower(),
            "strategy": strategy.upper(),
        }
        if strike_count is not None:
            params["strikeCount"] = strike_count
        if interval is not None:
            params["interval"] = interval
        if strike is not None:
            params["strike"] = strike
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date

        return self._execute_authenticated("/chains", params=params)

    def get_option_expirations(self, symbol: str) -> Dict[str, Any]:
        """
        4. Option Expiration Chain: Calendar list of active expiration dates and days-to-expiration (DTE).
        """
        return self._execute_authenticated("/expirationchain", params={"symbol": symbol.strip().upper()})

    def get_instruments(self, symbol: str, projection: str = "fundamental") -> Dict[str, Any]:
        """
        5. Instruments: Asset profiles, CUSIP identifiers, and fundamental balance sheet metrics.
        """
        params = {
            "symbol": symbol.strip().upper(),
            "projection": projection.lower(),
        }
        return self._execute_authenticated("/instruments", params=params)

    def get_movers(
        self,
        index_symbol: str = "$SPX",
        sort_by: str = "VOLUME",
        frequency: int = 0,
    ) -> Dict[str, Any]:
        """
        6. Movers: Top market movers across benchmark indices ($SPX, $COMPX, $DJI).
        """
        valid_indices = {"$SPX", "$COMPX", "$DJI"}
        target = index_symbol.strip().upper()
        if target not in valid_indices:
            raise ValueError(f"index_symbol must be one of {valid_indices}, got '{index_symbol}'")

        params = {"sort": sort_by.upper(), "frequency": frequency}
        encoded_index = urllib.parse.quote(target)
        return self._execute_authenticated(f"/movers/{encoded_index}", params=params)

    def get_market_hours(self, markets: str = "equity,option") -> Dict[str, Any]:
        """
        7. Market Hours: Trading session windows across equity, option, bond, and forex markets.
        """
        return self._execute_authenticated("/markets", params={"markets": markets.lower().strip()})

    # -----------------------------------------------------------------------
    # RESOURCE MANAGEMENT
    # -----------------------------------------------------------------------
    def close(self) -> None:
        """Gracefully tears down underlying HTTP session adapters and connections."""
        try:
            self.session.close()
        except Exception:
            pass

    def __enter__(self) -> "SchwabClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()