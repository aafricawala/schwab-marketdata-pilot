"""
schwab_auth.py
---
Purpose
Provides an authentication and client initialization layer for connecting to the Schwab API. It handles secure retrieval of credentials from various sources (Colab secrets, environment variables, interactive prompts) and manages the configuration of the `SchwabClient`.

Prerequisites
Requires a working `SchwabClient` implementation in the same directory or Python path. May require Google Colab (`google.colab`) if running in a Colab environment. Needs Schwab API credentials (client ID and secret) accessible via one of the supported methods.

What this module does
1. Sets up the Python path to ensure the `schwab_client` module can be imported.
2. Defines custom error classes for workflow and credential resolution failures.
3. Attempts to retrieve secrets securely from Google Colab's secret manager, if available.
4. Resolves credentials by checking a provided secret provider, Colab secrets, environment variables, and finally falling back to an interactive prompt if enabled.
5. Determines a secure path to store the Schwab authentication token, applying restrictive permissions to protect it.
6. Builds and returns a fully configured `SchwabClient` instance using the resolved credentials and token path.

Configuration knobs
- `SCHWAB_TOKEN_PATH`: Environment variable to specify a custom path for the token file.
- `SCHWAB_CLIENT_ID`: Environment variable or secret key for the Schwab App Key.
- `SCHWAB_CLIENT_SECRET`: Environment variable or secret key for the Schwab App Secret.
- `SCHWAB_REDIRECT_URI`: Environment variable for the OAuth redirect URI (defaults to "https://127.0.0.1").

Outputs
Provides the `build_schwab_client` factory function which returns a configured `SchwabClient` object. Also provides utility functions like `resolve_credential` and `resolve_secure_token_path`.

Notes
Credentials retrieved are never added back into the environment variables for security. The token file path defaults to a Google Drive location if running in Colab, or a hidden `~/.schwab` folder otherwise, and attempts to set POSIX 0o700 permissions to restrict access.
"""

# Enable modern type hinting features, allowing types to be used before they are defined
from __future__ import annotations

# Import the getpass module for securely prompting for passwords without echoing them
import getpass
# Import the logging module to record diagnostic information and errors
import logging
# Import the os module to interact with the operating system, like reading environment variables
import os
# Import the sys module to manipulate Python runtime environment variables, like the import path
import sys
# Import the Path class from the pathlib module to easily handle file and directory paths
from pathlib import Path
# Import typing helpers to define function signatures for better code clarity
from typing import Callable, Optional, Union

# ---------------------------------------------------------------------------
# PATH RESOLUTION & SAFE IMPORT GUARD
# ---------------------------------------------------------------------------
# Determine the source code directory; use the location of this file if known, otherwise default to a Colab path
PROJECT_SRC = (
    Path(__file__).resolve().parent
    if "__file__" in locals()
    else Path("/content/schwab-marketdata-pilot/src")
)
# Check if our source directory is already in the list of places Python looks for modules
if str(PROJECT_SRC) not in sys.path:
    # If not, add our source directory to the very beginning of the list to prioritize our local modules
    sys.path.insert(0, str(PROJECT_SRC))

# Try to import the SchwabClient and its associated error class from our local module
try:
    from schwab_client import SchwabClient, SchwabClientError
# Catch the case where the module cannot be found
except ImportError as exc:
    # Raise a clear, fatal error explaining that the SchwabClient could not be loaded, and include the reason
    raise ImportError(
        f"FATAL: Unable to load SchwabClient from '{PROJECT_SRC}'. "
        f"Verify file placement and sys.path. Detail: {exc}"
    ) from exc

# Set up a logger specifically for the "schwab_orchestrator" to track events in this module
logger = logging.getLogger("schwab_orchestrator")


# Define a new exception class for general orchestrator errors, inheriting from SchwabClientError
class OrchestratorError(SchwabClientError):
    """Base exception for workflow orchestration failures."""


# Define a more specific exception for when we fail to find necessary login credentials
class CredentialResolutionError(OrchestratorError):
    """Raised when authentication credentials cannot be securely located."""


# Define a helper function to try and get a secret value if we are running in Google Colab
def _get_colab_secret(key: str) -> Optional[str]:
    """Attempts extraction from Google Colab userdata secrets vault."""
    # Start a block that might fail if we aren't in Colab
    try:
        # Try to import the userdata module from the Google Colab package
        from google.colab import userdata  # type: ignore
        # Attempt to retrieve the value associated with the provided key from Colab's secrets
        val = userdata.get(key)
        # If a value was found, convert it to a string and strip extra whitespace; otherwise return nothing
        return str(val).strip() if val else None
    # If any error occurs (like the module not existing), just catch it silently
    except Exception:
        # Return nothing, as we couldn't get the secret
        return None


# Define a function to find a credential value using a priority order of different sources
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
    # Check if a custom function was provided to get secrets (like from a corporate vault)
    if secret_provider:
        # Try to use this custom function
        try:
            # Call the custom function with our key to get the secret value
            val = secret_provider(key)
            # If the function returned a value and it isn't just empty space
            if val and val.strip():
                # Return the cleaned-up value
                return val.strip()
        # Catch any errors that happen when using the custom secret function
        except Exception as exc:
            # Log a debug message explaining that the custom provider failed, but continue trying other methods
            logger.debug("Enterprise secret provider failed for '%s': %s", key, exc)

    # Next, try to get the secret from Google Colab using our helper function
    colab_val = _get_colab_secret(key)
    # If we found a value in Colab
    if colab_val:
        # Return it immediately
        return colab_val

    # Next, check if the value is set as a standard operating system environment variable
    env_val = os.environ.get(key)
    # If an environment variable was found and isn't empty
    if env_val and env_val.strip():
        # Return the cleaned-up environment variable value
        return env_val.strip()

    # Finally, if we are allowed to ask the user directly
    if interactive:
        # Try to prompt the user
        try:
            # If the value is a secret (like a password)
            if is_secret:
                # Use getpass to ask the user without showing what they type, and clean up the input
                user_val = getpass.getpass(prompt=f"{prompt_label}: ").strip()
            # If it's not a secret (like a username)
            else:
                # Use normal input to ask the user, and clean up the input
                user_val = input(f"{prompt_label}: ").strip()

            # If the user actually typed something
            if user_val:
                # Return what they typed
                return user_val
        # Catch cases where the user cancels the input (like pressing Ctrl+C or Ctrl+D)
        except (EOFError, KeyboardInterrupt) as exc:
            # Raise an error saying the user aborted the prompt
            raise CredentialResolutionError(f"Interactive input aborted for '{key}'.") from exc

    # If all methods fail to find the credential, raise an error explaining that it is missing
    raise CredentialResolutionError(
        f"Missing required credential '{key}'. Provide via Secret Manager, "
        "Colab Secrets, environment variable, or interactive prompt."
    )


# Define a function to figure out where to safely save the login token file
def resolve_secure_token_path() -> Path:
    """
    Determines an isolated, permission-controlled path for token persistence.
    Enforces POSIX 0o700 directory permissions to block cross-user inspection.
    """
    # Check if the user explicitly provided a path via an environment variable
    explicit_path = os.environ.get("SCHWAB_TOKEN_PATH")
    # If they did and it's not empty
    if explicit_path and explicit_path.strip():
        # Use that path, expanding any '~' to the user's home directory and resolving it to an absolute path
        target = Path(explicit_path).expanduser().resolve()
    # If no explicit path was provided
    else:
        # Define a path that represents a typical Google Drive folder in Colab
        drive_dir = Path("/content/drive/MyDrive/Colab Notebooks/schwab_market_data")
        # Check if this Google Drive folder actually exists and is a directory
        if drive_dir.exists() and drive_dir.is_dir():
            # If it does, store the token file there
            target = drive_dir / "schwab_token.json"
        # If the Colab Drive folder doesn't exist
        else:
            # Fall back to storing the token in a hidden '.schwab' folder in the user's home directory
            target = Path.home() / ".schwab" / "schwab_token.json"

    # Get the folder where we decided to put the token file
    parent_dir = target.parent
    # Create this folder if it doesn't exist, and create any necessary parent folders too
    parent_dir.mkdir(parents=True, exist_ok=True)
    # Try to set secure permissions on the folder
    try:
        # Change the folder permissions so only the owner can read, write, or access it (0o700)
        os.chmod(parent_dir, 0o700)
    # Catch any errors trying to set permissions (like on Windows where this might not work)
    except OSError:
        # Just ignore the error and proceed
        pass
    # Return the full path to where the token file should be
    return target


# Define a factory function to create and configure a new SchwabClient object
def build_schwab_client(
    *,
    token_file_path: Optional[Union[str, Path]] = None,
    interactive: bool = True,
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> SchwabClient:
    """
    Factory creating a fully configured SchwabClient instance using secure credential resolution.
    """
    # Try to build the client
    try:
        # Determine the token path: use the provided one (resolved to an absolute path) or calculate a secure default
        resolved_token_path = (
            Path(token_file_path).resolve() if token_file_path else resolve_secure_token_path()
        )
        # Call our helper function to find the 'SCHWAB_CLIENT_ID' credential, prompting the user if needed
        client_id = resolve_credential(
            "SCHWAB_CLIENT_ID",
            "Enter Schwab Client ID (App Key)",
            is_secret=False,
            interactive=interactive,
            secret_provider=secret_provider,
        )
        # Call our helper function to securely find the 'SCHWAB_CLIENT_SECRET' credential, hiding user input if prompted
        client_secret = resolve_credential(
            "SCHWAB_CLIENT_SECRET",
            "Enter Schwab Client Secret",
            is_secret=True,
            interactive=interactive,
            secret_provider=secret_provider,
        )
        # Look for a custom redirect URI in environment variables, or use a default local address
        redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

        # Create and return a new SchwabClient using all the gathered credentials and settings
        return SchwabClient(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            token_file_path=resolved_token_path,
        )
    # Catch any errors that happen during this whole setup process
    except Exception as exc:
        # Log a severe error message explaining that client initialization failed
        logger.error("Client initialization failed: %s", exc)
        # Raise a new error describing the problem, linking it back to the original error
        raise RuntimeError(f"Schwab client setup error: {exc}") from exc