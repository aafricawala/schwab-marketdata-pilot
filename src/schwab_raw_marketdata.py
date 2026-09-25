"""
schwab_raw_marketdata.py
========================================================================================
CHARLES SCHWAB IN-MEMORY RAW DATA INGESTION & NORMALIZATION ENGINE
========================================================================================

WHAT THIS SCRIPT DOES:
----------------------
This module serves as the primary extraction and normalization engine for raw Charles
Schwab Market Data. It bridges the low-level HTTP client (`schwab_client.py`) and the
analytical modeling engine (`schwab_marketdata_calculator.py`).

Its core responsibilities include:
  - Ticker validation against standardized capital-market regex patterns.
  - Converting raw, nested API responses into structured pandas DataFrames (OHLCV price
    history, option contract chains, multi-asset quote summaries).
  - Executing thesis-specific in-memory extraction workflows (underlying fundamentals,
    market hours status, expiration calendar filtering, and targeted option chain queries).
  - Providing end-to-end production extraction pipelines for deep historical timeseries
    (up to 20 years) and full expiration-chunked volatility surfaces.

WHEN AND HOW IT GETS CALLED:
----------------------------
1. Notebook Master Pipeline Coordinator (Cell 2):
   Called directly inside `run_master_pipeline()` to pull all necessary in-memory market
   structures for a target ticker:
     - `extract_market_open_status()`: Validates if regular cash sessions are active.
     - `extract_strict_underlying_data()`: Pulls quotes, fundamentals, and borrow status.
     - `extract_in_memory_price_history()`: Fetches OHLCV bars for volatility lookbacks.
     - `extract_in_memory_option_expirations()` & `resolve_optimal_expirations()`: Identifies
       front-month and ~30-DTE tenors.
     - `extract_in_memory_option_chains()`: Retrieves targeted strikes for skew and straddle
       pricing.

2. Spread Screeners & Standalone Analytics:
   Imported by `schwab_vertical_spread_screener.py` to reuse `sanitize_and_validate_symbols()`.

3. Standalone Historical & Surface Extractions:
   Called programmatically to retrieve full historical price datasets or complete multi-cycle
   option surfaces via `extract_historical_timeseries()` and `extract_volatility_surface()`.

KEY FUNCTIONS AND HIGH-LEVEL RESPONSIBILITIES:
---------------------------------------------
1. sanitize_and_validate_symbols(raw_symbol):
   - Cleans, uppercases, and validates tickers against standard exchange regex patterns.
   - Rejects invalid characters and prevents malformed query strings from hitting the API gateway.

2. Normalization Parsers (DataFrame Builders):
   - parse_price_history_to_df(history_payload):
       Transforms raw candle arrays into timezone-aware (US/Eastern) indexed OHLCV DataFrames.
   - parse_option_chain_to_df(chain_payload):
       Unpacks deeply nested Call and Put expiration/strike maps into a flat tabular
       volatility surface containing Greeks, IV, moneyness, marks, and open interest.
   - parse_quotes_to_df(quotes_payload):
       Flattens multi-symbol quote dictionaries into a structured risk metrics table.

3. In-Memory Thesis Extraction Routines:
   - extract_market_open_status(client, tz):
       Queries the `/markets` endpoint to verify if equity trading is active today.
   - extract_strict_underlying_data(client, symbol, tz):
       Extracts grounding quotes, fundamental valuation ratios (P/E, margins, float, debt),
       and short locate status (`isShortable`, `isHardToBorrow`, `htbRate`). Implements
       fallback reconciliation between the Quotes and Instruments endpoints.
   - extract_in_memory_price_history(client, symbol, config):
       Extracts historical candles strictly in-memory for downstream realized volatility engines.
   - extract_in_memory_option_expirations(client, symbol) & resolve_optimal_expirations(...):
       Inspects all expiration cycles and resolves the front-month and ~30-DTE target dates.
   - extract_in_memory_option_chains(client, symbol, target_expirations, ...):
       Extracts compact, strike-constrained contract chains for the resolved expirations
       to calculate 25-delta skew and ATM straddles without downloading unnecessary chain bloat.

4. Production Timeseries & Surface Routines:
   - extract_historical_timeseries(symbol, ...):
       Pulls multi-year OHLCV bars directly into a pandas DataFrame using automated client setup.
   - extract_volatility_surface(symbol, ...):
       Extracts full option chains across every active expiration cycle by automatically chunking
       requests per expiration date, bypassing API payload size limits and gateway timeouts.

IMPORTANT ARCHITECTURAL CONSIDERATIONS:
---------------------------------------
- Pure Data Ingestion: This module performs zero quantitative modeling (no Black-Scholes,
  no floor pivots, no realized vol math) and zero file serialization; it strictly ingests,
  normalizes, and structures market data.
- Transient Memory Focus: In-memory functions return lightweight Python dictionaries and
  DataFrames directly to the caller, preventing intermediate CSV/JSON disk clutter.
- Resilient Error Handling: Extraction routines log non-fatal warnings and return safe
  fallbacks (e.g., empty DataFrames or `None`) to ensure downstream pipelines degrade
  gracefully rather than crashing outright.
========================================================================================

ENGINEERING AUDIT REMEDIATION SUMMARY:
--------------------------------------
DEF-OUT-01: Cleans OHLCV strings (strips '$' and ',') upstream before creating records
            so DataFrame coercion downstream will not yield 100% NaN rows.
DEF-OUT-02: Explicitly extracts 'bid' and 'ask' in `extract_in_memory_option_chains()`
            to unblock straddle liquidity and spread validation gates.
DEF-10:     Forces `include_underlying_quote=True` on option chain pulls to capture
            and forward contemporaneous root-level `underlyingPrice`.
DEF-OUT-03: Slices fundamental ratios (`pbRatio`, `pcfRatio`, debt, margins) with fallback
            reconciliation across Quotes and Instruments endpoints.
========================================================================================
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

import pandas as pd

from schwab_auth import (
    CredentialResolutionError,
    OrchestratorError,
    build_schwab_client,
    resolve_credential,
    resolve_secure_token_path,
)
from schwab_client import (
    APIRequestError,
    SchwabClient,
    TokenError,
)

logger = logging.getLogger("schwab_orchestrator")
logger.addHandler(logging.NullHandler())

# Strict symbol regex supporting equities, multi-class shares, futures, options, and indices
SYMBOL_REGEX = re.compile(r"^[\$A-Z0-9.\-_/ ]{1,30}$")


@dataclass(frozen=True)
class RunResult:
    """Immutable execution contract returned by standalone execution flows."""
    success: bool
    symbol: str
    data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    session_resumed: bool = False
    forced_restart: bool = False


def sanitize_and_validate_symbols(raw_symbol: Union[str, List[str]]) -> str:
    """Validates and standardizes ticker formats against capital-market regex patterns."""
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
                f"Security validation failed: Symbol '{sym}' contains illegal characters."
            )
    return ",".join(candidates)


def _clean_numeric_val(val: Any) -> Any:
    """Helper to strip currency and comma characters from raw scalar values."""
    if isinstance(val, str):
        cleaned = val.strip().replace("$", "").replace(",", "")
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return val
    return val


# ---------------------------------------------------------------------------
# NORMALIZATION & ANALYTICAL PARSERS
# ---------------------------------------------------------------------------
def parse_price_history_to_df(history_payload: Dict[str, Any]) -> pd.DataFrame:
    """Normalizes a Schwab PriceHistory payload into a clean OHLCV DataFrame."""
    if not isinstance(history_payload, dict) or history_payload.get("empty", True):
        logger.warning("Empty or invalid price history payload provided.")
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

    candles = history_payload.get("candles", [])
    if not candles:
        logger.warning("Price history contains zero candle elements.")
        return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(candles)
    required_cols = {"datetime", "open", "high", "low", "close", "volume"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        raise ValueError(f"Price history schema mismatch: missing columns {missing}")

    # DEF-OUT-01: Sanitize OHLCV columns upstream before DataFrame typing
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            if df[col].dtype == object:
                df[col] = (
                    df[col]
                    .astype(str)
                    .str.replace("$", "", regex=False)
                    .str.replace(",", "", regex=False)
                    .str.strip()
                )
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Retain integer epoch milliseconds in datetime for monotonic sorting
    df["datetime"] = pd.to_numeric(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime", "high", "low", "close"])
    df = df.sort_values("datetime", ascending=True).reset_index(drop=True)

    return df[["datetime", "open", "high", "low", "close", "volume"]]


def parse_option_chain_to_df(chain_payload: Dict[str, Any]) -> pd.DataFrame:
    """Normalizes Schwab option chain nested maps into a flat tabular Volatility Surface."""
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
                    "bid": _clean_numeric_val(c.get("bid")),
                    "ask": _clean_numeric_val(c.get("ask")),
                    "mark": _clean_numeric_val(c.get("mark")),
                    "last": _clean_numeric_val(c.get("last")),
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
    """Transforms multi-symbol quotes payload into a structured risk metrics DataFrame."""
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
            "last_price": _clean_numeric_val(q.get("lastPrice")),
            "net_change": _clean_numeric_val(q.get("netChange")),
            "percent_change": _clean_numeric_val(q.get("netPercentChange")),
            "bid": _clean_numeric_val(q.get("bidPrice")),
            "ask": _clean_numeric_val(q.get("askPrice")),
            "volume": q.get("totalVolume"),
            "high_52w": _clean_numeric_val(q.get("52WeekHigh")),
            "low_52w": _clean_numeric_val(q.get("52WeekLow")),
            "pe_ratio": f.get("peRatio"),
            "div_yield": f.get("divYield"),
        })

    df = pd.DataFrame(records)
    if not df.empty:
        df.set_index("ticker", inplace=True)
    return df


# ---------------------------------------------------------------------------
# IN-MEMORY THESIS EXTRACTION ROUTINES
# ---------------------------------------------------------------------------
def extract_market_open_status(client: SchwabClient, tz: ZoneInfo) -> Optional[bool]:
    """Queries Schwab to determine whether regular equity trading is active today."""
    try:
        now_et = datetime.now(timezone.utc).astimezone(tz)
        date_str = now_et.strftime("%Y-%m-%d")
        if hasattr(client, "get_market_hours"):
            try:
                raw_hours = client.get_market_hours("equity")
            except TypeError:
                try:
                    raw_hours = client.get_market_hours(markets="equity")
                except TypeError:
                    raw_hours = client.get_market_hours()

            if isinstance(raw_hours, dict):
                if "isOpen" in raw_hours:
                    return bool(raw_hours.get("isOpen", False))
                eq_hours = raw_hours.get("equity", {}).get("EQ", {})
                if "isOpen" in eq_hours:
                    return bool(eq_hours.get("isOpen", False))
    except Exception as exc:
        logger.warning("MarketHours retrieval skipped: %s", exc)
    return None


def extract_strict_underlying_data(client: SchwabClient, symbol: str, tz: ZoneInfo) -> Dict[str, Any]:
    """
    Extracts quotes, fundamentals, and borrow status for the underlying security.
    Resolves missing values across primary Quote and secondary Instruments payloads.
    """
    clean_sym = sanitize_and_validate_symbols(symbol)
    raw_payload = client.get_quote(symbol=clean_sym, fields="quote,fundamental,reference")
    payload = raw_payload.get(clean_sym, raw_payload)

    quote_c = payload.get("quote", {})
    fund_c = payload.get("fundamental", {})
    ref_c = payload.get("reference", {})

    inst_fund_c = {}
    try:
        if hasattr(client, "get_instruments"):
            inst_payload = client.get_instruments(symbol=clean_sym, projection="fundamental")
            inst_list = inst_payload.get("instruments", [])
            if inst_list and isinstance(inst_list, list):
                inst_fund_c = inst_list[0].get("fundamental", {})
            elif isinstance(inst_payload, dict):
                inst_fund_c = inst_payload.get("fundamental", {})
    except Exception as exc:
        logger.info("Instruments secondary query skipped: %s", exc)

    def resolve(field: str) -> Any:
        val = fund_c.get(field)
        return inst_fund_c.get(field) if (val is None or pd.isna(val)) else val

    quote_epoch = quote_c.get("quoteTime")
    quote_iso = None
    if quote_epoch and not pd.isna(quote_epoch) and quote_epoch > 0:
        quote_iso = datetime.fromtimestamp(quote_epoch / 1000.0, tz=timezone.utc).astimezone(tz).isoformat()

    return {
        "phase_0_grounding": {
            "symbol": clean_sym,
            "lastPrice": _clean_numeric_val(quote_c.get("lastPrice")),
            "quoteTime_ISO_ET": quote_iso,
            "closePrice": _clean_numeric_val(quote_c.get("closePrice")),
        },
        "step_1_fundamentals": {
            "beta": resolve("beta"),
            "peRatio": resolve("peRatio"),
            "pegRatio": resolve("pegRatio"),
            "pbRatio": resolve("pbRatio"),
            "prRatio": resolve("prRatio"),
            "pcfRatio": resolve("pcfRatio"),
            "quickRatio": resolve("quickRatio"),
            "currentRatio": resolve("currentRatio"),
            "totalDebtToEquity": resolve("totalDebtToEquity"),
            "grossMarginTTM": resolve("grossMarginTTM"),
            "netProfitMarginTTM": resolve("netProfitMarginTTM"),
            "operatingMarginTTM": resolve("operatingMarginTTM"),
            "returnOnEquity": resolve("returnOnEquity"),
            "returnOnAssets": resolve("returnOnAssets"),
            "eps": resolve("eps"),
            "revChangeYear": resolve("revChangeYear"),
            "divYield": resolve("divYield"),
            "divAmount": _clean_numeric_val(resolve("divAmount")),
            "divFreq": resolve("divFreq"),
            "divDate": resolve("divDate"),
            "sharesOutstanding": resolve("sharesOutstanding"),
            "sharesFloat": resolve("sharesFloat"),
        },
        "step_3_short_reference": {
            "isShortable": ref_c.get("isShortable"),
            "isHardToBorrow": ref_c.get("isHardToBorrow"),
            "htbRate": ref_c.get("htbRate"),
        },
        "step_8_liquidity_sizing": {
            "bidPrice": _clean_numeric_val(quote_c.get("bidPrice")),
            "askPrice": _clean_numeric_val(quote_c.get("askPrice")),
            "bidSize": quote_c.get("bidSize"),
            "askSize": quote_c.get("askSize"),
            "totalVolume": quote_c.get("totalVolume"),
            "vol10DayAvg": fund_c.get("vol10DayAvg"),
            "vol3MonthAvg": fund_c.get("vol3MonthAvg"),
        },
    }


def extract_in_memory_price_history(
    client: SchwabClient,
    symbol: str,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Fetches historical daily price candles in-memory.
    Enforces DEF-OUT-01 currency stripping so downstream calculators receive numeric OHLCV bars.
    """
    clean_sym = sanitize_and_validate_symbols(symbol)
    cfg = config or {}
    try:
        raw = client.get_price_history(
            symbol=clean_sym,
            period_type=cfg.get("HISTORICAL_PERIOD_TYPE", "year"),
            period=cfg.get("HISTORICAL_PERIOD", 1),
            frequency_type=cfg.get("HISTORICAL_FREQUENCY_TYPE", "daily"),
            frequency=cfg.get("HISTORICAL_FREQUENCY", 1),
            need_extended_hours=cfg.get("HISTORICAL_NEED_EXTENDED_HOURS", False),
        )

        try:
            df = parse_price_history_to_df(raw)
        except Exception:
            df = pd.DataFrame(raw.get("candles", []))

        if df.empty:
            return []

        # Upstream currency and punctuation sanitization
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                if df[col].dtype == object:
                    df[col] = (
                        df[col]
                        .astype(str)
                        .str.replace("$", "", regex=False)
                        .str.replace(",", "", regex=False)
                        .str.strip()
                    )
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "datetime" in df.columns:
            df["datetime"] = pd.to_numeric(df["datetime"], errors="coerce")

        cols = ["datetime", "open", "high", "low", "close", "volume"]
        existing = [c for c in cols if c in df.columns]
        return df[existing].dropna(subset=["high", "low", "close"]).to_dict(orient="records")

    except Exception as exc:
        logger.error("PriceHistory query failed for %s: %s", clean_sym, exc)
        return []


def extract_in_memory_option_expirations(client: SchwabClient, symbol: str) -> List[Dict[str, Any]]:
    """Retrieves option expiration schedules in-memory to discover required analytical tenors."""
    clean_sym = sanitize_and_validate_symbols(symbol)
    try:
        payload = client.get_option_expirations(clean_sym)
        exp_list = payload.get("expirationList", [])
        if not exp_list:
            return []
        df = pd.DataFrame(exp_list)
        cols = ["expirationDate", "daysToExpiration"]
        existing = [c for c in cols if c in df.columns]
        return df[existing].sort_values("daysToExpiration").to_dict(orient="records")
    except Exception as exc:
        logger.error("OptionExpirations query failed for %s: %s", clean_sym, exc)
        return []


def resolve_optimal_expirations(expirations: List[Dict[str, Any]]) -> List[str]:
    """Resolves the nearest front-month expiration cycle and the cycle closest to 30 DTE."""
    if not expirations:
        return []
    valid_exps = [e for e in expirations if e.get("daysToExpiration", 0) > 0]
    if not valid_exps:
        valid_exps = expirations

    front_exp = min(valid_exps, key=lambda x: x["daysToExpiration"])["expirationDate"]
    thirty_dte_exp = min(valid_exps, key=lambda x: abs(x["daysToExpiration"] - 30))["expirationDate"]
    return sorted(list({front_exp, thirty_dte_exp}))


def extract_in_memory_option_chains(
    client: SchwabClient,
    symbol: str,
    target_expirations: List[str],
    strike_count: int = 14,
    strategy: str = "SINGLE",
    include_quote: bool = True,  # DEF-10: Default True to capture contemporaneous underlyingPrice
) -> Tuple[Optional[float], Optional[float], List[Dict[str, Any]]]:
    """
    Extracts targeted option strikes for specified expirations in-memory.
    Returns: (volatility_30d, underlying_price, list_of_contract_records).
    """
    clean_sym = sanitize_and_validate_symbols(symbol)
    vol_30d: Optional[float] = None
    underlying_price: Optional[float] = None
    records: List[Dict[str, Any]] = []

    if not target_expirations:
        return None, None, []

    for exp_date in target_expirations:
        try:
            raw_chain = client.get_option_chain(
                symbol=clean_sym,
                contract_type="ALL",
                strike_count=strike_count,
                include_underlying_quote=include_quote,
                strategy=strategy,
                from_date=exp_date,
                to_date=exp_date,
            )

            if vol_30d is None:
                vol_30d = _clean_numeric_val(raw_chain.get("volatility"))

            if underlying_price is None:
                underlying_price = _clean_numeric_val(raw_chain.get("underlyingPrice"))

            def parse_map(exp_map: Dict[str, Any], flag: str):
                if not isinstance(exp_map, dict):
                    return
                for exp_key, strike_map in exp_map.items():
                    dte = int(exp_key.split(":")[1]) if ":" in exp_key else None
                    if not isinstance(strike_map, dict):
                        continue
                    for _, contracts in strike_map.items():
                        if not isinstance(contracts, list):
                            continue
                        for c in contracts:
                            # DEF-OUT-02: Explicitly extract bid, ask, and mark
                            records.append({
                                "putCallIndicator": c.get("putCallIndicator", flag),
                                "daysToExpiration": c.get("daysToExpiration", dte),
                                "strikePrice": _clean_numeric_val(c.get("strikePrice")),
                                "bid": _clean_numeric_val(c.get("bid")),
                                "ask": _clean_numeric_val(c.get("ask")),
                                "mark": _clean_numeric_val(c.get("mark")),
                                "totalVolume": c.get("totalVolume"),
                                "openInterest": c.get("openInterest"),
                                "volatility": _clean_numeric_val(c.get("volatility")),
                                "delta": _clean_numeric_val(c.get("delta")),
                                "gamma": _clean_numeric_val(c.get("gamma")),
                                "theta": _clean_numeric_val(c.get("theta")),
                                "vega": _clean_numeric_val(c.get("vega")),
                                "inTheMoney": c.get("inTheMoney", False),
                            })

            parse_map(raw_chain.get("callExpDateMap", {}), "CALL")
            parse_map(raw_chain.get("putExpDateMap", {}), "PUT")

        except Exception as exc:
            logger.error("OptionChains extraction failed for %s on %s: %s", clean_sym, exp_date, exc)
            continue

    return vol_30d, underlying_price, records


# ---------------------------------------------------------------------------
# WORKFLOW: FULL HISTORICAL TIMESERIES & SURFACE CHUNKING
# ---------------------------------------------------------------------------
def extract_historical_timeseries(
    symbol: str,
    *,
    period_type: str = "year",
    period: int = 20,
    frequency_type: str = "daily",
    frequency: int = 1,
    need_extended_hours: bool = False,
    token_file_path: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """Pulls up to 20 years of OHLCV bars and parses directly into a clean DataFrame."""
    clean_sym = sanitize_and_validate_symbols(symbol)
    with build_schwab_client(token_file_path=token_file_path) as client:
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
    token_file_path: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """Production-grade option surface extraction with automatic tenor chunking."""
    clean_sym = sanitize_and_validate_symbols(symbol)
    with build_schwab_client(token_file_path=token_file_path) as client:
        if strike_count is not None or not chunk_by_expiration:
            raw_chain = client.get_option_chain(
                symbol=clean_sym,
                contract_type=contract_type,
                strike_count=strike_count,
            )
            return parse_option_chain_to_df(raw_chain)

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