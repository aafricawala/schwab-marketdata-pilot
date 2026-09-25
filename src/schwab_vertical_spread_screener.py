"""
schwab_vertical_spread_screener.py
========================================================================================
CHARLES SCHWAB VERTICAL DEBIT SPREAD SCREENER & QUANTITATIVE ANALYTICS ENGINE
========================================================================================

WHAT THIS SCRIPT DOES:
----------------------
This module screens, prices, and evaluates vertical debit option spreads (Bull Call Spreads
and Bear Put Spreads) for a target equity ticker at a specified expiration date.

It takes candidate strike price combinations (long legs vs. short legs), retrieves live
option chains from the Charles Schwab API, and calculates institutional risk metrics:
- Net debit pricing (both synthetic midpoint mark and natural execution ask-bid crossing).
- Cost-to-width capital efficiency percentage (flagging trades that meet risk hurdle gates).
- Breakeven prices and percentage distance hurdles from the current underlying spot price.
- Maximum profit per share and theoretical maximum Return on Capital (ROC%).
- Net position Greeks (Delta, Theta, Vega, Gamma).
- Automatic sorting and ranking by ascending cost-to-width ratio.

WHEN AND HOW IT GETS CALLED:
----------------------------
1. Standalone CLI Tool:
   Run from the terminal or shell prompt to evaluate candidate spreads on demand:
     $ python schwab_vertical_spread_screener.py \
         --symbol GOOGL \
         --expiration 2028-01-21 \
         --long-strikes 280 290 300 \
         --short-strikes 430 440 450 \
         --strategy-type CALL \
         --cost-to-width-max 40.0 \
         --out googl_spreads.json

2. Programmatic Python / Colab Notebook Runner:
   Imported by screening notebooks or automated trade scanners:
     from schwab_vertical_spread_screener import evaluate_vertical_spreads
     results = evaluate_vertical_spreads(
         symbol="GOOGL",
         expiration="2028-01-21",
         long_strikes=[280.0, 290.0, 300.0],
         short_strikes=[430.0, 440.0, 450.0],
         strategy_type="CALL",
         cost_to_width_pass_pct=40.0,
     )

KEY FUNCTIONS AND HIGH-LEVEL RESPONSIBILITIES:
---------------------------------------------
1. evaluate_vertical_spreads(...):
   - The primary analytics engine of this module.
   - Validates ticker symbols and filters strike arrays to ensure positive, unique values.
   - Reuses `build_schwab_client()` from `schwab_auth` to acquire an active API session.
   - Queries `get_option_chain()` using dynamic signature inspection to support both
     snake_case and camelCase parameters across API wrapper versions.
   - Implements multi-tier spot price resolution (underlying block in chain -> chain root
     spot -> fallback quote query) to ensure moneyness and breakevens can always be solved.
   - Normalizes contract data (mark price fallbacks, Greek rounding, volume, and open interest).
   - Iterates through long and short strike combinations, rejecting invalid pairings:
       * Bull Call Spreads: Requires Long Strike < Short Strike.
       * Bear Put Spreads: Requires Long Strike > Short Strike.
       * Edge-case guards: Discards net credits, inverted parity pricing, and spreads
         where the net debit exceeds the gross spread width (guaranteed loss).
   - Computes capital efficiency, maximum return, breakeven distance, and netted Greeks.
   - Returns a structured dictionary containing ticker metadata, spot details, target DTE,
     extracted contract legs, and ranked spread evaluations.

2. _build_arg_parser() & main():
   - Configures CLI arguments (--symbol, --expiration, --long-strikes, --short-strikes,
     --cost-to-width-max, --strategy-type, --out, etc.).
   - Orchestrates CLI execution, optionally writes structured JSON output to disk, and
     prints formatted results to stdout.

EDGE-CASE PROTECTIONS & INSTITUTIONAL SAFEGUARDS:
------------------------------------------------
- Inverted / Parity Strike Guards: Discards pairings that violate directional spread geometry.
- Net Debit / Arbitrage Sanity: Rejects free/credit quotes or debit >= width quotes that indicate
  bad ticks, stale books, or guaranteed negative mathematical expectancy.
- Mark Price Fallbacks: If Schwab omits `mark`, defaults to synthetic midpoint `(bid + ask) / 2`,
  falling back to `last` if quotes are completely unpopulated.
- Decoupled Infrastructure: Consumes authentication from `schwab_auth` and symbol validation
  from `schwab_raw_marketdata`, avoiding duplicated session logic and preventing path pollution.
========================================================================================
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

# ------------------------------------------------------------------------------
# 1. Workspace Path Alignment & Module Imports
# ------------------------------------------------------------------------------
PROJECT_SRC = (
    Path(__file__).resolve().parent
    if "__file__" in locals()
    else Path("/content/schwab-marketdata-pilot/src")
)
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

logger = logging.getLogger("VerticalSpreadEngine")
logger.addHandler(logging.NullHandler())

try:
    from schwab_auth import (
        CredentialResolutionError,
        OrchestratorError,
        build_schwab_client,
        resolve_secure_token_path,
    )
    from schwab_raw_marketdata import sanitize_and_validate_symbols
except ImportError as err:
    raise ImportError(
        f"FATAL: Unable to load modules from '{PROJECT_SRC}'. "
        f"Ensure schwab_auth.py and schwab_raw_marketdata.py are present. Detail: {err}"
    ) from err

try:
    from schwab_client import SchwabClient
except ImportError as err:
    raise ImportError(
        f"FATAL: Unable to load 'schwab_client.py' from '{PROJECT_SRC}'. "
        f"Ensure the module is in your Python path. Detail: {err}"
    ) from err


# ------------------------------------------------------------------------------
# 2. Market Data & Spread Analytics Engine
# ------------------------------------------------------------------------------
def evaluate_vertical_spreads(
    symbol: str,
    expiration: str,
    long_strikes: Sequence[float],
    short_strikes: Sequence[float],
    *,
    strategy_type: str = "CALL",
    cost_to_width_pass_pct: float = 40.0,
    client: Optional[SchwabClient] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    token_path: Optional[Union[Path, str]] = None,
    interactive: bool = True,
    force_reauth: bool = False,
    secret_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> Dict[str, Any]:
    """
    Evaluates vertical debit spreads over target strike sets and expiration dates.
    Integrates defensive quote extraction, Greek netting, and institutional efficiency gates.
    """
    target_symbol = sanitize_and_validate_symbols(symbol)

    strat_type = strategy_type.strip().upper()
    if strat_type not in {"CALL", "PUT"}:
        raise ValueError(f"Invalid strategy_type: '{strategy_type}'. Must be 'CALL' or 'PUT'.")

    target_expiration = expiration.strip()
    sorted_longs = sorted(list(set(float(k) for k in long_strikes if float(k) > 0)))
    sorted_shorts = sorted(list(set(float(k) for k in short_strikes if float(k) > 0)))

    if not sorted_longs or not sorted_shorts:
        raise ValueError("Long strikes and short strikes must contain valid, positive numbers.")

    required_strikes = sorted(list(set(sorted_longs + sorted_shorts)))

    # Acquire or initialize API client via standard schwab_auth factory
    managed_client = client or build_schwab_client(
        token_file_path=token_path,
        interactive=interactive,
        secret_provider=secret_provider,
    )

    with managed_client as cli:
        # Dynamic query introspection
        chain_sig = inspect.signature(cli.get_option_chain)
        params = chain_sig.parameters
        query_kwargs: Dict[str, Any] = {}

        if "contract_type" in params:
            query_kwargs["contract_type"] = strat_type
        elif "contractType" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        ):
            query_kwargs["contractType"] = strat_type

        if "from_date" in params:
            query_kwargs["from_date"] = target_expiration
            query_kwargs["to_date"] = target_expiration
        elif "fromDate" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        ):
            query_kwargs["fromDate"] = target_expiration
            query_kwargs["toDate"] = target_expiration

        if "strategy" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        ):
            query_kwargs["strategy"] = "SINGLE"

        if "include_underlying_quote" in params:
            query_kwargs["include_underlying_quote"] = True
        elif "includeUnderlyingQuote" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        ):
            query_kwargs["includeUnderlyingQuote"] = True

        try:
            chain_payload = cli.get_option_chain(symbol=target_symbol, **query_kwargs)
        except Exception as req_err:
            logger.warning("Parameterized get_option_chain failed (%s). Retrying unconstrained...", req_err)
            chain_payload = cli.get_option_chain(target_symbol)

        # Multi-tier Spot Price Fallback
        spot_px: Optional[float] = None
        underlying_dict = chain_payload.get("underlying") or {}

        if underlying_dict and isinstance(underlying_dict, dict):
            spot_px = (
                underlying_dict.get("mark")
                or underlying_dict.get("last")
                or underlying_dict.get("bid")
            )

        if spot_px is None:
            spot_px = chain_payload.get("underlyingPrice")

        if spot_px is None or float(spot_px) <= 0:
            logger.info("Resolving underlying spot quote via get_quotes fallback endpoint...")
            try:
                quote_resp = cli.get_quotes(target_symbol)
                sym_quote = quote_resp.get(target_symbol, {}).get("quote", {})
                spot_px = (
                    sym_quote.get("mark")
                    or sym_quote.get("lastPrice")
                    or sym_quote.get("bidPrice")
                )
                underlying_dict = {
                    "spot": float(spot_px or 0.0),
                    "bid": float(sym_quote.get("bidPrice", 0.0)),
                    "ask": float(sym_quote.get("askPrice", 0.0)),
                    "mark": float(sym_quote.get("mark", spot_px or 0.0)),
                    "volume": int(sym_quote.get("totalVolume", 0)),
                }
            except Exception as quote_err:
                logger.warning("Fallback get_quotes query failed: %s", quote_err)

        if not spot_px or float(spot_px) <= 0:
            raise OrchestratorError(
                f"Spot price resolution failed for ticker '{target_symbol}'. "
                "Unable to compute relative moneyness or breakeven hurdles."
            )

        spot_float = float(spot_px)

        # Strike Surface & Greeks Parsing
        exp_map_key = "callExpDateMap" if strat_type == "CALL" else "putExpDateMap"
        exp_map = chain_payload.get(exp_map_key, {})
        target_exp_key = next((k for k in exp_map.keys() if target_expiration in k), None)

        if not target_exp_key:
            available_expirations = list(exp_map.keys())[:10]
            raise ValueError(
                f"Expiration '{target_expiration}' not found in {exp_map_key}. "
                f"Available expiration cycles: {available_expirations}"
            )

        try:
            dte_val = int(target_exp_key.split(":")[1])
        except Exception:
            dte_val = 0

        contracts_db: Dict[float, Dict[str, Any]] = {}
        raw_strikes = exp_map[target_exp_key]

        for strk_str, contract_arr in raw_strikes.items():
            try:
                k_val = float(strk_str)
                if k_val in required_strikes and contract_arr:
                    c_obj = contract_arr[0]
                    c_bid = float(c_obj.get("bid") or 0.0)
                    c_ask = float(c_obj.get("ask") or 0.0)
                    c_mark = c_obj.get("mark")

                    # Robust mark price fallback
                    if c_mark is not None and float(c_mark) > 0:
                        mark_clean = float(c_mark)
                    elif (c_bid + c_ask) > 0:
                        mark_clean = (c_bid + c_ask) / 2.0
                    else:
                        mark_clean = float(c_obj.get("last") or 0.0)

                    contracts_db[k_val] = {
                        "strike": k_val,
                        "bid": round(c_bid, 2),
                        "ask": round(c_ask, 2),
                        "mark": round(mark_clean, 2),
                        "delta": round(float(c_obj.get("delta") or 0.0), 4),
                        "theta": round(float(c_obj.get("theta") or 0.0), 4),
                        "vega": round(float(c_obj.get("vega") or 0.0), 4),
                        "gamma": round(float(c_obj.get("gamma") or 0.0), 4),
                        "iv": round(float(c_obj.get("volatility") or 0.0), 2),
                        "open_interest": int(c_obj.get("openInterest") or 0),
                        "volume": int(c_obj.get("totalVolume") or 0),
                    }
            except (ValueError, TypeError) as parse_err:
                logger.debug("Skipping unparseable strike %s: %s", strk_str, parse_err)
                continue

        # Spread Synthesis & Risk Modeling
        spread_evaluations: List[Dict[str, Any]] = []

        for k_long in sorted_longs:
            for k_short in sorted_shorts:
                # Structural validity:
                # Bull Call Spread: Long strike < Short strike
                # Bear Put Spread: Long strike > Short strike
                if strat_type == "CALL" and k_short <= k_long:
                    continue
                if strat_type == "PUT" and k_long <= k_short:
                    continue

                if k_long not in contracts_db or k_short not in contracts_db:
                    continue

                leg_l = contracts_db[k_long]
                leg_s = contracts_db[k_short]
                spread_width = round(abs(k_short - k_long), 2)
                net_debit_mark = round(leg_l["mark"] - leg_s["mark"], 2)
                net_debit_nat = round(leg_l["ask"] - leg_s["bid"], 2)

                # Edge Case: Reject non-debit spreads, arbitrage quotes, or negative expectancy
                if net_debit_mark <= 0 or spread_width <= 0:
                    continue
                if net_debit_mark >= spread_width:
                    continue  # Debit >= width guarantees capital loss at maximum gain

                max_profit = round(spread_width - net_debit_mark, 2)
                roc_pct = round((max_profit / net_debit_mark) * 100, 2)
                cost_to_width = round((net_debit_mark / spread_width) * 100, 2)

                breakeven = (
                    round(k_long + net_debit_mark, 2)
                    if strat_type == "CALL"
                    else round(k_long - net_debit_mark, 2)
                )
                be_dist_pct = round(((breakeven - spot_float) / spot_float) * 100, 2)

                spread_evaluations.append(
                    {
                        "structure": (
                            f"${k_long:.0f} /${k_short:.0f} Bull Call Spread"
                            if strat_type == "CALL"
                            else f"${k_long:.0f} /${k_short:.0f} Bear Put Spread"
                        ),
                        "strategy_type": strat_type,
                        "long_strike": k_long,
                        "short_strike": k_short,
                        "gross_width": spread_width,
                        "pricing": {
                            "net_debit_mark": net_debit_mark,
                            "net_debit_natural": net_debit_nat,
                            "cost_to_width_pct": cost_to_width,
                            "efficiency_status": (
                                "PASS"
                                if cost_to_width <= cost_to_width_pass_pct
                                else "FAIL"
                            ),
                            "max_profit_per_share": max_profit,
                            "max_roc_pct": roc_pct,
                            "breakeven_price": breakeven,
                            "breakeven_pct_from_spot": be_dist_pct,
                        },
                        "net_greeks": {
                            "net_delta": round(leg_l["delta"] - leg_s["delta"], 4),
                            "net_theta": round(leg_l["theta"] - leg_s["theta"], 4),
                            "net_vega": round(leg_l["vega"] - leg_s["vega"], 4),
                            "net_gamma": round(leg_l["gamma"] - leg_s["gamma"], 4),
                        },
                        "long_leg": leg_l,
                        "short_leg": leg_s,
                    }
                )

        # Rank by ascending cost-to-width ratio (capital efficiency)
        spread_evaluations.sort(key=lambda x: x["pricing"]["cost_to_width_pct"])

        return {
            "as_of_ticker": target_symbol,
            "spot_price": spot_float,
            "underlying_details": underlying_dict,
            "expiration": target_expiration,
            "dte": dte_val,
            "contracts_extracted": list(contracts_db.values()),
            "spread_evaluations": spread_evaluations,
        }


# ------------------------------------------------------------------------------
# 3. CLI Execution Interface
# ------------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Institutional Vertical Debit Spread Screener (Schwab API)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--symbol", "-s", type=str, required=True, help="Target underlying ticker (e.g. GOOGL)")
    parser.add_argument("--expiration", "-e", type=str, required=True, help="Expiration date (YYYY-MM-DD)")
    parser.add_argument("--long-strikes", "-l", type=float, nargs="+", required=True, help="Candidate long strikes")
    parser.add_argument("--short-strikes", "-k", type=float, nargs="+", required=True, help="Candidate short strikes")
    parser.add_argument("--cost-to-width-max", type=float, default=40.0, help="Max cost-to-width %% for PASS tag")
    parser.add_argument("--strategy-type", choices=["CALL", "PUT"], default="CALL", help="Spread contract right")
    parser.add_argument("--force-reauth", action="store_true", help="Evict cached token and re-run OAuth handshake")
    parser.add_argument("--non-interactive", action="store_true", help="Fail fast if token is expired/missing")
    parser.add_argument("--token-path", type=str, default=None, help="Custom token storage path override")
    parser.add_argument("--out", type=str, default=None, help="File path to write JSON results")
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = _build_arg_parser()
    args = parser.parse_args()

    result = evaluate_vertical_spreads(
        symbol=args.symbol,
        expiration=args.expiration,
        long_strikes=args.long_strikes,
        short_strikes=args.short_strikes,
        cost_to_width_pass_pct=args.cost_to_width_max,
        strategy_type=args.strategy_type,
        interactive=not args.non_interactive,
        force_reauth=args.force_reauth,
        token_path=args.token_path,
    )

    json_str = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(json_str, encoding="utf-8")
        logger.info("Output saved to %s", args.out)

    print(json_str)


if __name__ == "__main__":
    main()