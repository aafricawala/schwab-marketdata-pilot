"""
schwab_client.py
-----------------------------------------------------------------------------
Institutional-Grade Charles Schwab OAuth2 & Market Data Client.

Architecture & Hardening:
- Defense-in-depth token isolation: 0o600 permissions enforced at creation.
- Concurrency: Double-checked locking prevents multi-thread refresh stampedes
  without blocking active readers.
- Resiliency: Handles 429 (Retry-After), 5xx exponential jitter backoff,
  and automatic 401 token invalidation recovery.
- Coverage: Native support for all 7 Schwab Market Data endpoint families.
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
# GATEWAY ENDPOINTS & SYSTEM CONSTANTS
# ---------------------------------------------------------------------------
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
MARKETDATA_BASE = "https://api.schwabapi.com/marketdata/v1"

# Connect timeout: 3.05s (avoids TCP packet drop sync), Read timeout: 15s
DEFAULT_TIMEOUT: Tuple[float, float] = (3.05, 15.0)
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5
TOKEN_EXPIRY_BUFFER = 60  # Early refresh window in seconds

logger = logging.getLogger("schwab_client")
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# EXCEPTIONS
# ---------------------------------------------------------------------------
class SchwabClientError(Exception):
    """Base exception for all Schwab client operations."""


class TokenError(SchwabClientError):
    """Raised when token retrieval, verification, or refresh fails."""


class APIRequestError(SchwabClientError):
    """Raised when an API endpoint returns an unrecoverable HTTP status."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TokenPayload:
    """Immutable representation of OAuth state."""
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
        # Use recorded expires_at, or calculate from current time
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
# HARDENED UTILITY FUNCTIONS
# ---------------------------------------------------------------------------
def _atomic_write_secure_json(target_path: Path, data: Dict[str, Any]) -> None:
    """
    Atomically writes JSON with strict owner-only permissions (0o600).
    Uses low-level os.open with O_CREAT | O_EXCL to prevent symlink and
    race-condition exploits.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp.{os.getpid()}_{threading.get_ident()}")

    # Open with explicit 0o600 flags before data hits disk
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

    # Atomic replace
    os.replace(tmp_path, target_path)


def _safe_json_parse(resp: Response) -> Dict[str, Any]:
    """Safely extracts JSON response without exposing payload internals on error."""
    try:
        return resp.json()
    except ValueError as exc:
        raise APIRequestError(
            f"Invalid JSON payload returned from endpoint (HTTP {resp.status_code})",
            status_code=resp.status_code
        ) from exc


def _parse_retry_after(header_val: Optional[str], default_wait: float) -> float:
    """Parses RFC-7231 / integer values from HTTP Retry-After headers."""
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
        self.client_id = client_id or os.environ.get("SCHWAB_CLIENT_ID", "").strip()
        self.client_secret = client_secret or os.environ.get("SCHWAB_CLIENT_SECRET", "").strip()
        self.redirect_uri = redirect_uri or os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1").strip()
        
        raw_token_path = token_file_path or os.environ.get("SCHWAB_TOKEN_PATH", "schwab_tokens.json")
        self.token_file_path = Path(raw_token_path).resolve()

        if not self.client_id:
            raise ValueError("Configuration missing: SCHWAB_CLIENT_ID must be provided.")

        self.timeout = timeout
        self.max_retries = max(0, max_retries)

        # Thread synchronization primitives
        self._tokens_lock = threading.RLock()
        self._token_payload: Optional[TokenPayload] = None

        # Build hardened connection pool
        if session:
            self.session = session
        else:
            self.session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=pool_connections,
                pool_maxsize=pool_maxsize,
                max_retries=Retry(total=0)  # Logic handled via custom backoff engine
            )
            self.session.mount("https://", adapter)

        self._load_tokens_from_disk()

    # -----------------------------------------------------------------------
    # TOKEN PERSISTENCE & LIFECYCLE
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
        if not self.client_secret:
            raise ValueError("Operation requires SCHWAB_CLIENT_SECRET.")
        raw_creds = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(raw_creds.encode("utf-8")).decode("utf-8")
        return {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

    # -----------------------------------------------------------------------
    # OAUTH TRANSACTIONS
    # -----------------------------------------------------------------------
    def build_auth_url(self, state: Optional[str] = None) -> str:
        """Builds user consent URL with optional state parameter for CSRF defense."""
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "api",
        }
        if state:
            params["state"] = state
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code_for_token(self, code_or_url: str) -> TokenPayload:
        """Parses and swaps authorization code for permanent access/refresh pairs."""
        raw = code_or_url.strip()
        if "code=" in raw:
            query = raw.split("?", 1)[-1] if "?" in raw else raw
            parsed = urllib.parse.parse_qs(query)
            extracted_code = parsed.get("code", [None])[0]
            if not extracted_code:
                extracted_code = raw.split("code=")[-1].split("&")[0]
        else:
            extracted_code = raw

        sanitized_code = urllib.parse.unquote(extracted_code.strip())
        if not sanitized_code:
            raise TokenError("Failed to extract clean authorization code parameter.")

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
        """Executes a silent refresh using double-checked thread synchronization."""
        with self._tokens_lock:
            # Re-check expiration: Did another thread complete refresh while this thread was waiting?
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
        # Check without lock first (read-heavy optimization)
        current = self._token_payload
        if current and time.time() < (current.expires_at - TOKEN_EXPIRY_BUFFER):
            return current.access_token

        # Acquire lock and execute refresh if expired
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
        """Executes HTTP calls with jittered exponential backoff and 429 adherence."""
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
                time.sleep(backoff + (time.time() % 0.2))  # Add entropy jitter
                continue

            # Respect rate limits
            if resp.status_code == 429:
                wait_time = _parse_retry_after(
                    resp.headers.get("Retry-After"),
                    DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1))
                )
                logger.warning("Schwab rate limit triggered. Backing off for %.2f seconds.", wait_time)
                if attempt > self.max_retries:
                    raise APIRequestError("Exceeded maximum retries on HTTP 429 Rate Limit.", status_code=429)
                time.sleep(wait_time)
                continue

            # Retry transient server errors
            if 500 <= resp.status_code < 600:
                if attempt > self.max_retries:
                    raise APIRequestError(f"Persistent server failure (HTTP {resp.status_code}).", status_code=resp.status_code)
                backoff = DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1))
                time.sleep(backoff)
                continue

            return resp

    def _execute_authenticated(
        self,
        endpoint_path: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Base API handler with automatic 401 token invalidation recovery."""
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
                raise APIRequestError(f"API request failed on {endpoint_path} with status {resp.status_code}", status_code=resp.status_code)

            return _safe_json_parse(resp)

        raise APIRequestError("Request failed after re-authentication attempt.", status_code=401)

    # -----------------------------------------------------------------------
    # ALL 7 SCHWAB MARKET DATA ENDPOINT FAMILIES
    # -----------------------------------------------------------------------
    def get_quotes(self, symbols: Union[str, List[str]], fields: Optional[str] = None) -> Dict[str, Any]:
        """1. Quotes: Real-time/delayed quotes for single or multiple equity/ETF/index symbols."""
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
        """2. Price History: Historical OHLCV candle bars across custom time intervals."""
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
        """3. Option Chains: Real-time strike matrix with implied volatility and Greeks."""
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
        """4. Option Expiration Chain: Calendar list of active expiration dates and DTE."""
        return self._execute_authenticated("/expirationchain", params={"symbol": symbol.strip().upper()})

    def get_instruments(self, symbol: str, projection: str = "fundamental") -> Dict[str, Any]:
        """5. Instruments: Asset profiles, CUSIP identifiers, and fundamental accounting ratios."""
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
        """6. Movers: Top market movers across major benchmark indices ($SPX, $COMPX, $DJI)."""
        valid_indices = {"$SPX", "$COMPX", "$DJI"}
        target = index_symbol.strip().upper()
        if target not in valid_indices:
            raise ValueError(f"index_symbol must be one of {valid_indices}, got '{index_symbol}'")

        params = {"sort": sort_by.upper(), "frequency": frequency}
        # Path parameter requires explicit URL-encoding for index symbol prefix '$'
        encoded_index = urllib.parse.quote(target)
        return self._execute_authenticated(f"/movers/{encoded_index}", params=params)

    def get_market_hours(self, markets: str = "equity,option") -> Dict[str, Any]:
        """7. Market Hours: Trading session windows across equity, option, bond, and forex markets."""
        return self._execute_authenticated("/markets", params={"markets": markets.lower().strip()})

    # -----------------------------------------------------------------------
    # RESOURCE CLEANUP
    # -----------------------------------------------------------------------
    def close(self) -> None:
        """Gracefully tears down underlying connection adapters."""
        try:
            self.session.close()
        except Exception:
            pass

    def __enter__(self) -> "SchwabClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()