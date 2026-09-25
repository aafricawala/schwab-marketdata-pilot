"""
schwab_auth.py
========================================================================================
CHARLES SCHWAB AUTHENTICATION, CREDENTIALS & SECURE SESSION FACTORY
========================================================================================

WHAT THIS SCRIPT DOES:
----------------------
This module serves as the security backbone and authentication provider for all Charles
Schwab API interactions across the repository. It centralizes credential resolution,
manages local disk token storage paths, enforces strict filesystem permissions, and
acts as a factory for initializing ready-to-use `SchwabClient` session instances.

WHEN AND HOW IT GETS CALLED:
----------------------------
This module is called whenever an authenticated session is needed to interact with Schwab's
REST APIs. It is imported by:
1. `schwab_raw_marketdata.py` to extract live quotes, candle history, and option surfaces.
2. `schwab_vertical_spread_screener.py` to pull options chains for spread analysis.
3. `schwab_audit_cli.py` to run ad-hoc command-line queries and 7-endpoint audits.
4. Notebook coordinator cells (e.g., Cell 2) via `build_schwab_client()`.

KEY FUNCTIONS AND HIGH-LEVEL RESPONSIBILITIES:
---------------------------------------------
1. _get_colab_secret(key):
   - Safely queries Google Colab's native user secrets store (`google.colab.userdata`).
   - Returns the secret value if present; otherwise, catches exceptions silently and
     returns `None` when running outside Colab or when the secret is not found.

2. resolve_credential(key, prompt_label, is_secret=False, interactive=True, ...):
   - Securely looks up required keys (such as `SCHWAB_CLIENT_ID` or `SCHWAB_CLIENT_SECRET`)
     following a strict 4-tier precedence hierarchy:
       1. Custom Enterprise Secret Provider (e.g., AWS Secrets Manager, HashiCorp Vault)
       2. Google Colab User Secrets Vault
       3. Operating System Environment Variables (read-only inspection)
       4. Interactive Prompt (masked via `getpass` for secrets; standard `input` otherwise)
   - Guarantees zero credential leakage: resolved values are kept in ephemeral memory and
     are NEVER written back to `os.environ` or logged.

3. resolve_secure_token_path():
   - Determines the target directory and filename for persisting OAuth access/refresh tokens.
   - Respects user-defined overrides via `SCHWAB_TOKEN_PATH`.
   - In Google Colab with mounted Drive, prioritizes:
     `/content/drive/MyDrive/Colab Notebooks/schwab_market_data/schwab_token.json`
   - Falls back to the user's home directory: `~/.schwab/schwab_token.json`.
   - Enforces POSIX `0o700` directory permissions (read/write/execute restricted strictly
     to the owner) to protect tokens from multi-tenant inspection.

4. build_schwab_client(token_file_path=None, interactive=True, ...):
   - The primary public factory function of this module.
   - Resolves the token storage path, retrieves client credentials via `resolve_credential()`,
     determines the OAuth redirect URI, and instantiates a fully configured `SchwabClient`.

EXCEPTIONS:
-----------
- `OrchestratorError`: Base exception for workflow and orchestration failures.
- `CredentialResolutionError`: Raised when required authentication credentials cannot
  be located across any of the resolution tiers.

IMPORTANT SECURITY PRACTICES:
-----------------------------
- Zero-Pollution Policy: Sensitive API keys and OAuth secrets are never exported into global
  Python state, dumped to terminal logs, or persisted in unprotected plain-text files.
- Decoupled Responsibility: Isolating authentication into this dedicated module ensures that
  testing mathematical models or data schemas does not inadvertently require or trigger
  authentication logic.
========================================================================================
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