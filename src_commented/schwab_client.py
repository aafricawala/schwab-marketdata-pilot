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
schwab_client.py
"""

# Explain this line: from __future__ import annotations...
# Line: from __future__ import annotations
from __future__ import annotations

# Explain this line: import base64...
# Line: import base64
import base64
# Explain this line: import email.utils...
# Line: import email.utils
import email.utils
# Explain this line: import json...
# Line: import json
import json
# Explain this line: import logging...
# Line: import logging
import logging
# Explain this line: import os...
# Line: import os
import os
# Explain this line: import threading...
# Line: import threading
import threading
# Explain this line: import time...
# Line: import time
import time
# Explain this line: import urllib.parse...
# Line: import urllib.parse
import urllib.parse
# Explain this line: from dataclasses import dataclass...
# Line: from dataclasses import dataclass
from dataclasses import dataclass
# Explain this line: from pathlib import Path...
# Line: from pathlib import Path
from pathlib import Path
# Explain this line: from typing import Any, Dict, List, Opti...
# Line: from typing import Any, Dict, List, Optional, Tupl
from typing import Any, Dict, List, Optional, Tuple, Union

# Explain this line: import requests...
# Line: import requests
import requests
# Explain this line: from requests import Response, Session...
# Line: from requests import Response, Session
from requests import Response, Session
# Explain this line: from requests.adapters import HTTPAdapte...
# Line: from requests.adapters import HTTPAdapter
from requests.adapters import HTTPAdapter
# Explain this line: from urllib3.util.retry import Retry...
# Line: from urllib3.util.retry import Retry
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# GATEWAY CONFIGURATION CONSTANTS
# ---------------------------------------------------------------------------
# Explain this line: AUTH_URL = "https://api.schwabapi.com/v1...
# Line: AUTH_URL = "https://api.schwabapi.com/v1/oauth/aut
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
# Explain this line: TOKEN_URL = "https://api.schwabapi.com/v...
# Line: TOKEN_URL = "https://api.schwabapi.com/v1/oauth/to
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
# Explain this line: MARKETDATA_BASE = "https://api.schwabapi...
# Line: MARKETDATA_BASE = "https://api.schwabapi.com/marke
MARKETDATA_BASE = "https://api.schwabapi.com/marketdata/v1"

# Connect timeout: 3.05s (prevents TCP syn drop hang), Read timeout: 15.0s
# Explain this line: DEFAULT_TIMEOUT: Tuple[float, float] = (...
# Line: DEFAULT_TIMEOUT: Tuple[float, float] = (3.05, 15.0
DEFAULT_TIMEOUT: Tuple[float, float] = (3.05, 15.0)
# Explain this line: DEFAULT_RETRIES = 3...
# Line: DEFAULT_RETRIES = 3
DEFAULT_RETRIES = 3
# Explain this line: DEFAULT_BACKOFF_FACTOR = 0.5...
# Line: DEFAULT_BACKOFF_FACTOR = 0.5
DEFAULT_BACKOFF_FACTOR = 0.5
# Explain this line: TOKEN_EXPIRY_BUFFER = 60  # Seconds befo...
# Line: TOKEN_EXPIRY_BUFFER = 60  # Seconds before nominal
TOKEN_EXPIRY_BUFFER = 60  # Seconds before nominal expiry to proactively refresh

# Explain this line: logger = logging.getLogger("schwab_clien...
# Line: logger = logging.getLogger("schwab_client")
logger = logging.getLogger("schwab_client")
# Explain this line: logger.addHandler(logging.NullHandler())...
# Line: logger.addHandler(logging.NullHandler())
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# CUSTOM EXCEPTION HIERARCHY
# ---------------------------------------------------------------------------
# Explain this line: class SchwabClientError(Exception):...
# Line: class SchwabClientError(Exception):
class SchwabClientError(Exception):
    """Base exception for all Schwab client failures."""


# Explain this line: class TokenError(SchwabClientError):...
# Line: class TokenError(SchwabClientError):
class TokenError(SchwabClientError):
    """Raised when token retrieval, decoding, persistence, or refresh fails."""


# Explain this line: class CallbackURLError(SchwabClientError...
# Line: class CallbackURLError(SchwabClientError):
class CallbackURLError(SchwabClientError):
    """Raised when the redirect_uri violates Schwab Developer Portal specifications."""


# Explain this line: class APIRequestError(SchwabClientError)...
# Line: class APIRequestError(SchwabClientError):
class APIRequestError(SchwabClientError):
    """
    Raised when an API endpoint returns an unrecoverable HTTP status.
    Carries the HTTP status code, Schwab Correlation ID, and structured error details.
    """

    # Explain this line: def __init__(...
    # Line: def __init__(
    def __init__(
        # Explain this line: self,...
        # Line: self,
        self,
        # Explain this line: message: str,...
        # Line: message: str,
        message: str,
        # Explain this line: status_code: Optional[int] = None,...
        # Line: status_code: Optional[int] = None,
        status_code: Optional[int] = None,
        # Explain this line: correl_id: Optional[str] = None,...
        # Line: correl_id: Optional[str] = None,
        correl_id: Optional[str] = None,
        # Explain this line: error_details: Optional[str] = None,...
        # Line: error_details: Optional[str] = None,
        error_details: Optional[str] = None,
    # Explain this line: ) -> None:...
    # Line: ) -> None:
    ) -> None:
        # Explain this line: super().__init__(message)...
        # Line: super().__init__(message)
        super().__init__(message)
        # Explain this line: self.status_code = status_code...
        # Line: self.status_code = status_code
        self.status_code = status_code
        # Explain this line: self.correl_id = correl_id or "UNKNOWN"...
        # Line: self.correl_id = correl_id or "UNKNOWN"
        self.correl_id = correl_id or "UNKNOWN"
        # Explain this line: self.error_details = error_details or ""...
        # Line: self.error_details = error_details or ""
        self.error_details = error_details or ""


# ---------------------------------------------------------------------------
# IMMUTABLE TOKEN CONTAINER
# ---------------------------------------------------------------------------
# Explain this line: @dataclass(frozen=True)...
# Line: @dataclass(frozen=True)
@dataclass(frozen=True)
# Explain this line: class TokenPayload:...
# Line: class TokenPayload:
class TokenPayload:
    """Thread-safe, immutable representation of OAuth credentials and lifecycle timestamps."""
    # Explain this line: access_token: str...
    # Line: access_token: str
    access_token: str
    # Explain this line: token_type: str...
    # Line: token_type: str
    token_type: str
    # Explain this line: expires_in: int...
    # Line: expires_in: int
    expires_in: int
    # Explain this line: expires_at: float...
    # Line: expires_at: float
    expires_at: float
    # Explain this line: refresh_token: Optional[str] = None...
    # Line: refresh_token: Optional[str] = None
    refresh_token: Optional[str] = None
    # Explain this line: scope: Optional[str] = None...
    # Line: scope: Optional[str] = None
    scope: Optional[str] = None

    # Explain this line: @classmethod...
    # Line: @classmethod
    @classmethod
    # Explain this line: def from_dict(cls, data: Dict[str, Any])...
    # Line: def from_dict(cls, data: Dict[str, Any]) -> "Token
    def from_dict(cls, data: Dict[str, Any]) -> "TokenPayload":
        # Explain this line: now = time.time()...
        # Line: now = time.time()
        now = time.time()
        # Explain this line: expires_in = int(data.get("expires_in", ...
        # Line: expires_in = int(data.get("expires_in", 1800))
        expires_in = int(data.get("expires_in", 1800))
        # Explain this line: expires_at = float(data.get("expires_at"...
        # Line: expires_at = float(data.get("expires_at", now + ex
        expires_at = float(data.get("expires_at", now + expires_in))

        # Explain this line: return cls(...
        # Line: return cls(
        return cls(
            # Explain this line: access_token=data["access_token"],...
            # Line: access_token=data["access_token"],
            access_token=data["access_token"],
            # Explain this line: token_type=data.get("token_type", "Beare...
            # Line: token_type=data.get("token_type", "Bearer"),
            token_type=data.get("token_type", "Bearer"),
            # Explain this line: expires_in=expires_in,...
            # Line: expires_in=expires_in,
            expires_in=expires_in,
            # Explain this line: expires_at=expires_at,...
            # Line: expires_at=expires_at,
            expires_at=expires_at,
            # Explain this line: refresh_token=data.get("refresh_token"),...
            # Line: refresh_token=data.get("refresh_token"),
            refresh_token=data.get("refresh_token"),
            # Explain this line: scope=data.get("scope"),...
            # Line: scope=data.get("scope"),
            scope=data.get("scope"),
        # Explain this line: )...
        # Line: )
        )

    # Explain this line: def to_dict(self) -> Dict[str, Any]:...
    # Line: def to_dict(self) -> Dict[str, Any]:
    def to_dict(self) -> Dict[str, Any]:
        # Explain this line: return {...
        # Line: return {
        return {
            # Explain this line: "access_token": self.access_token,...
            # Line: "access_token": self.access_token,
            "access_token": self.access_token,
            # Explain this line: "token_type": self.token_type,...
            # Line: "token_type": self.token_type,
            "token_type": self.token_type,
            # Explain this line: "expires_in": self.expires_in,...
            # Line: "expires_in": self.expires_in,
            "expires_in": self.expires_in,
            # Explain this line: "expires_at": self.expires_at,...
            # Line: "expires_at": self.expires_at,
            "expires_at": self.expires_at,
            # Explain this line: "refresh_token": self.refresh_token,...
            # Line: "refresh_token": self.refresh_token,
            "refresh_token": self.refresh_token,
            # Explain this line: "scope": self.scope,...
            # Line: "scope": self.scope,
            "scope": self.scope,
        # Explain this line: }...
        # Line: }
        }


# ---------------------------------------------------------------------------
# HARDENED SECURITY & VALIDATION HELPERS
# ---------------------------------------------------------------------------
# Explain this line: def validate_and_normalize_redirect_uri(...
# Line: def validate_and_normalize_redirect_uri(uri: str)
def validate_and_normalize_redirect_uri(uri: str) -> str:
    """
    Validates and standardizes redirect_uri according to Schwab's Developer Portal rules:
      1. Must be a non-empty string.
      2. Must not exceed Schwab's maximum 255-character ceiling.
      3. Must not contain whitespace characters.
      4. Must declare a secure scheme ('https') as required by LMS.
      5. Normalizes bare root paths (e.g., 'https://127.0.0.1/' -> 'https://127.0.0.1')
         to prevent string-mismatch errors during token exchange.
    """
    # Explain this line: if not uri or not isinstance(uri, str):...
    # Line: if not uri or not isinstance(uri, str):
    if not uri or not isinstance(uri, str):
        # Explain this line: raise CallbackURLError("redirect_uri mus...
        # Line: raise CallbackURLError("redirect_uri must be a non
        raise CallbackURLError("redirect_uri must be a non-empty string.")

    # Explain this line: cleaned = uri.strip()...
    # Line: cleaned = uri.strip()
    cleaned = uri.strip()

    # Explain this line: if len(cleaned) > 255:...
    # Line: if len(cleaned) > 255:
    if len(cleaned) > 255:
        # Explain this line: raise CallbackURLError(...
        # Line: raise CallbackURLError(
        raise CallbackURLError(
            # Explain this line: f"redirect_uri exceeds Schwab's 255-char...
            # Line: f"redirect_uri exceeds Schwab's 255-character ceil
            f"redirect_uri exceeds Schwab's 255-character ceiling ({len(cleaned)} chars): '{cleaned}'"
        # Explain this line: )...
        # Line: )
        )

    # Explain this line: if any(c.isspace() for c in cleaned):...
    # Line: if any(c.isspace() for c in cleaned):
    if any(c.isspace() for c in cleaned):
        # Explain this line: raise CallbackURLError(f"redirect_uri co...
        # Line: raise CallbackURLError(f"redirect_uri contains ill
        raise CallbackURLError(f"redirect_uri contains illegal whitespace characters: '{cleaned}'")

    # Explain this line: parsed = urllib.parse.urlparse(cleaned)...
    # Line: parsed = urllib.parse.urlparse(cleaned)
    parsed = urllib.parse.urlparse(cleaned)

    # Explain this line: if parsed.scheme.lower() != "https":...
    # Line: if parsed.scheme.lower() != "https":
    if parsed.scheme.lower() != "https":
        # Explain this line: raise CallbackURLError(...
        # Line: raise CallbackURLError(
        raise CallbackURLError(
            # Explain this line: f"Invalid scheme '{parsed.scheme}' in re...
            # Line: f"Invalid scheme '{parsed.scheme}' in redirect_uri
            f"Invalid scheme '{parsed.scheme}' in redirect_uri '{cleaned}'. "
            # Explain this line: "Schwab Developer Portal requirements ma...
            # Line: "Schwab Developer Portal requirements mandate the
            "Schwab Developer Portal requirements mandate the 'https://' scheme."
        # Explain this line: )...
        # Line: )
        )

    # Explain this line: if parsed.path == "/" and not parsed.que...
    # Line: if parsed.path == "/" and not parsed.query and not
    if parsed.path == "/" and not parsed.query and not parsed.fragment:
        # Explain this line: cleaned = f"{parsed.scheme}://{parsed.ne...
        # Line: cleaned = f"{parsed.scheme}://{parsed.netloc}"
        cleaned = f"{parsed.scheme}://{parsed.netloc}"

    # Explain this line: return cleaned...
    # Line: return cleaned
    return cleaned


# Explain this line: def _atomic_write_secure_json(target_pat...
# Line: def _atomic_write_secure_json(target_path: Path, d
def _atomic_write_secure_json(target_path: Path, data: Dict[str, Any]) -> None:
    """
    Atomically writes JSON payload to disk with POSIX 0o600 permissions.
    Eliminates the umask vulnerability window using low-level os.open before writing.
    """
    # Explain this line: target_path.parent.mkdir(parents=True, e...
    # Line: target_path.parent.mkdir(parents=True, exist_ok=Tr
    target_path.parent.mkdir(parents=True, exist_ok=True)
    # Explain this line: tmp_path = target_path.with_name(f"{targ...
    # Line: tmp_path = target_path.with_name(f"{target_path.na
    tmp_path = target_path.with_name(f"{target_path.name}.tmp.{os.getpid()}_{threading.get_ident()}")

    # Explain this line: flags = os.O_WRONLY | os.O_CREAT | os.O_...
    # Line: flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    # Explain this line: if hasattr(os, "O_NOFOLLOW"):...
    # Line: if hasattr(os, "O_NOFOLLOW"):
    if hasattr(os, "O_NOFOLLOW"):
        # Explain this line: flags |= os.O_NOFOLLOW...
        # Line: flags |= os.O_NOFOLLOW
        flags |= os.O_NOFOLLOW

    # Explain this line: fd = os.open(tmp_path, flags, 0o600)...
    # Line: fd = os.open(tmp_path, flags, 0o600)
    fd = os.open(tmp_path, flags, 0o600)
    # Explain this line: try:...
    # Line: try:
    try:
        # Explain this line: with open(fd, "w", encoding="utf-8", clo...
        # Line: with open(fd, "w", encoding="utf-8", closefd=True)
        with open(fd, "w", encoding="utf-8", closefd=True) as f:
            # Explain this line: json.dump(data, f, indent=4)...
            # Line: json.dump(data, f, indent=4)
            json.dump(data, f, indent=4)
            # Explain this line: f.flush()...
            # Line: f.flush()
            f.flush()
            # Explain this line: os.fsync(f.fileno())...
            # Line: os.fsync(f.fileno())
            os.fsync(f.fileno())
    # Explain this line: except Exception:...
    # Line: except Exception:
    except Exception:
        # Explain this line: if tmp_path.exists():...
        # Line: if tmp_path.exists():
        if tmp_path.exists():
            # Explain this line: tmp_path.unlink()...
            # Line: tmp_path.unlink()
            tmp_path.unlink()
        # Explain this line: raise...
        # Line: raise
        raise

    # Explain this line: os.replace(tmp_path, target_path)...
    # Line: os.replace(tmp_path, target_path)
    os.replace(tmp_path, target_path)


# Explain this line: def _safe_json_parse(resp: Response) -> ...
# Line: def _safe_json_parse(resp: Response) -> Dict[str,
def _safe_json_parse(resp: Response) -> Dict[str, Any]:
    """Safely extracts JSON payload without leaking internal gateway tokens on error."""
    # Explain this line: try:...
    # Line: try:
    try:
        # Explain this line: return resp.json()...
        # Line: return resp.json()
        return resp.json()
    # Explain this line: except ValueError as exc:...
    # Line: except ValueError as exc:
    except ValueError as exc:
        # Explain this line: correl_id = resp.headers.get("Schwab-Cli...
        # Line: correl_id = resp.headers.get("Schwab-Client-Correl
        correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
        # Explain this line: raise APIRequestError(...
        # Line: raise APIRequestError(
        raise APIRequestError(
            # Explain this line: f"Invalid JSON returned from endpoint (H...
            # Line: f"Invalid JSON returned from endpoint (HTTP {resp.
            f"Invalid JSON returned from endpoint (HTTP {resp.status_code}). CorrelId: {correl_id}",
            # Explain this line: status_code=resp.status_code,...
            # Line: status_code=resp.status_code,
            status_code=resp.status_code,
            # Explain this line: correl_id=correl_id,...
            # Line: correl_id=correl_id,
            correl_id=correl_id,
        # Explain this line: ) from exc...
        # Line: ) from exc
        ) from exc


# Explain this line: def _parse_schwab_error(resp: Response) ...
# Line: def _parse_schwab_error(resp: Response) -> str:
def _parse_schwab_error(resp: Response) -> str:
    """
    Extracts detailed diagnostics from Schwab's structured JSON error schema:
    {"errors": [{"status": 400, "title": "Bad Request", "detail": "...", "id": "guid"}]}
    Falls back to sanitized raw text if payload does not match schema.
    """
    # Explain this line: try:...
    # Line: try:
    try:
        # Explain this line: data = resp.json()...
        # Line: data = resp.json()
        data = resp.json()
        # Explain this line: if isinstance(data, dict) and "errors" i...
        # Line: if isinstance(data, dict) and "errors" in data and
        if isinstance(data, dict) and "errors" in data and isinstance(data["errors"], list):
            # Explain this line: messages = []...
            # Line: messages = []
            messages = []
            # Explain this line: for err in data["errors"]:...
            # Line: for err in data["errors"]:
            for err in data["errors"]:
                # Explain this line: if isinstance(err, dict):...
                # Line: if isinstance(err, dict):
                if isinstance(err, dict):
                    # Explain this line: title = err.get("title", "")...
                    # Line: title = err.get("title", "")
                    title = err.get("title", "")
                    # Explain this line: detail = err.get("detail", "")...
                    # Line: detail = err.get("detail", "")
                    detail = err.get("detail", "")
                    # Explain this line: err_id = err.get("id", "")...
                    # Line: err_id = err.get("id", "")
                    err_id = err.get("id", "")
                    # Explain this line: elements = [e for e in (title, detail) i...
                    # Line: elements = [e for e in (title, detail) if e]
                    elements = [e for e in (title, detail) if e]
                    # Explain this line: msg = ": ".join(elements) if elements el...
                    # Line: msg = ": ".join(elements) if elements else "Unspec
                    msg = ": ".join(elements) if elements else "Unspecified Schwab error"
                    # Explain this line: if err_id:...
                    # Line: if err_id:
                    if err_id:
                        # Explain this line: msg += f" (Error ID: {err_id})"...
                        # Line: msg += f" (Error ID: {err_id})"
                        msg += f" (Error ID: {err_id})"
                    # Explain this line: messages.append(msg)...
                    # Line: messages.append(msg)
                    messages.append(msg)
            # Explain this line: if messages:...
            # Line: if messages:
            if messages:
                # Explain this line: return " | ".join(messages)...
                # Line: return " | ".join(messages)
                return " | ".join(messages)
    # Explain this line: except Exception:...
    # Line: except Exception:
    except Exception:
        # Explain this line: pass...
        # Line: pass
        pass

    # Explain this line: return resp.text.strip()[:300] if resp.t...
    # Line: return resp.text.strip()[:300] if resp.text else "
    return resp.text.strip()[:300] if resp.text else "No error payload returned by gateway."


# Explain this line: def _parse_retry_after(header_val: Optio...
# Line: def _parse_retry_after(header_val: Optional[str],
def _parse_retry_after(header_val: Optional[str], default_wait: float) -> float:
    """Parses RFC-7231 or integer seconds from HTTP Retry-After headers."""
    # Explain this line: if not header_val:...
    # Line: if not header_val:
    if not header_val:
        # Explain this line: return default_wait...
        # Line: return default_wait
        return default_wait
    # Explain this line: try:...
    # Line: try:
    try:
        # Explain this line: return max(0.0, float(header_val))...
        # Line: return max(0.0, float(header_val))
        return max(0.0, float(header_val))
    # Explain this line: except ValueError:...
    # Line: except ValueError:
    except ValueError:
        # Explain this line: pass...
        # Line: pass
        pass
    # Explain this line: try:...
    # Line: try:
    try:
        # Explain this line: date_tuple = email.utils.parsedate_tz(he...
        # Line: date_tuple = email.utils.parsedate_tz(header_val)
        date_tuple = email.utils.parsedate_tz(header_val)
        # Explain this line: if date_tuple:...
        # Line: if date_tuple:
        if date_tuple:
            # Explain this line: target_time = email.utils.mktime_tz(date...
            # Line: target_time = email.utils.mktime_tz(date_tuple)
            target_time = email.utils.mktime_tz(date_tuple)
            # Explain this line: return max(0.0, target_time - time.time(...
            # Line: return max(0.0, target_time - time.time())
            return max(0.0, target_time - time.time())
    # Explain this line: except Exception:...
    # Line: except Exception:
    except Exception:
        # Explain this line: pass...
        # Line: pass
        pass
    # Explain this line: return default_wait...
    # Line: return default_wait
    return default_wait


# ---------------------------------------------------------------------------
# CLIENT IMPLEMENTATION
# ---------------------------------------------------------------------------
# Explain this line: class SchwabClient:...
# Line: class SchwabClient:
class SchwabClient:
    """
    Thread-safe, institutional-grade market data client for Charles Schwab.
    Handles automated token persistence, proactive background refresh, and endpoint queries.
    """

    # Explain this line: def __init__(...
    # Line: def __init__(
    def __init__(
        # Explain this line: self,...
        # Line: self,
        self,
        # Explain this line: client_id: Optional[str] = None,...
        # Line: client_id: Optional[str] = None,
        client_id: Optional[str] = None,
        # Explain this line: client_secret: Optional[str] = None,...
        # Line: client_secret: Optional[str] = None,
        client_secret: Optional[str] = None,
        # Explain this line: redirect_uri: Optional[str] = None,...
        # Line: redirect_uri: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        # Explain this line: token_file_path: Optional[Union[str, Pat...
        # Line: token_file_path: Optional[Union[str, Path]] = None
        token_file_path: Optional[Union[str, Path]] = None,
        # Explain this line: session: Optional[Session] = None,...
        # Line: session: Optional[Session] = None,
        session: Optional[Session] = None,
        # Explain this line: timeout: Tuple[float, float] = DEFAULT_T...
        # Line: timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
        timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
        # Explain this line: max_retries: int = DEFAULT_RETRIES,...
        # Line: max_retries: int = DEFAULT_RETRIES,
        max_retries: int = DEFAULT_RETRIES,
        # Explain this line: pool_connections: int = 50,...
        # Line: pool_connections: int = 50,
        pool_connections: int = 50,
        # Explain this line: pool_maxsize: int = 50,...
        # Line: pool_maxsize: int = 50,
        pool_maxsize: int = 50,
    # Explain this line: ) -> None:...
    # Line: ) -> None:
    ) -> None:
        # Explain this line: self.client_id = (client_id or os.enviro...
        # Line: self.client_id = (client_id or os.environ.get("SCH
        self.client_id = (client_id or os.environ.get("SCHWAB_CLIENT_ID", "")).strip()
        # Explain this line: self.client_secret = (client_secret or o...
        # Line: self.client_secret = (client_secret or os.environ.
        self.client_secret = (client_secret or os.environ.get("SCHWAB_CLIENT_SECRET", "")).strip()

        # Explain this line: raw_redirect = (redirect_uri or os.envir...
        # Line: raw_redirect = (redirect_uri or os.environ.get("SC
        raw_redirect = (redirect_uri or os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")).strip()
        # Explain this line: self.redirect_uri = validate_and_normali...
        # Line: self.redirect_uri = validate_and_normalize_redirec
        self.redirect_uri = validate_and_normalize_redirect_uri(raw_redirect)

        # Explain this line: raw_token_path = token_file_path or os.e...
        # Line: raw_token_path = token_file_path or os.environ.get
        raw_token_path = token_file_path or os.environ.get("SCHWAB_TOKEN_PATH", "schwab_tokens.json")
        # Explain this line: self.token_file_path = Path(raw_token_pa...
        # Line: self.token_file_path = Path(raw_token_path).resolv
        self.token_file_path = Path(raw_token_path).resolve()

        # Explain this line: if not self.client_id:...
        # Line: if not self.client_id:
        if not self.client_id:
            # Explain this line: raise ValueError("Configuration missing:...
            # Line: raise ValueError("Configuration missing: SCHWAB_CL
            raise ValueError("Configuration missing: SCHWAB_CLIENT_ID must be provided.")

        # Explain this line: self.timeout = timeout...
        # Line: self.timeout = timeout
        self.timeout = timeout
        # Explain this line: self.max_retries = max(0, max_retries)...
        # Line: self.max_retries = max(0, max_retries)
        self.max_retries = max(0, max_retries)

        # Thread synchronization primitives
        # Explain this line: self._tokens_lock = threading.RLock()...
        # Line: self._tokens_lock = threading.RLock()
        self._tokens_lock = threading.RLock()
        # Explain this line: self._token_payload: Optional[TokenPaylo...
        # Line: self._token_payload: Optional[TokenPayload] = None
        self._token_payload: Optional[TokenPayload] = None

        # Build resilient connection pool
        # Explain this line: if session:...
        # Line: if session:
        if session:
            # Explain this line: self.session = session...
            # Line: self.session = session
            self.session = session
        # Explain this line: else:...
        # Line: else:
        else:
            # Explain this line: self.session = requests.Session()...
            # Line: self.session = requests.Session()
            self.session = requests.Session()
            # Explain this line: adapter = HTTPAdapter(...
            # Line: adapter = HTTPAdapter(
            adapter = HTTPAdapter(
                # Explain this line: pool_connections=pool_connections,...
                # Line: pool_connections=pool_connections,
                pool_connections=pool_connections,
                # Explain this line: pool_maxsize=pool_maxsize,...
                # Line: pool_maxsize=pool_maxsize,
                pool_maxsize=pool_maxsize,
                # Explain this line: max_retries=Retry(total=0),  # Handled v...
                # Line: max_retries=Retry(total=0),  # Handled via custom
                max_retries=Retry(total=0),  # Handled via custom exponential backoff engine
            # Explain this line: )...
            # Line: )
            )
            # Explain this line: self.session.mount("https://", adapter)...
            # Line: self.session.mount("https://", adapter)
            self.session.mount("https://", adapter)

        # Explain this line: self._load_tokens_from_disk()...
        # Line: self._load_tokens_from_disk()
        self._load_tokens_from_disk()

    # -----------------------------------------------------------------------
    # TOKEN PERSISTENCE & CONCURRENCY
    # -----------------------------------------------------------------------
    # Explain this line: def _load_tokens_from_disk(self) -> None...
    # Line: def _load_tokens_from_disk(self) -> None:
    def _load_tokens_from_disk(self) -> None:
        """Loads cached tokens into memory under thread lock."""
        # Explain this line: with self._tokens_lock:...
        # Line: with self._tokens_lock:
        with self._tokens_lock:
            # Explain this line: if not self.token_file_path.exists():...
            # Line: if not self.token_file_path.exists():
            if not self.token_file_path.exists():
                # Explain this line: self._token_payload = None...
                # Line: self._token_payload = None
                self._token_payload = None
                # Explain this line: return...
                # Line: return
                return

            # Explain this line: try:...
            # Line: try:
            try:
                # Explain this line: with self.token_file_path.open("r", enco...
                # Line: with self.token_file_path.open("r", encoding="utf-
                with self.token_file_path.open("r", encoding="utf-8") as f:
                    # Explain this line: data = json.load(f)...
                    # Line: data = json.load(f)
                    data = json.load(f)
                # Explain this line: if "access_token" in data:...
                # Line: if "access_token" in data:
                if "access_token" in data:
                    # Explain this line: self._token_payload = TokenPayload.from_...
                    # Line: self._token_payload = TokenPayload.from_dict(data)
                    self._token_payload = TokenPayload.from_dict(data)
                # Explain this line: else:...
                # Line: else:
                else:
                    # Explain this line: self._token_payload = None...
                    # Line: self._token_payload = None
                    self._token_payload = None
            # Explain this line: except Exception as exc:...
            # Line: except Exception as exc:
            except Exception as exc:
                # Explain this line: logger.warning("Unreadable token store a...
                # Line: logger.warning("Unreadable token store at %s: %s",
                logger.warning("Unreadable token store at %s: %s", self.token_file_path, exc)
                # Explain this line: self._token_payload = None...
                # Line: self._token_payload = None
                self._token_payload = None

    # Explain this line: def _persist_tokens(self, token_data: Di...
    # Line: def _persist_tokens(self, token_data: Dict[str, An
    def _persist_tokens(self, token_data: Dict[str, Any]) -> TokenPayload:
        """Atomically caches new token sets to disk and updates in-memory reference."""
        # Explain this line: with self._tokens_lock:...
        # Line: with self._tokens_lock:
        with self._tokens_lock:
            # Explain this line: if "refresh_token" not in token_data and...
            # Line: if "refresh_token" not in token_data and self._tok
            if "refresh_token" not in token_data and self._token_payload and self._token_payload.refresh_token:
                # Explain this line: token_data["refresh_token"] = self._toke...
                # Line: token_data["refresh_token"] = self._token_payload.
                token_data["refresh_token"] = self._token_payload.refresh_token

            # Explain this line: expires_in = int(token_data.get("expires...
            # Line: expires_in = int(token_data.get("expires_in", 1800
            expires_in = int(token_data.get("expires_in", 1800))
            # Explain this line: token_data["expires_at"] = time.time() +...
            # Line: token_data["expires_at"] = time.time() + expires_i
            token_data["expires_at"] = time.time() + expires_in

            # Explain this line: _atomic_write_secure_json(self.token_fil...
            # Line: _atomic_write_secure_json(self.token_file_path, to
            _atomic_write_secure_json(self.token_file_path, token_data)
            # Explain this line: self._token_payload = TokenPayload.from_...
            # Line: self._token_payload = TokenPayload.from_dict(token
            self._token_payload = TokenPayload.from_dict(token_data)
            # Explain this line: return self._token_payload...
            # Line: return self._token_payload
            return self._token_payload

    # Explain this line: def _get_basic_auth_header(self) -> Dict...
    # Line: def _get_basic_auth_header(self) -> Dict[str, str]
    def _get_basic_auth_header(self) -> Dict[str, str]:
        """Builds HTTP Basic Authorization header: 'Basic base64(client_id:client_secret)'."""
        # Explain this line: if not self.client_secret:...
        # Line: if not self.client_secret:
        if not self.client_secret:
            # Explain this line: raise ValueError("Operation requires SCH...
            # Line: raise ValueError("Operation requires SCHWAB_CLIENT
            raise ValueError("Operation requires SCHWAB_CLIENT_SECRET.")
        # Explain this line: raw_creds = f"{self.client_id}:{self.cli...
        # Line: raw_creds = f"{self.client_id}:{self.client_secret
        raw_creds = f"{self.client_id}:{self.client_secret}"
        # Explain this line: encoded = base64.b64encode(raw_creds.enc...
        # Line: encoded = base64.b64encode(raw_creds.encode("utf-8
        encoded = base64.b64encode(raw_creds.encode("utf-8")).decode("utf-8")
        # Explain this line: return {...
        # Line: return {
        return {
            # Explain this line: "Authorization": f"Basic {encoded}",...
            # Line: "Authorization": f"Basic {encoded}",
            "Authorization": f"Basic {encoded}",
            # Explain this line: "Content-Type": "application/x-www-form-...
            # Line: "Content-Type": "application/x-www-form-urlencoded
            "Content-Type": "application/x-www-form-urlencoded",
        # Explain this line: }...
        # Line: }
        }

    # -----------------------------------------------------------------------
    # OAUTH TRANSACTIONS
    # -----------------------------------------------------------------------
    # Explain this line: def build_auth_url(self, state: Optional...
    # Line: def build_auth_url(self, state: Optional[str] = No
    def build_auth_url(self, state: Optional[str] = None) -> str:
        """Constructs user consent URL with validated callback URI and optional CSRF state."""
        # Explain this line: params = {...
        # Line: params = {
        params = {
            # Explain this line: "response_type": "code",...
            # Line: "response_type": "code",
            "response_type": "code",
            # Explain this line: "client_id": self.client_id,...
            # Line: "client_id": self.client_id,
            "client_id": self.client_id,
            # Explain this line: "redirect_uri": self.redirect_uri,...
            # Line: "redirect_uri": self.redirect_uri,
            "redirect_uri": self.redirect_uri,
            # Explain this line: "scope": "api",...
            # Line: "scope": "api",
            "scope": "api",
        # Explain this line: }...
        # Line: }
        }
        # Explain this line: if state:...
        # Line: if state:
        if state:
            # Explain this line: params["state"] = state...
            # Line: params["state"] = state
            params["state"] = state
        # Explain this line: return f"{AUTH_URL}?{urllib.parse.urlenc...
        # Line: return f"{AUTH_URL}?{urllib.parse.urlencode(params
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    # Explain this line: def exchange_code_for_token(...
    # Line: def exchange_code_for_token(
    def exchange_code_for_token(
        # Explain this line: self,...
        # Line: self,
        self,
        # Explain this line: code_or_url: str,...
        # Line: code_or_url: str,
        code_or_url: str,
        # Explain this line: expected_state: Optional[str] = None,...
        # Line: expected_state: Optional[str] = None,
        expected_state: Optional[str] = None,
    # Explain this line: ) -> TokenPayload:...
    # Line: ) -> TokenPayload:
    ) -> TokenPayload:
        """
        Exchanges the authorization code for access and refresh tokens.
        Validates the returned CSRF 'state' token if expected_state was supplied.
        """
        # Explain this line: raw = code_or_url.strip()...
        # Line: raw = code_or_url.strip()
        raw = code_or_url.strip()
        # Explain this line: extracted_state = None...
        # Line: extracted_state = None
        extracted_state = None

        # Explain this line: if "code=" in raw:...
        # Line: if "code=" in raw:
        if "code=" in raw:
            # Explain this line: query = raw.split("?", 1)[-1] if "?" in ...
            # Line: query = raw.split("?", 1)[-1] if "?" in raw else r
            query = raw.split("?", 1)[-1] if "?" in raw else raw
            # Explain this line: parsed = urllib.parse.parse_qs(query)...
            # Line: parsed = urllib.parse.parse_qs(query)
            parsed = urllib.parse.parse_qs(query)
            # Explain this line: extracted_code = parsed.get("code", [Non...
            # Line: extracted_code = parsed.get("code", [None])[0]
            extracted_code = parsed.get("code", [None])[0]
            # Explain this line: extracted_state = parsed.get("state", [N...
            # Line: extracted_state = parsed.get("state", [None])[0]
            extracted_state = parsed.get("state", [None])[0]
            # Explain this line: if not extracted_code:...
            # Line: if not extracted_code:
            if not extracted_code:
                # Explain this line: extracted_code = raw.split("code=")[-1]....
                # Line: extracted_code = raw.split("code=")[-1].split("&")
                extracted_code = raw.split("code=")[-1].split("&")[0]
        # Explain this line: else:...
        # Line: else:
        else:
            # Explain this line: extracted_code = raw...
            # Line: extracted_code = raw
            extracted_code = raw

        # Cryptographic state verification (RFC 6749 Section 10.12)
        # Explain this line: if expected_state:...
        # Line: if expected_state:
        if expected_state:
            # Explain this line: if not extracted_state:...
            # Line: if not extracted_state:
            if not extracted_state:
                # Explain this line: raise TokenError("Security Alert: Author...
                # Line: raise TokenError("Security Alert: Authorization re
                raise TokenError("Security Alert: Authorization response is missing the required 'state' parameter.")
            # Explain this line: if extracted_state != expected_state:...
            # Line: if extracted_state != expected_state:
            if extracted_state != expected_state:
                # Explain this line: raise TokenError(...
                # Line: raise TokenError(
                raise TokenError(
                    # Explain this line: f"Security Alert: CSRF state mismatch de...
                    # Line: f"Security Alert: CSRF state mismatch detected! Ex
                    f"Security Alert: CSRF state mismatch detected! Expected '{expected_state}', got '{extracted_state}'."
                # Explain this line: )...
                # Line: )
                )

        # Explain this line: sanitized_code = urllib.parse.unquote((e...
        # Line: sanitized_code = urllib.parse.unquote((extracted_c
        sanitized_code = urllib.parse.unquote((extracted_code or "").strip())
        # Explain this line: if not sanitized_code:...
        # Line: if not sanitized_code:
        if not sanitized_code:
            # Explain this line: raise TokenError("Failed to extract vali...
            # Line: raise TokenError("Failed to extract valid authoriz
            raise TokenError("Failed to extract valid authorization code parameter.")

        # Explain this line: payload = {...
        # Line: payload = {
        payload = {
            # Explain this line: "grant_type": "authorization_code",...
            # Line: "grant_type": "authorization_code",
            "grant_type": "authorization_code",
            # Explain this line: "code": sanitized_code,...
            # Line: "code": sanitized_code,
            "code": sanitized_code,
            # Explain this line: "redirect_uri": self.redirect_uri,...
            # Line: "redirect_uri": self.redirect_uri,
            "redirect_uri": self.redirect_uri,
        # Explain this line: }...
        # Line: }
        }

        # Explain this line: resp = self._raw_http_request("POST", TO...
        # Line: resp = self._raw_http_request("POST", TOKEN_URL, h
        resp = self._raw_http_request("POST", TOKEN_URL, headers=self._get_basic_auth_header(), data=payload)
        # Explain this line: if resp.status_code != 200:...
        # Line: if resp.status_code != 200:
        if resp.status_code != 200:
            # Explain this line: correl_id = resp.headers.get("Schwab-Cli...
            # Line: correl_id = resp.headers.get("Schwab-Client-Correl
            correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
            # Explain this line: err_msg = _parse_schwab_error(resp)...
            # Line: err_msg = _parse_schwab_error(resp)
            err_msg = _parse_schwab_error(resp)
            # Explain this line: raise TokenError(...
            # Line: raise TokenError(
            raise TokenError(
                # Explain this line: f"OAuth code exchange failed (HTTP {resp...
                # Line: f"OAuth code exchange failed (HTTP {resp.status_co
                f"OAuth code exchange failed (HTTP {resp.status_code}). CorrelId: {correl_id} | Details: {err_msg}"
            # Explain this line: )...
            # Line: )
            )

        # Explain this line: return self._persist_tokens(_safe_json_p...
        # Line: return self._persist_tokens(_safe_json_parse(resp)
        return self._persist_tokens(_safe_json_parse(resp))

    # Explain this line: def refresh_access_token(self) -> TokenP...
    # Line: def refresh_access_token(self) -> TokenPayload:
    def refresh_access_token(self) -> TokenPayload:
        """Executes a silent token refresh using double-checked thread synchronization."""
        # Explain this line: with self._tokens_lock:...
        # Line: with self._tokens_lock:
        with self._tokens_lock:
            # Explain this line: if self._token_payload and time.time() <...
            # Line: if self._token_payload and time.time() < (self._to
            if self._token_payload and time.time() < (self._token_payload.expires_at - TOKEN_EXPIRY_BUFFER):
                # Explain this line: return self._token_payload...
                # Line: return self._token_payload
                return self._token_payload

            # Explain this line: if not self._token_payload or not self._...
            # Line: if not self._token_payload or not self._token_payl
            if not self._token_payload or not self._token_payload.refresh_token:
                # Explain this line: raise TokenError("No refresh token avail...
                # Line: raise TokenError("No refresh token available. Inte
                raise TokenError("No refresh token available. Interactive authorization required.")

            # Explain this line: payload = {...
            # Line: payload = {
            payload = {
                # Explain this line: "grant_type": "refresh_token",...
                # Line: "grant_type": "refresh_token",
                "grant_type": "refresh_token",
                # Explain this line: "refresh_token": self._token_payload.ref...
                # Line: "refresh_token": self._token_payload.refresh_token
                "refresh_token": self._token_payload.refresh_token,
            # Explain this line: }...
            # Line: }
            }

            # Explain this line: resp = self._raw_http_request("POST", TO...
            # Line: resp = self._raw_http_request("POST", TOKEN_URL, h
            resp = self._raw_http_request("POST", TOKEN_URL, headers=self._get_basic_auth_header(), data=payload)
            # Explain this line: if resp.status_code != 200:...
            # Line: if resp.status_code != 200:
            if resp.status_code != 200:
                # Explain this line: correl_id = resp.headers.get("Schwab-Cli...
                # Line: correl_id = resp.headers.get("Schwab-Client-Correl
                correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
                # Explain this line: err_msg = _parse_schwab_error(resp)...
                # Line: err_msg = _parse_schwab_error(resp)
                err_msg = _parse_schwab_error(resp)
                # Explain this line: raise TokenError(...
                # Line: raise TokenError(
                raise TokenError(
                    # Explain this line: f"Refresh token rejected by Schwab (HTTP...
                    # Line: f"Refresh token rejected by Schwab (HTTP {resp.sta
                    f"Refresh token rejected by Schwab (HTTP {resp.status_code}). "
                    # Explain this line: f"CorrelId: {correl_id} | Details: {err_...
                    # Line: f"CorrelId: {correl_id} | Details: {err_msg}"
                    f"CorrelId: {correl_id} | Details: {err_msg}"
                # Explain this line: )...
                # Line: )
                )

            # Explain this line: return self._persist_tokens(_safe_json_p...
            # Line: return self._persist_tokens(_safe_json_parse(resp)
            return self._persist_tokens(_safe_json_parse(resp))

    # Explain this line: def get_valid_access_token(self) -> str:...
    # Line: def get_valid_access_token(self) -> str:
    def get_valid_access_token(self) -> str:
        """Fast-path thread-safe retrieval of validated access token."""
        # Explain this line: current = self._token_payload...
        # Line: current = self._token_payload
        current = self._token_payload
        # Explain this line: if current and time.time() < (current.ex...
        # Line: if current and time.time() < (current.expires_at -
        if current and time.time() < (current.expires_at - TOKEN_EXPIRY_BUFFER):
            # Explain this line: return current.access_token...
            # Line: return current.access_token
            return current.access_token

        # Explain this line: return self.refresh_access_token().acces...
        # Line: return self.refresh_access_token().access_token
        return self.refresh_access_token().access_token

    # -----------------------------------------------------------------------
    # RESILIENT HTTP EXECUTION ENGINE
    # -----------------------------------------------------------------------
    # Explain this line: def _raw_http_request(...
    # Line: def _raw_http_request(
    def _raw_http_request(
        # Explain this line: self,...
        # Line: self,
        self,
        # Explain this line: method: str,...
        # Line: method: str,
        method: str,
        # Explain this line: url: str,...
        # Line: url: str,
        url: str,
        # Explain this line: headers: Optional[Dict[str, str]] = None...
        # Line: headers: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        # Explain this line: params: Optional[Dict[str, Any]] = None,...
        # Line: params: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        # Explain this line: data: Optional[Dict[str, Any]] = None,...
        # Line: data: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    # Explain this line: ) -> Response:...
    # Line: ) -> Response:
    ) -> Response:
        """Executes raw HTTP calls with entropy-jittered exponential backoff and 429 adherence."""
        # Explain this line: attempt = 0...
        # Line: attempt = 0
        attempt = 0
        # Explain this line: while True:...
        # Line: while True:
        while True:
            # Explain this line: attempt += 1...
            # Line: attempt += 1
            attempt += 1
            # Explain this line: try:...
            # Line: try:
            try:
                # Explain this line: resp = self.session.request(...
                # Line: resp = self.session.request(
                resp = self.session.request(
                    # Explain this line: method=method,...
                    # Line: method=method,
                    method=method,
                    # Explain this line: url=url,...
                    # Line: url=url,
                    url=url,
                    # Explain this line: headers=headers,...
                    # Line: headers=headers,
                    headers=headers,
                    # Explain this line: params=params,...
                    # Line: params=params,
                    params=params,
                    # Explain this line: data=data,...
                    # Line: data=data,
                    data=data,
                    # Explain this line: timeout=self.timeout,...
                    # Line: timeout=self.timeout,
                    timeout=self.timeout,
                # Explain this line: )...
                # Line: )
                )
            # Explain this line: except requests.RequestException as err:...
            # Line: except requests.RequestException as err:
            except requests.RequestException as err:
                # Explain this line: if attempt > self.max_retries:...
                # Line: if attempt > self.max_retries:
                if attempt > self.max_retries:
                    # Explain this line: raise APIRequestError(f"Network transpor...
                    # Line: raise APIRequestError(f"Network transport failure
                    raise APIRequestError(f"Network transport failure after {attempt} attempts: {err}") from err
                # Explain this line: backoff = DEFAULT_BACKOFF_FACTOR * (2 **...
                # Line: backoff = DEFAULT_BACKOFF_FACTOR * (2 ** (attempt
                backoff = DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1))
                # Explain this line: time.sleep(backoff + (time.time() % 0.2)...
                # Line: time.sleep(backoff + (time.time() % 0.2))
                time.sleep(backoff + (time.time() % 0.2))
                # Explain this line: continue...
                # Line: continue
                continue

            # Handle rate limiting
            # Explain this line: if resp.status_code == 429:...
            # Line: if resp.status_code == 429:
            if resp.status_code == 429:
                # Explain this line: correl_id = resp.headers.get("Schwab-Cli...
                # Line: correl_id = resp.headers.get("Schwab-Client-Correl
                correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
                # Explain this line: wait_time = _parse_retry_after(...
                # Line: wait_time = _parse_retry_after(
                wait_time = _parse_retry_after(
                    # Explain this line: resp.headers.get("Retry-After"),...
                    # Line: resp.headers.get("Retry-After"),
                    resp.headers.get("Retry-After"),
                    # Explain this line: DEFAULT_BACKOFF_FACTOR * (2 ** (attempt ...
                    # Line: DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1)),
                    DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1)),
                # Explain this line: )...
                # Line: )
                )
                # Explain this line: logger.warning(...
                # Line: logger.warning(
                logger.warning(
                    # Explain this line: "Schwab rate limit triggered (CorrelId: ...
                    # Line: "Schwab rate limit triggered (CorrelId: %s). Backi
                    "Schwab rate limit triggered (CorrelId: %s). Backing off for %.2f seconds.",
                    # Explain this line: correl_id,...
                    # Line: correl_id,
                    correl_id,
                    # Explain this line: wait_time,...
                    # Line: wait_time,
                    wait_time,
                # Explain this line: )...
                # Line: )
                )
                # Explain this line: if attempt > self.max_retries:...
                # Line: if attempt > self.max_retries:
                if attempt > self.max_retries:
                    # Explain this line: raise APIRequestError(...
                    # Line: raise APIRequestError(
                    raise APIRequestError(
                        # Explain this line: f"Exceeded maximum retries on HTTP 429 R...
                        # Line: f"Exceeded maximum retries on HTTP 429 Rate Limit.
                        f"Exceeded maximum retries on HTTP 429 Rate Limit. CorrelId: {correl_id}",
                        # Explain this line: status_code=429,...
                        # Line: status_code=429,
                        status_code=429,
                        # Explain this line: correl_id=correl_id,...
                        # Line: correl_id=correl_id,
                        correl_id=correl_id,
                    # Explain this line: )...
                    # Line: )
                    )
                # Explain this line: time.sleep(wait_time)...
                # Line: time.sleep(wait_time)
                time.sleep(wait_time)
                # Explain this line: continue...
                # Line: continue
                continue

            # Retry transient server errors
            # Explain this line: if 500 <= resp.status_code < 600:...
            # Line: if 500 <= resp.status_code < 600:
            if 500 <= resp.status_code < 600:
                # Explain this line: correl_id = resp.headers.get("Schwab-Cli...
                # Line: correl_id = resp.headers.get("Schwab-Client-Correl
                correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
                # Explain this line: if attempt > self.max_retries:...
                # Line: if attempt > self.max_retries:
                if attempt > self.max_retries:
                    # Explain this line: err_msg = _parse_schwab_error(resp)...
                    # Line: err_msg = _parse_schwab_error(resp)
                    err_msg = _parse_schwab_error(resp)
                    # Explain this line: raise APIRequestError(...
                    # Line: raise APIRequestError(
                    raise APIRequestError(
                        # Explain this line: f"Persistent server failure (HTTP {resp....
                        # Line: f"Persistent server failure (HTTP {resp.status_cod
                        f"Persistent server failure (HTTP {resp.status_code}). "
                        # Explain this line: f"CorrelId: {correl_id} | Details: {err_...
                        # Line: f"CorrelId: {correl_id} | Details: {err_msg}",
                        f"CorrelId: {correl_id} | Details: {err_msg}",
                        # Explain this line: status_code=resp.status_code,...
                        # Line: status_code=resp.status_code,
                        status_code=resp.status_code,
                        # Explain this line: correl_id=correl_id,...
                        # Line: correl_id=correl_id,
                        correl_id=correl_id,
                        # Explain this line: error_details=err_msg,...
                        # Line: error_details=err_msg,
                        error_details=err_msg,
                    # Explain this line: )...
                    # Line: )
                    )
                # Explain this line: backoff = DEFAULT_BACKOFF_FACTOR * (2 **...
                # Line: backoff = DEFAULT_BACKOFF_FACTOR * (2 ** (attempt
                backoff = DEFAULT_BACKOFF_FACTOR * (2 ** (attempt - 1))
                # Explain this line: time.sleep(backoff)...
                # Line: time.sleep(backoff)
                time.sleep(backoff)
                # Explain this line: continue...
                # Line: continue
                continue

            # Explain this line: return resp...
            # Line: return resp
            return resp

    # Explain this line: def _execute_authenticated(...
    # Line: def _execute_authenticated(
    def _execute_authenticated(
        # Explain this line: self,...
        # Line: self,
        self,
        # Explain this line: endpoint_path: str,...
        # Line: endpoint_path: str,
        endpoint_path: str,
        # Explain this line: params: Optional[Dict[str, Any]] = None,...
        # Line: params: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    # Explain this line: ) -> Dict[str, Any]:...
    # Line: ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
        """Base API handler with automatic 401 token recovery and diagnostic logging."""
        # Explain this line: target_url = f"{MARKETDATA_BASE}{endpoin...
        # Line: target_url = f"{MARKETDATA_BASE}{endpoint_path}"
        target_url = f"{MARKETDATA_BASE}{endpoint_path}"

        # Explain this line: for is_recovery_attempt in (False, True)...
        # Line: for is_recovery_attempt in (False, True):
        for is_recovery_attempt in (False, True):
            # Explain this line: token = self.get_valid_access_token()...
            # Line: token = self.get_valid_access_token()
            token = self.get_valid_access_token()
            # Explain this line: headers = {"Authorization": f"Bearer {to...
            # Line: headers = {"Authorization": f"Bearer {token}", "Ac
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

            # Explain this line: resp = self._raw_http_request("GET", tar...
            # Line: resp = self._raw_http_request("GET", target_url, h
            resp = self._raw_http_request("GET", target_url, headers=headers, params=params)

            # Self-healing on unexpected token invalidation
            # Explain this line: if resp.status_code == 401 and not is_re...
            # Line: if resp.status_code == 401 and not is_recovery_att
            if resp.status_code == 401 and not is_recovery_attempt:
                # Explain this line: correl_id = resp.headers.get("Schwab-Cli...
                # Line: correl_id = resp.headers.get("Schwab-Client-Correl
                correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
                # Explain this line: logger.warning("HTTP 401 received (Corre...
                # Line: logger.warning("HTTP 401 received (CorrelId: %s).
                logger.warning("HTTP 401 received (CorrelId: %s). Forcing access token refresh.", correl_id)
                # Explain this line: self.refresh_access_token()...
                # Line: self.refresh_access_token()
                self.refresh_access_token()
                # Explain this line: continue...
                # Line: continue
                continue

            # Explain this line: if resp.status_code != 200:...
            # Line: if resp.status_code != 200:
            if resp.status_code != 200:
                # Explain this line: correl_id = resp.headers.get("Schwab-Cli...
                # Line: correl_id = resp.headers.get("Schwab-Client-Correl
                correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
                # Explain this line: version = resp.headers.get("Schwab-Resou...
                # Line: version = resp.headers.get("Schwab-Resource-Versio
                version = resp.headers.get("Schwab-Resource-Version", "1")
                # Explain this line: err_msg = _parse_schwab_error(resp)...
                # Line: err_msg = _parse_schwab_error(resp)
                err_msg = _parse_schwab_error(resp)

                # Explain this line: raise APIRequestError(...
                # Line: raise APIRequestError(
                raise APIRequestError(
                    # Explain this line: f"API request failed on {endpoint_path} ...
                    # Line: f"API request failed on {endpoint_path} (HTTP {res
                    f"API request failed on {endpoint_path} (HTTP {resp.status_code}). "
                    # Explain this line: f"CorrelId: {correl_id} | Version: {vers...
                    # Line: f"CorrelId: {correl_id} | Version: {version} | Det
                    f"CorrelId: {correl_id} | Version: {version} | Details: {err_msg}",
                    # Explain this line: status_code=resp.status_code,...
                    # Line: status_code=resp.status_code,
                    status_code=resp.status_code,
                    # Explain this line: correl_id=correl_id,...
                    # Line: correl_id=correl_id,
                    correl_id=correl_id,
                    # Explain this line: error_details=err_msg,...
                    # Line: error_details=err_msg,
                    error_details=err_msg,
                # Explain this line: )...
                # Line: )
                )

            # Explain this line: return _safe_json_parse(resp)...
            # Line: return _safe_json_parse(resp)
            return _safe_json_parse(resp)

        # Explain this line: correl_id = resp.headers.get("Schwab-Cli...
        # Line: correl_id = resp.headers.get("Schwab-Client-Correl
        correl_id = resp.headers.get("Schwab-Client-CorrelId", "UNKNOWN")
        # Explain this line: raise APIRequestError(...
        # Line: raise APIRequestError(
        raise APIRequestError(
            # Explain this line: f"Request failed after re-authentication...
            # Line: f"Request failed after re-authentication recovery
            f"Request failed after re-authentication recovery attempt. CorrelId: {correl_id}",
            # Explain this line: status_code=401,...
            # Line: status_code=401,
            status_code=401,
            # Explain this line: correl_id=correl_id,...
            # Line: correl_id=correl_id,
            correl_id=correl_id,
        # Explain this line: )...
        # Line: )
        )

    # -----------------------------------------------------------------------
    # ALL 7 SCHWAB MARKET DATA ENDPOINT FAMILIES (FULLY PARAMETERIZED)
    # -----------------------------------------------------------------------
    # Explain this line: def get_quotes(...
    # Line: def get_quotes(
    def get_quotes(
        # Explain this line: self,...
        # Line: self,
        self,
        # Explain this line: symbols: Union[str, List[str]],...
        # Line: symbols: Union[str, List[str]],
        symbols: Union[str, List[str]],
        # Explain this line: fields: Optional[str] = None,...
        # Line: fields: Optional[str] = None,
        fields: Optional[str] = None,
    # Explain this line: ) -> Dict[str, Any]:...
    # Line: ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
        """
        1. Quotes: Real-time/delayed quotes for single or multiple symbols.
        Parameters:
            symbols: Single ticker or list/comma-delimited tickers.
            fields: Comma-separated subset filter: 'quote,fundamental,extended,reference,regular'.
        """
        # Explain this line: if isinstance(symbols, list):...
        # Line: if isinstance(symbols, list):
        if isinstance(symbols, list):
            # Explain this line: clean_syms = ",".join(str(s).strip().upp...
            # Line: clean_syms = ",".join(str(s).strip().upper() for s
            clean_syms = ",".join(str(s).strip().upper() for s in symbols if str(s).strip())
        # Explain this line: else:...
        # Line: else:
        else:
            # Explain this line: clean_syms = ",".join(str(s).strip().upp...
            # Line: clean_syms = ",".join(str(s).strip().upper() for s
            clean_syms = ",".join(str(s).strip().upper() for s in str(symbols).split(",") if str(s).strip())

        # Explain this line: if not clean_syms:...
        # Line: if not clean_syms:
        if not clean_syms:
            # Explain this line: raise ValueError("Parameter 'symbols' mu...
            # Line: raise ValueError("Parameter 'symbols' must contain
            raise ValueError("Parameter 'symbols' must contain at least one valid ticker symbol.")

        # Explain this line: params: Dict[str, Any] = {"symbols": cle...
        # Line: params: Dict[str, Any] = {"symbols": clean_syms}
        params: Dict[str, Any] = {"symbols": clean_syms}
        # Explain this line: if fields:...
        # Line: if fields:
        if fields:
            # Explain this line: params["fields"] = fields.strip()...
            # Line: params["fields"] = fields.strip()
            params["fields"] = fields.strip()
        # Explain this line: return self._execute_authenticated("/quo...
        # Line: return self._execute_authenticated("/quotes", para
        return self._execute_authenticated("/quotes", params=params)

    # Explain this line: def get_quote(...
    # Line: def get_quote(
    def get_quote(
        # Explain this line: self,...
        # Line: self,
        self,
        # Explain this line: symbol: str,...
        # Line: symbol: str,
        symbol: str,
        # Explain this line: fields: Optional[str] = None,...
        # Line: fields: Optional[str] = None,
        fields: Optional[str] = None,
    # Explain this line: ) -> Dict[str, Any]:...
    # Line: ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
        """
        Convenience method: Retrieves quote breakdown for a single isolated symbol.
        """
        # Explain this line: if not symbol or not str(symbol).strip()...
        # Line: if not symbol or not str(symbol).strip():
        if not symbol or not str(symbol).strip():
            # Explain this line: raise ValueError("Parameter 'symbol' mus...
            # Line: raise ValueError("Parameter 'symbol' must be a non
            raise ValueError("Parameter 'symbol' must be a non-empty string.")

        # Explain this line: clean_sym = str(symbol).strip().upper()...
        # Line: clean_sym = str(symbol).strip().upper()
        clean_sym = str(symbol).strip().upper()
        # Explain this line: payload = self.get_quotes(symbols=clean_...
        # Line: payload = self.get_quotes(symbols=clean_sym, field
        payload = self.get_quotes(symbols=clean_sym, fields=fields)
        # Explain this line: return payload.get(clean_sym, payload)...
        # Line: return payload.get(clean_sym, payload)
        return payload.get(clean_sym, payload)

    # Explain this line: def get_price_history(...
    # Line: def get_price_history(
    def get_price_history(
        # Explain this line: self,...
        # Line: self,
        self,
        # Explain this line: symbol: str,...
        # Line: symbol: str,
        symbol: str,
        # Explain this line: period_type: str = "year",...
        # Line: period_type: str = "year",
        period_type: str = "year",
        # Explain this line: period: int = 1,...
        # Line: period: int = 1,
        period: int = 1,
        # Explain this line: frequency_type: str = "daily",...
        # Line: frequency_type: str = "daily",
        frequency_type: str = "daily",
        # Explain this line: frequency: int = 1,...
        # Line: frequency: int = 1,
        frequency: int = 1,
        # Explain this line: start_date: Optional[int] = None,...
        # Line: start_date: Optional[int] = None,
        start_date: Optional[int] = None,
        # Explain this line: end_date: Optional[int] = None,...
        # Line: end_date: Optional[int] = None,
        end_date: Optional[int] = None,
        # Explain this line: need_extended_hours: bool = False,...
        # Line: need_extended_hours: bool = False,
        need_extended_hours: bool = False,
    # Explain this line: ) -> Dict[str, Any]:...
    # Line: ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
        """
        2. Price History: Historical OHLCV candle bars across custom time horizons.
        Parameters:
            symbol: Ticker symbol.
            period_type: 'day', 'month', 'year', or 'ytd'.
            period: Lookback units (e.g., period=20 with period_type='year' pulls 20 years).
            frequency_type: 'minute', 'daily', 'weekly', or 'monthly'.
            frequency: Frequency multiplier (e.g., 1 for 1-day candles, 5 for 5-minute candles).
            start_date: Start epoch in milliseconds.
            end_date: End epoch in milliseconds.
            need_extended_hours: Includes pre- and post-market trading sessions.
        """
        # Explain this line: if not symbol or not str(symbol).strip()...
        # Line: if not symbol or not str(symbol).strip():
        if not symbol or not str(symbol).strip():
            # Explain this line: raise ValueError("Parameter 'symbol' mus...
            # Line: raise ValueError("Parameter 'symbol' must be a non
            raise ValueError("Parameter 'symbol' must be a non-empty string.")

        # Explain this line: params: Dict[str, Any] = {...
        # Line: params: Dict[str, Any] = {
        params: Dict[str, Any] = {
            # Explain this line: "symbol": str(symbol).strip().upper(),...
            # Line: "symbol": str(symbol).strip().upper(),
            "symbol": str(symbol).strip().upper(),
            # Explain this line: "periodType": period_type.lower(),...
            # Line: "periodType": period_type.lower(),
            "periodType": period_type.lower(),
            # Explain this line: "period": period,...
            # Line: "period": period,
            "period": period,
            # Explain this line: "frequencyType": frequency_type.lower(),...
            # Line: "frequencyType": frequency_type.lower(),
            "frequencyType": frequency_type.lower(),
            # Explain this line: "frequency": frequency,...
            # Line: "frequency": frequency,
            "frequency": frequency,
            # Explain this line: "needExtendedHoursData": str(need_extend...
            # Line: "needExtendedHoursData": str(need_extended_hours).
            "needExtendedHoursData": str(need_extended_hours).lower(),
        # Explain this line: }...
        # Line: }
        }
        # Explain this line: if start_date is not None:...
        # Line: if start_date is not None:
        if start_date is not None:
            # Explain this line: params["startDate"] = start_date...
            # Line: params["startDate"] = start_date
            params["startDate"] = start_date
        # Explain this line: if end_date is not None:...
        # Line: if end_date is not None:
        if end_date is not None:
            # Explain this line: params["endDate"] = end_date...
            # Line: params["endDate"] = end_date
            params["endDate"] = end_date
        # Explain this line: return self._execute_authenticated("/pri...
        # Line: return self._execute_authenticated("/pricehistory"
        return self._execute_authenticated("/pricehistory", params=params)

    # Explain this line: def get_option_chain(...
    # Line: def get_option_chain(
    def get_option_chain(
        # Explain this line: self,...
        # Line: self,
        self,
        # Explain this line: symbol: str,...
        # Line: symbol: str,
        symbol: str,
        # Explain this line: contract_type: str = "ALL",...
        # Line: contract_type: str = "ALL",
        contract_type: str = "ALL",
        # Explain this line: strike_count: Optional[int] = None,...
        # Line: strike_count: Optional[int] = None,
        strike_count: Optional[int] = None,
        # Explain this line: include_underlying_quote: bool = True,...
        # Line: include_underlying_quote: bool = True,
        include_underlying_quote: bool = True,
        # Explain this line: strategy: str = "SINGLE",...
        # Line: strategy: str = "SINGLE",
        strategy: str = "SINGLE",
        # Explain this line: interval: Optional[float] = None,...
        # Line: interval: Optional[float] = None,
        interval: Optional[float] = None,
        # Explain this line: strike: Optional[float] = None,...
        # Line: strike: Optional[float] = None,
        strike: Optional[float] = None,
        # Explain this line: from_date: Optional[str] = None,...
        # Line: from_date: Optional[str] = None,
        from_date: Optional[str] = None,
        # Explain this line: to_date: Optional[str] = None,...
        # Line: to_date: Optional[str] = None,
        to_date: Optional[str] = None,
    # Explain this line: ) -> Dict[str, Any]:...
    # Line: ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
        """
        3. Option Chains: Real-time strike matrix with implied volatility and Greeks.
        Parameters:
            symbol: Underlying ticker symbol.
            contract_type: 'CALL', 'PUT', or 'ALL'.
            strike_count: Number of strikes above/below ATM. Pass None for full unbounded chain.
            strategy: 'SINGLE', 'ANALYTICAL', 'COVERED', 'VERTICAL', etc.
            interval: Strike interval filter.
            strike: Exact strike price filter.
            from_date: Expiration filter start (YYYY-MM-DD).
            to_date: Expiration filter end (YYYY-MM-DD).
        """
        # Explain this line: if not symbol or not str(symbol).strip()...
        # Line: if not symbol or not str(symbol).strip():
        if not symbol or not str(symbol).strip():
            # Explain this line: raise ValueError("Parameter 'symbol' mus...
            # Line: raise ValueError("Parameter 'symbol' must be a non
            raise ValueError("Parameter 'symbol' must be a non-empty string.")

        # Explain this line: params: Dict[str, Any] = {...
        # Line: params: Dict[str, Any] = {
        params: Dict[str, Any] = {
            # Explain this line: "symbol": str(symbol).strip().upper(),...
            # Line: "symbol": str(symbol).strip().upper(),
            "symbol": str(symbol).strip().upper(),
            # Explain this line: "contractType": contract_type.upper(),...
            # Line: "contractType": contract_type.upper(),
            "contractType": contract_type.upper(),
            # Explain this line: "includeUnderlyingQuote": str(include_un...
            # Line: "includeUnderlyingQuote": str(include_underlying_q
            "includeUnderlyingQuote": str(include_underlying_quote).lower(),
            # Explain this line: "strategy": strategy.upper(),...
            # Line: "strategy": strategy.upper(),
            "strategy": strategy.upper(),
        # Explain this line: }...
        # Line: }
        }
        # Explain this line: if strike_count is not None:...
        # Line: if strike_count is not None:
        if strike_count is not None:
            # Explain this line: params["strikeCount"] = strike_count...
            # Line: params["strikeCount"] = strike_count
            params["strikeCount"] = strike_count
        # Explain this line: if interval is not None:...
        # Line: if interval is not None:
        if interval is not None:
            # Explain this line: params["interval"] = interval...
            # Line: params["interval"] = interval
            params["interval"] = interval
        # Explain this line: if strike is not None:...
        # Line: if strike is not None:
        if strike is not None:
            # Explain this line: params["strike"] = strike...
            # Line: params["strike"] = strike
            params["strike"] = strike
        # Explain this line: if from_date:...
        # Line: if from_date:
        if from_date:
            # Explain this line: params["fromDate"] = from_date...
            # Line: params["fromDate"] = from_date
            params["fromDate"] = from_date
        # Explain this line: if to_date:...
        # Line: if to_date:
        if to_date:
            # Explain this line: params["toDate"] = to_date...
            # Line: params["toDate"] = to_date
            params["toDate"] = to_date

        # Explain this line: return self._execute_authenticated("/cha...
        # Line: return self._execute_authenticated("/chains", para
        return self._execute_authenticated("/chains", params=params)

    # Explain this line: def get_option_expirations(self, symbol:...
    # Line: def get_option_expirations(self, symbol: str) -> D
    def get_option_expirations(self, symbol: str) -> Dict[str, Any]:
        """
        4. Option Expiration Chain: Calendar list of active expiration dates and days-to-expiration (DTE).
        Parameters:
            symbol: Underlying ticker symbol.
        """
        # Explain this line: if not symbol or not str(symbol).strip()...
        # Line: if not symbol or not str(symbol).strip():
        if not symbol or not str(symbol).strip():
            # Explain this line: raise ValueError("Parameter 'symbol' mus...
            # Line: raise ValueError("Parameter 'symbol' must be a non
            raise ValueError("Parameter 'symbol' must be a non-empty string.")

        # Explain this line: return self._execute_authenticated(...
        # Line: return self._execute_authenticated(
        return self._execute_authenticated(
            # Explain this line: "/expirationchain",...
            # Line: "/expirationchain",
            "/expirationchain",
            # Explain this line: params={"symbol": str(symbol).strip().up...
            # Line: params={"symbol": str(symbol).strip().upper()},
            params={"symbol": str(symbol).strip().upper()},
        # Explain this line: )...
        # Line: )
        )

    # Explain this line: def get_instruments(self, symbol: str, p...
    # Line: def get_instruments(self, symbol: str, projection:
    def get_instruments(self, symbol: str, projection: str = "fundamental") -> Dict[str, Any]:
        """
        5. Instruments: Asset profiles, CUSIP identifiers, and fundamental balance sheet metrics.
        Parameters:
            symbol: Ticker symbol.
            projection: 'symbol-search', 'symbol-regex', 'desc-search', or 'fundamental'.
        """
        # Explain this line: if not symbol or not str(symbol).strip()...
        # Line: if not symbol or not str(symbol).strip():
        if not symbol or not str(symbol).strip():
            # Explain this line: raise ValueError("Parameter 'symbol' mus...
            # Line: raise ValueError("Parameter 'symbol' must be a non
            raise ValueError("Parameter 'symbol' must be a non-empty string.")

        # Explain this line: params = {...
        # Line: params = {
        params = {
            # Explain this line: "symbol": str(symbol).strip().upper(),...
            # Line: "symbol": str(symbol).strip().upper(),
            "symbol": str(symbol).strip().upper(),
            # Explain this line: "projection": projection.lower(),...
            # Line: "projection": projection.lower(),
            "projection": projection.lower(),
        # Explain this line: }...
        # Line: }
        }
        # Explain this line: return self._execute_authenticated("/ins...
        # Line: return self._execute_authenticated("/instruments",
        return self._execute_authenticated("/instruments", params=params)

    # Explain this line: def get_movers(...
    # Line: def get_movers(
    def get_movers(
        # Explain this line: self,...
        # Line: self,
        self,
        # Explain this line: index_symbol: str,...
        # Line: index_symbol: str,
        index_symbol: str,
        # Explain this line: sort_by: str = "VOLUME",...
        # Line: sort_by: str = "VOLUME",
        sort_by: str = "VOLUME",
        # Explain this line: frequency: int = 0,...
        # Line: frequency: int = 0,
        frequency: int = 0,
    # Explain this line: ) -> Dict[str, Any]:...
    # Line: ) -> Dict[str, Any]:
    ) -> Dict[str, Any]:
        """
        6. Movers: Top market movers across benchmark indices ($SPX, $COMPX, $DJI).
        Parameters:
            index_symbol: Index ticker (e.g., '$SPX', '$COMPX', '$DJI'). Required; no default.
            sort_by: 'VOLUME', 'TRADES', 'PERCENT_CHANGE_UP', or 'PERCENT_CHANGE_DOWN'.
            frequency: 0 (all day) or interval minutes (1, 5, 10, 30, 60).
        """
        # Explain this line: if not index_symbol or not str(index_sym...
        # Line: if not index_symbol or not str(index_symbol).strip
        if not index_symbol or not str(index_symbol).strip():
            # Explain this line: raise ValueError("Parameter 'index_symbo...
            # Line: raise ValueError("Parameter 'index_symbol' must be
            raise ValueError("Parameter 'index_symbol' must be a non-empty string.")

        # Explain this line: valid_indices = {"$SPX", "$COMPX", "$DJI...
        # Line: valid_indices = {"$SPX", "$COMPX", "$DJI"}
        valid_indices = {"$SPX", "$COMPX", "$DJI"}
        # Explain this line: target = str(index_symbol).strip().upper...
        # Line: target = str(index_symbol).strip().upper()
        target = str(index_symbol).strip().upper()
        # Explain this line: if target not in valid_indices:...
        # Line: if target not in valid_indices:
        if target not in valid_indices:
            # Explain this line: raise ValueError(f"index_symbol must be ...
            # Line: raise ValueError(f"index_symbol must be one of {va
            raise ValueError(f"index_symbol must be one of {valid_indices}, got '{index_symbol}'")

        # Explain this line: params = {"sort": sort_by.upper(), "freq...
        # Line: params = {"sort": sort_by.upper(), "frequency": fr
        params = {"sort": sort_by.upper(), "frequency": frequency}
        # Explain this line: encoded_index = urllib.parse.quote(targe...
        # Line: encoded_index = urllib.parse.quote(target)
        encoded_index = urllib.parse.quote(target)
        # Explain this line: return self._execute_authenticated(f"/mo...
        # Line: return self._execute_authenticated(f"/movers/{enco
        return self._execute_authenticated(f"/movers/{encoded_index}", params=params)

    # Explain this line: def get_market_hours(self, markets: str ...
    # Line: def get_market_hours(self, markets: str = "equity,
    def get_market_hours(self, markets: str = "equity,option") -> Dict[str, Any]:
        """
        7. Market Hours: Trading session windows across equity, option, bond, and forex markets.
        Parameters:
            markets: Comma-separated list ('equity', 'option', 'bond', 'forex').
        """
        # Explain this line: return self._execute_authenticated("/mar...
        # Line: return self._execute_authenticated("/markets", par
        return self._execute_authenticated("/markets", params={"markets": markets.lower().strip()})

    # -----------------------------------------------------------------------
    # RESOURCE MANAGEMENT
    # -----------------------------------------------------------------------
    # Explain this line: def close(self) -> None:...
    # Line: def close(self) -> None:
    def close(self) -> None:
        """Gracefully tears down underlying HTTP session adapters and connections."""
        # Explain this line: try:...
        # Line: try:
        try:
            # Explain this line: self.session.close()...
            # Line: self.session.close()
            self.session.close()
        # Explain this line: except Exception:...
        # Line: except Exception:
        except Exception:
            # Explain this line: pass...
            # Line: pass
            pass

    # Explain this line: def __enter__(self) -> "SchwabClient":...
    # Line: def __enter__(self) -> "SchwabClient":
    def __enter__(self) -> "SchwabClient":
        # Explain this line: return self...
        # Line: return self
        return self

    # Explain this line: def __exit__(self, exc_type, exc_val, ex...
    # Line: def __exit__(self, exc_type, exc_val, exc_tb) -> N
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Explain this line: self.close()...
        # Line: self.close()
        self.close()