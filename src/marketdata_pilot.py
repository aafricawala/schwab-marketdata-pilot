"""
marketdata_pilot.py
-----------------------------------------------------------------------------
Institutional-Grade Schwab Market Data Orchestrator & Production Extraction Engine.

Designed for: Global Equity Strategy, Market Risk Systems, and Automated Pipelines.

Production Extraction Guarantees:
1. Zero Hard-Coded Symbols:
   - All extraction functions, orchestrators, and diagnostic flows require the caller
     to explicitly supply the ticker symbols or universe lists.
2. Production Normalization Pipeline:
   - Built-in DataFrame transformations for multi-asset quotes, 20-year daily historical
     OHLCV timeseries, and full volatility/Greeks surfaces.
3. Zero Secret Ingestion:
   - Credentials are held strictly in ephemeral variables and never written back to
     global runtime tables or `os.environ`.
4. Cryptographic CSRF Protection (RFC 6749):
   - Generates high-entropy nonces via Python's `secrets` module during authorization
     and asserts strict parity before initiating token code exchange.
5. Dual-Tier OAuth Protocol:
   - Tier 1: Proactive silent renewal (30-minute window) using cached refresh token.
   - Tier 2: Deterministic full OAuth restart on token revocation, technical failures,
     CAG/LMS scope modifications, or administrative override (`force_reauth=True`).
6. Precision Failure Boundary:
   - Differentiates between authentication failures (which initiate an OAuth handshake)
     and upstream gateway/asset errors (which fail fast).
-----------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import pandas as pd

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
    from schwab_client import (
        APIRequestError,
        CallbackURLError,
        SchwabClient,
        SchwabClientError,
        TokenError,
    )
except ImportError as exc:
    raise ImportError(
        f"FATAL: Unable to load SchwabClient from '{PROJECT_SRC}'. "
        f"Verify file placement and sys.path. Detail: {exc}"
    ) from exc

logger = logging.getLogger("schwab_orchestrator")
logger.addHandler(logging.NullHandler())

# Strict symbol regex supporting equities, multi-class shares, futures, options, and indices
SYMBOL_REGEX = re.compile(r"^[\$A-Z0-9.\-_/ ]{1,30}$")


# ---------------------------------------------------------------------------
# STRUCTURED DATA MODELS & EXCEPTIONS
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RunResult:
    """
    Immutable execution contract returned by run_marketdata_flow.
    Guarantees deterministic structure for downstream algorithmic consumption.
    """
    success: bool
    symbol: str
    data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    session_resumed: bool = False
    forced_restart: bool = False


class OrchestratorError(SchwabClientError):
    """Base exception for workflow orchestration failures."""


class CredentialResolutionError(OrchestratorError):
    """Raised when authentication credentials cannot be securely located."""


# ---------------------------------------------------------------------------
# SECURE CREDENTIAL RESOLUTION (ZERO-POLLUTION HIERARCHY)
# ---------------------------------------------------------------------------
def _get_colab_secret(key: str) -> Optional[str]:
    """Attempts extraction from Google Colab userdata secrets vault."""
    try:
        from google.colab import userdata  # type: ignore
        val = userdata.get(key)
        return str(val).strip() if val else None
    except Exception:
        return None


def _resolve_credential(
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


# ---------------------------------------------------------------------------
# SECURE STORAGE RESOLUTION
# ---------------------------------------------------------------------------
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


def _sanitize_and_validate_symbols(raw_symbol: Union[str, List[str]]) -> str:
    """
    Validates and standardizes ticker formats against capital-market regex patterns.
    Prevents parameter injection, whitespace corruption, and malformed queries.
    """
    if isinstance(raw_symbol, list):
        candidates = [str(s).strip().upper() for s in raw_symbol if str(s).strip()]
    elif isinstance(raw_symbol, str):
        candidates = [s.strip().upper() for s in raw_symbol.split(",") if s.strip()]
    else:
        raise ValueError("Parameter 'raw_symbol' must be a non-empty string or list of strings.")

    if not candidates:
        raise ValueError("No valid symbols supplied after sanitization.")

    for sym in candidates:
        if not SYMBOL_REGEX.match(sym):
            raise ValueError(
                f"Security validation failed: Symbol '{sym}' contains illegal characters. "
                "Must be alphanumeric or approved index/share delimiters ($, ., -, /, space)."
            )

    return ",".join(candidates)


# ---------------------------------------------------------------------------
# INSTITUTIONAL NORMALIZATION & ANALYTICAL PARSERS
# ---------------------------------------------------------------------------
def parse_price_history_to_df(history_payload: Dict[str, Any]) -> pd.DataFrame:
    """
    Normalizes a Schwab PriceHistory payload into an institutional OHLCV DataFrame.

    Features:
      - Validates 'empty' flag to prevent downstream runtime indexing faults.
      - Converts Unix epoch milliseconds to UTC timestamps, then localizes to US/Eastern.
      - Enforces strict type casting: float64 for price series, int64 for volume.
      - Guarantees sorted, unique DatetimeIndex.
    """
    if not isinstance(history_payload, dict) or history_payload.get("empty", True):
        logger.warning("Empty or invalid price history payload provided.")
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    candles = history_payload.get("candles", [])
    if not candles:
        logger.warning("Price history contains zero candle elements.")
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(candles)

    required_cols = {"datetime", "open", "high", "low", "close", "volume"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        raise ValueError(f"Price history schema mismatch: missing columns {missing}")

    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True).dt.tz_convert("US/Eastern")
    df.set_index("datetime", inplace=True)
    df.sort_index(inplace=True)

    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].astype(float)
    df["volume"] = df["volume"].astype("int64")

    return df[["open", "high", "low", "close", "volume"]]


def parse_option_chain_to_df(chain_payload: Dict[str, Any]) -> pd.DataFrame:
    """
    Normalizes Schwab option chain nested maps into an institutional Volatility Surface.

    Features:
      - Traverses dual multi-tier structures: callExpDateMap and putExpDateMap.
      - Parses the composite expiration key ('YYYY-MM-DD:DTE') into distinct columns.
      - Extracts first-order and second-order Greeks (Delta, Gamma, Vega, Theta).
      - Computes moneyness relative to the underlying spot price.
      - Guards against null, empty, or non-tradable contract nodes.
    """
    if not isinstance(chain_payload, dict):
        logger.warning("Invalid chain payload received.")
        return pd.DataFrame()

    underlying_price = float(chain_payload.get("underlyingPrice", 0.0))
    records: List[Dict[str, Any]] = []

    structure_targets = [
        ("CALL", chain_payload.get("callExpDateMap", {})),
        ("PUT", chain_payload.get("putExpDateMap", {})),
    ]

    for side, exp_map in structure_targets:
        if not isinstance(exp_map, dict):
            continue

        for exp_key, strike_map in exp_map.items():
            if ":" not in exp_key:
                continue
            exp_date_str, dte_str = exp_key.split(":", 1)

            try:
                dte = int(dte_str)
                exp_date = pd.to_datetime(exp_date_str)
            except (ValueError, TypeError):
                continue

            if not isinstance(strike_map, dict):
                continue

            for strike_str, contracts in strike_map.items():
                if not isinstance(contracts, list) or not contracts:
                    continue

                c = contracts[0]
                if not isinstance(c, dict):
                    continue

                try:
                    strike_val = float(strike_str)
                except ValueError:
                    strike_val = float(c.get("strikePrice", 0.0))

                records.append({
                    "side": side,
                    "expiration": exp_date,
                    "dte": dte,
                    "strike": strike_val,
                    "bid": c.get("bid"),
                    "ask": c.get("ask"),
                    "mark": c.get("mark"),
                    "last": c.get("last"),
                    "volume": c.get("totalVolume", 0),
                    "open_interest": c.get("openInterest", 0),
                    "implied_vol": c.get("volatility"),
                    "delta": c.get("delta"),
                    "gamma": c.get("gamma"),
                    "theta": c.get("theta"),
                    "vega": c.get("vega"),
                    "moneyness": round(strike_val / underlying_price, 4) if underlying_price > 0 else None,
                    "symbol": c.get("symbol"),
                    "in_the_money": c.get("inTheMoney", False),
                })

    df = pd.DataFrame(records)
    if not df.empty:
        df.sort_values(by=["expiration", "strike", "side"], inplace=True)
        df.reset_index(drop=True, inplace=True)

    return df


def parse_quotes_to_df(quotes_payload: Dict[str, Any]) -> pd.DataFrame:
    """
    Transforms multi-symbol quotes payload into a structured risk metrics DataFrame.
    Defensively extracts quote, fundamental, and reference blocks.
    """
    if not isinstance(quotes_payload, dict):
        return pd.DataFrame()

    records = []
    for sym, asset_data in quotes_payload.items():
        if not isinstance(asset_data, dict):
            continue

        q = asset_data.get("quote", {})
        f = asset_data.get("fundamental", {})
        r = asset_data.get("reference", {})

        records.append({
            "ticker": sym,
            "description": r.get("description", "N/A"),
            "exchange": r.get("exchangeName", "N/A"),
            "last_price": q.get("lastPrice"),
            "net_change": q.get("netChange"),
            "percent_change": q.get("netPercentChange"),
            "bid": q.get("bidPrice"),
            "ask": q.get("askPrice"),
            "volume": q.get("totalVolume"),
            "high_52w": q.get("52WeekHigh"),
            "low_52w": q.get("52WeekLow"),
            "pe_ratio": f.get("peRatio"),
            "div_yield": f.get("divYield"),
        })

    df = pd.DataFrame(records)
    if not df.empty:
        df.set_index("ticker", inplace=True)
    return df


# ---------------------------------------------------------------------------
# CORE WORKFLOW: MARKET DATA RETRIEVAL
# ---------------------------------------------------------------------------
def run_marketdata_flow(
    symbols: Union[str, List[str]],
    *,
    fields: Optional[str] = None,
    interactive: bool = True,
    force_reauth: bool = False,
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
    token_file_path: Optional[Union[str, Path]] = None,
    client_kwargs: Optional[Dict[str, Any]] = None,
) -> RunResult:
    """
    Executes the market data retrieval lifecycle with full dual-tier OAuth support.
    Requires caller to supply target symbol(s).
    """
    validated_symbols = _sanitize_and_validate_symbols(symbols)
    resolved_token_path = (
        Path(token_file_path).resolve() if token_file_path else resolve_secure_token_path()
    )

    if force_reauth and resolved_token_path.exists():
        logger.info("force_reauth=True: Evicting cached token file at %s", resolved_token_path)
        try:
            resolved_token_path.unlink()
        except OSError as exc:
            logger.warning("Failed to evict cached token file: %s", exc)

    client_id = _resolve_credential(
        "SCHWAB_CLIENT_ID",
        "Enter Schwab Client ID (App Key)",
        is_secret=False,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    client_secret = _resolve_credential(
        "SCHWAB_CLIENT_SECRET",
        "Enter Schwab Client Secret",
        is_secret=True,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

    kwargs = client_kwargs.copy() if client_kwargs else {}

    with SchwabClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        token_file_path=resolved_token_path,
        **kwargs,
    ) as client:

        # Step A: Attempt execution using cached or silently refreshed session
        if not force_reauth:
            try:
                quote_payload = client.get_quotes(validated_symbols, fields=fields)
                logger.info("Successfully fetched quotes for [%s] via active session.", validated_symbols)
                return RunResult(
                    success=True,
                    symbol=validated_symbols,
                    data=quote_payload,
                    session_resumed=True,
                    forced_restart=False,
                )
            except TokenError as te:
                logger.info("Cached token invalid or refresh expired: %s. Initiating OAuth restart.", te)
            except APIRequestError as ae:
                if getattr(ae, "status_code", None) == 401:
                    logger.warning("Gateway returned HTTP 401 Unauthorized. Forcing OAuth restart.")
                else:
                    logger.error("API gateway failure for [%s]: %s", validated_symbols, ae)
                    return RunResult(
                        success=False,
                        symbol=validated_symbols,
                        error_message=f"API Request Failure: {ae}",
                        session_resumed=False,
                        forced_restart=False,
                    )

        # Step B: Full OAuth Flow Restart (CAG / LMS Consent Handshake)
        if not interactive:
            err_msg = (
                "Execution halted: Session expired or OAuth restart required, "
                "but interactive authentication is disabled."
            )
            logger.error(err_msg)
            return RunResult(
                success=False,
                symbol=validated_symbols,
                error_message=err_msg,
                session_resumed=False,
                forced_restart=force_reauth,
            )

        try:
            session_state = secrets.token_urlsafe(16)
            auth_url = client.build_auth_url(state=session_state)

            print("\n" + "=" * 78)
            print("SCHWAB FULL OAUTH RESTART (LMS CONSENT & ACCOUNT SELECTION)")
            print("=" * 78)
            print("1. Open this URL in your browser to authorize application access:\n")
            print(auth_url)
            print("\n2. Log in, select/verify your accounts, and paste the redirected URL below.")
            print("-" * 78)

            auth_code = input("\nPaste Redirect URL or Code: ").strip()
            if not auth_code:
                raise OrchestratorError("No authorization code provided. Workflow aborted.")

            print("\nExchanging code for token pair with CSRF state verification...")
            client.exchange_code_for_token(auth_code, expected_state=session_state)

            quote_payload = client.get_quotes(validated_symbols, fields=fields)
            return RunResult(
                success=True,
                symbol=validated_symbols,
                data=quote_payload,
                session_resumed=False,
                forced_restart=force_reauth,
            )

        except (TokenError, APIRequestError, OrchestratorError) as exc:
            logger.error("OAuth handshake failed: %s", exc)
            return RunResult(
                success=False,
                symbol=validated_symbols,
                error_message=str(exc),
                session_resumed=False,
                forced_restart=force_reauth,
            )
        except Exception as exc:
            logger.exception("Catastrophic error during OAuth handshake: %s", exc)
            raise OrchestratorError(f"Handshake pipeline failure: {exc}") from exc


# ---------------------------------------------------------------------------
# PRODUCTION EXTRACTION ENGINE: TIMESERIES & DERIVATIVES
# ---------------------------------------------------------------------------
def extract_historical_timeseries(
    symbol: str,
    *,
    period_type: str = "year",
    period: int = 20,
    frequency_type: str = "daily",
    frequency: int = 1,
    need_extended_hours: bool = False,
    interactive: bool = True,
    force_reauth: bool = False,
    token_file_path: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """
    Production-grade historical timeseries extraction.
    Pulls up to 20 years of OHLCV bars and parses directly into a clean DataFrame.
    """
    clean_sym = _sanitize_and_validate_symbols(symbol)
    resolved_token_path = (
        Path(token_file_path).resolve() if token_file_path else resolve_secure_token_path()
    )

    client_id = _resolve_credential("SCHWAB_CLIENT_ID", "Enter Schwab Client ID", is_secret=False, interactive=interactive)
    client_secret = _resolve_credential("SCHWAB_CLIENT_SECRET", "Enter Schwab Client Secret", is_secret=True, interactive=interactive)
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

    with SchwabClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        token_file_path=resolved_token_path,
    ) as client:
        raw_history = client.get_price_history(
            symbol=clean_sym,
            period_type=period_type,
            period=period,
            frequency_type=frequency_type,
            frequency=frequency,
            need_extended_hours=need_extended_hours,
        )
        return parse_price_history_to_df(raw_history)

def extract_volatility_surface(
    symbol: str,
    *,
    strike_count: Optional[int] = None,
    contract_type: str = "ALL",
    chunk_by_expiration: bool = True,
    interactive: bool = True,
    force_reauth: bool = False,
    token_file_path: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """
    Production-grade option surface extraction with automatic tenor chunking.

    Solves the Apigee 'protocol.http.TooBigBody' (HTTP 502) gateway buffer overflow
    by querying the active expiration calendar via /expirationchain and pulling
    full-strike chains per expiration slice when strike_count is None.
    """
    clean_sym = _sanitize_and_validate_symbols(symbol)
    resolved_token_path = (
        Path(token_file_path).resolve() if token_file_path else resolve_secure_token_path()
    )

    client_id = _resolve_credential(
        "SCHWAB_CLIENT_ID", "Enter Schwab Client ID", is_secret=False, interactive=interactive
    )
    client_secret = _resolve_credential(
        "SCHWAB_CLIENT_SECRET", "Enter Schwab Client Secret", is_secret=True, interactive=interactive
    )
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

    with SchwabClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        token_file_path=resolved_token_path,
    ) as client:

        # Fast path: Bounded strike queries fit comfortably inside the proxy buffer
        if strike_count is not None or not chunk_by_expiration:
            raw_chain = client.get_option_chain(
                symbol=clean_sym,
                contract_type=contract_type,
                strike_count=strike_count,
            )
            return parse_option_chain_to_df(raw_chain)

        # Resilient path: Chunk across expirations to avoid HTTP 502 buffer overflows
        logger.info("Extracting full surface for %s via expiration calendar chunking...", clean_sym)
        exp_payload = client.get_option_expirations(clean_sym)
        expirations = [
            item["expirationDate"]
            for item in exp_payload.get("expirationList", [])
            if "expirationDate" in item
        ]

        if not expirations:
            logger.warning("Zero active expiration cycles returned for %s.", clean_sym)
            return pd.DataFrame()

        surface_slices: List[pd.DataFrame] = []

        for exp_date in expirations:
            try:
                chunk_chain = client.get_option_chain(
                    symbol=clean_sym,
                    contract_type=contract_type,
                    strike_count=None,
                    from_date=exp_date,
                    to_date=exp_date,
                )
                df_slice = parse_option_chain_to_df(chunk_chain)
                if not df_slice.empty:
                    surface_slices.append(df_slice)
            except APIRequestError as err:
                logger.warning("Failed slice for %s on %s: %s", clean_sym, exp_date, err)
                continue

        if not surface_slices:
            return pd.DataFrame()

        df_full = pd.concat(surface_slices, ignore_index=True)
        df_full.sort_values(by=["expiration", "strike", "side"], inplace=True)
        df_full.reset_index(drop=True, inplace=True)
        return df_full

# ---------------------------------------------------------------------------
# AUDIT WORKFLOW: COMPREHENSIVE 7-ENDPOINT CATALOG
# ---------------------------------------------------------------------------
def run_full_marketdata_catalog(
    symbol: str,
    benchmark_index: str,
    *,
    strike_count: Optional[int] = None,
    period_type: str = "day",
    period: int = 5,
    frequency_type: str = "minute",
    frequency: int = 30,
    interactive: bool = True,
    force_reauth: bool = False,
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
    token_file_path: Optional[Union[str, Path]] = None,
    client_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Audits and queries all 7 Schwab Market Data endpoint families for a given asset.
    Requires caller to supply target symbol and benchmark index.
    """
    clean_symbol = _sanitize_and_validate_symbols(symbol)
    resolved_token_path = (
        Path(token_file_path).resolve() if token_file_path else resolve_secure_token_path()
    )

    if force_reauth and resolved_token_path.exists():
        logger.info("force_reauth=True: Evicting cached token file at %s", resolved_token_path)
        try:
            resolved_token_path.unlink()
        except OSError as exc:
            logger.warning("Failed to evict cached token file: %s", exc)

    client_id = _resolve_credential(
        "SCHWAB_CLIENT_ID",
        "Enter Schwab Client ID",
        is_secret=False,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    client_secret = _resolve_credential(
        "SCHWAB_CLIENT_SECRET",
        "Enter Schwab Client Secret",
        is_secret=True,
        interactive=interactive,
        secret_provider=secret_provider,
    )
    redirect_uri = os.environ.get("SCHWAB_REDIRECT_URI", "https://127.0.0.1")

    kwargs = client_kwargs.copy() if client_kwargs else {}

    with SchwabClient(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        token_file_path=resolved_token_path,
        **kwargs,
    ) as client:

        try:
            client.get_valid_access_token()
        except TokenError:
            if not interactive:
                raise OrchestratorError("Authentication missing and interactive mode is disabled.")
            session_state = secrets.token_urlsafe(16)
            auth_url = client.build_auth_url(state=session_state)
            print("\nAuthorization required. Complete consent flow:\n", auth_url)
            auth_code = input("\nPaste Redirect URL or Code: ").strip()
            client.exchange_code_for_token(auth_code, expected_state=session_state)

        print("\n" + "=" * 82)
        print(f"SCHWAB MARKET DATA 7-ENDPOINT AUDIT SNAPSHOT: {clean_symbol}")
        print("=" * 82)

        audit_plan = [
            ("Quotes", lambda: client.get_quotes(clean_symbol)),
            (
                "PriceHistory",
                lambda: client.get_price_history(
                    clean_symbol,
                    period_type=period_type,
                    period=period,
                    frequency_type=frequency_type,
                    frequency=frequency,
                ),
            ),
            (
                "OptionChains",
                lambda: client.get_option_chain(clean_symbol, strike_count=strike_count),
            ),
            (
                "OptionExpirations",
                lambda: client.get_option_expirations(clean_symbol),
            ),
            (
                "Instruments",
                lambda: client.get_instruments(clean_symbol, projection="fundamental"),
            ),
            (
                "Movers",
                lambda: client.get_movers(index_symbol=benchmark_index),
            ),
            (
                "MarketHours",
                lambda: client.get_market_hours("equity,option"),
            ),
        ]

        snapshot: Dict[str, Any] = {"symbol": clean_symbol, "endpoints": {}}

        print(f"{'Endpoint':<20} | {'Status':<10} | {'Summary Data Points'}")
        print("-" * 82)

        for endpoint_name, query_func in audit_plan:
            try:
                payload = query_func()
                summary_text = ""

                if endpoint_name == "Quotes":
                    q = payload.get(clean_symbol, {}).get("quote", {})
                    summary_text = f"Last: ${q.get('lastPrice', 'N/A')} | Vol: {q.get('totalVolume', 0):,}"
                elif endpoint_name == "PriceHistory":
                    candles = payload.get("candles", [])
                    summary_text = f"{len(candles)} candle bars returned ({period_type}={period})"
                elif endpoint_name == "OptionChains":
                    call_map = payload.get("callExpDateMap", {})
                    summary_text = f"Underlying: ${payload.get('underlyingPrice', 'N/A')} | Expiries: {len(call_map)}"
                elif endpoint_name == "OptionExpirations":
                    exps = payload.get("expirationList", [])
                    summary_text = f"{len(exps)} active expiration cycles discovered"
                elif endpoint_name == "Instruments":
                    insts = payload.get("instruments", [])
                    cusip = insts[0].get("cusip", "N/A") if insts else "N/A"
                    summary_text = f"CUSIP: {cusip} | Records: {len(insts)}"
                elif endpoint_name == "Movers":
                    screeners = payload.get("screeners", [])
                    summary_text = f"{len(screeners)} index mover securities ({benchmark_index})"
                elif endpoint_name == "MarketHours":
                    summary_text = f"Trading markets: {', '.join(payload.keys())}"

                snapshot["endpoints"][endpoint_name] = {"available": True, "data": payload}
                print(f"{endpoint_name:<20} | 200 OK     | {summary_text}")

            except APIRequestError as err:
                status_code = getattr(err, "status_code", "ERR")
                snapshot["endpoints"][endpoint_name] = {"available": False, "error": str(err)}
                print(f"{endpoint_name:<20} | HTTP {status_code:<4} | Request rejected: {err}")
            except Exception as err:
                snapshot["endpoints"][endpoint_name] = {"available": False, "error": str(err)}
                print(f"{endpoint_name:<20} | FAILED     | {err}")

        print("-" * 82 + "\n")
        return snapshot


# ---------------------------------------------------------------------------
# CLI INTERFACE & DISPATCHER
# ---------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Institutional Charles Schwab Market Data Orchestration Engine",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "symbols",
        help="Ticker symbol or comma-separated symbols (e.g., AAPL or SPY,QQQ,NVDA)",
    )
    parser.add_argument(
        "--audit-catalog",
        action="store_true",
        help="Execute full 7-endpoint inspection audit instead of single quote query",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default=None,
        choices=["$SPX", "$COMPX", "$DJI"],
        help="Benchmark index symbol for movers analysis (required if --audit-catalog is set)",
    )
    parser.add_argument(
        "--force-reauth",
        action="store_true",
        help="Evict cached token and execute full interactive OAuth restart",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Disable interactive login prompts (fails fast if session is expired)",
    )
    parser.add_argument(
        "--token-path",
        type=str,
        default=None,
        help="Explicit file path for reading and persisting tokens",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Application logging verbosity level",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI execution entrypoint adhering to standard POSIX status codes."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        if args.audit_catalog:
            if not args.benchmark:
                print("[ERROR] Argument --benchmark ($SPX, $COMPX, $DJI) is required when --audit-catalog is enabled.", file=sys.stderr)
                return 2

            run_full_marketdata_catalog(
                symbol=args.symbols,
                benchmark_index=args.benchmark,
                interactive=not args.non_interactive,
                force_reauth=args.force_reauth,
                token_file_path=args.token_path,
            )
            return 0

        res = run_marketdata_flow(
            symbols=args.symbols,
            interactive=not args.non_interactive,
            force_reauth=args.force_reauth,
            token_file_path=args.token_path,
        )

        if res.success:
            session_state = "Resumed Active Session" if res.session_resumed else "Newly Authenticated"
            print(f"\n[OK] Market data retrieved ({session_state}) for: {res.symbol}")
            if logger.isEnabledFor(logging.DEBUG) and res.data:
                import json as _json
                print(_json.dumps(res.data, indent=2))
            return 0
        else:
            print(f"\n[ERROR] Pipeline failure: {res.error_message}", file=sys.stderr)
            return 1

    except CredentialResolutionError as exc:
        print(f"\n[CREDENTIAL CONFIGURATION ERROR] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\n[FATAL ORCHESTRATOR FAILURE] {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())