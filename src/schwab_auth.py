"""
schwab_auth.py
"""

from __future__ import annotations

import getpass
import logging
import os
import sys
from pathlib import Path
from typing import Callable, Optional, Union

# ---------------------------------------------------------------------------
# PATH RESOLUTION & SAFE IMPORT GUARD
# ---------------------------------------------------------------------------
PROJECT_SRC = (
    Path(__file__).resolve().parent
    if "__file__" in locals()
    else Path("/content/schwab-marketdata-pilot/src")
)
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

try:
    from schwab_client import SchwabClient, SchwabClientError
except ImportError as exc:
    raise ImportError(
        f"FATAL: Unable to load SchwabClient from '{PROJECT_SRC}'. "
        f"Verify file placement and sys.path. Detail: {exc}"
    ) from exc

logger = logging.getLogger("schwab_orchestrator")


class OrchestratorError(SchwabClientError):
    """Base exception for workflow orchestration failures."""


class CredentialResolutionError(OrchestratorError):
    """Raised when authentication credentials cannot be securely located."""


def _get_colab_secret(key: str) -> Optional[str]:
    """Attempts extraction from Google Colab userdata secrets vault."""
    try:
        from google.colab import userdata  # type: ignore
        val = userdata.get(key)
        return str(val).strip() if val else None
    except Exception:
        return None


def resolve_credential(
    key: str,
    prompt_label: str,
    *,
    is_secret: bool = False,
    interactive: bool = True,
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> str:
    """
    Resolves credentials via strict precedence:
      1. Enterprise Secret Provider callback (HashiCorp Vault, AWS Secrets Manager)
      2. Google Colab User Secrets Vault
      3. OS Environment Variable (read-only inspection)
      4. Masked Interactive Prompt (terminal or notebook fallback)

    Crucial Security Rule: Resolved values are NEVER injected back into `os.environ`.
    """
    if secret_provider:
        try:
            val = secret_provider(key)
            if val and val.strip():
                return val.strip()
        except Exception as exc:
            logger.debug("Enterprise secret provider failed for '%s': %s", key, exc)

    colab_val = _get_colab_secret(key)
    if colab_val:
        return colab_val

    env_val = os.environ.get(key)
    if env_val and env_val.strip():
        return env_val.strip()

    if interactive:
        try:
            if is_secret:
                user_val = getpass.getpass(prompt=f"{prompt_label}: ").strip()
            else:
                user_val = input(f"{prompt_label}: ").strip()

            if user_val:
                return user_val
        except (EOFError, KeyboardInterrupt) as exc:
            raise CredentialResolutionError(f"Interactive input aborted for '{key}'.") from exc

    raise CredentialResolutionError(
        f"Missing required credential '{key}'. Provide via Secret Manager, "
        "Colab Secrets, environment variable, or interactive prompt."
    )


def resolve_secure_token_path() -> Path:
    """
    Determines an isolated, permission-controlled path for token persistence.
    Enforces POSIX 0o700 directory permissions to block cross-user inspection.
    """
    explicit_path = os.environ.get("SCHWAB_TOKEN_PATH")
    if explicit_path and explicit_path.strip():
        target = Path(explicit_path).expanduser().resolve()
    else:
        drive_dir = Path("/content/drive/MyDrive/Colab Notebooks/schwab_market_data")
        if drive_dir.exists() and drive_dir.is_dir():
            target = drive_dir / "schwab_token.json"
        else:
            target = Path.home() / ".schwab" / "schwab_token.json"

    parent_dir = target.parent
    parent_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(parent_dir, 0o700)
    except OSError:
        pass
    return target


def build_schwab_client(
    *,
    token_file_path: Optional[Union[str, Path]] = None,
    interactive: bool = True,
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> SchwabClient:
    """
    Factory creating a fully configured SchwabClient instance using secure credential resolution.
    """
    try:
        resolved_token_path = (
            Path(token_file_path).resolve() if token_file_path else resolve_secure_token_path()
        )
        client_id = resolve_credential(
            "SCHWAB_CLIENT_ID",
            "Enter Schwab Client ID (App Key)",
            is_secret=False,
            interactive=interactive,
            secret_provider=secret_provider,
        )
        client_secret = resolve_credential(
            "SCHWAB_CLIENT_SECRET",
            "Enter Schwab Client Secret",
            is_secret=True,
            interactive=interactive,
            secret_provider=secret_provider,
        )
        redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

        return SchwabClient(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            token_file_path=resolved_token_path,
        )
    except Exception as exc:
        logger.error("Client initialization failed: %s", exc)
        raise RuntimeError(f"Schwab client setup error: {exc}") from exc