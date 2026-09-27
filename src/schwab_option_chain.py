"""
schwab_option_chain.py

Option surface: expirations discovery, optimal expiration selection, and
in-memory option-chain extraction (targeted + default-chain fallback) with
rejection telemetry.

Moved verbatim from schwab_raw_marketdata.py (no logic change). The nested
_parse_chain_payload closure inside extract_in_memory_option_chains is
preserved intact.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from schwab_utils import safe_float, validate_symbol
from schwab_vendor_resilience import parse_client_response, retry_vendor_call

logger = logging.getLogger("schwab_raw_marketdata")
logger.addHandler(logging.NullHandler())


def extract_in_memory_option_expirations(
    client: Any, symbol: str
) -> List[Dict[str, Any]]:
    clean_sym = validate_symbol(symbol)

    @retry_vendor_call(max_retries=2, base_delay=0.2)
    def _fetch_expirations() -> Any:
        for m in ["get_option_expirations", "get_option_expiration_chain"]:
            if hasattr(client, m):
                return getattr(client, m)(clean_sym)
        return None

    try:
        r = _fetch_expirations()
        d = parse_client_response(r)
        if d:
            return d.get("expirationList", []) or []
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        logger.warning("Option expirations query encountered an error for %s: %s", clean_sym, e)
    return []


def resolve_optimal_expirations(
    exp_list: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    valid = [
        e
        for e in exp_list
        if safe_float(e.get("daysToExpiration")) is not None
        and int(e["daysToExpiration"]) >= 0
    ]
    if not valid:
        return []
    sorted_exps = sorted(valid, key=lambda x: int(x["daysToExpiration"]))
    front = sorted_exps[0]
    t1_cands = [e for e in sorted_exps if int(e["daysToExpiration"]) <= 30]
    t2_cands = [e for e in sorted_exps if int(e["daysToExpiration"]) >= 30]
    t1 = t1_cands[-1] if t1_cands else sorted_exps[0]
    t2 = t2_cands[0] if t2_cands else sorted_exps[-1]
    targets = [front, t1, t2]
    seen, uniq = set(), []
    for t in targets:
        k = t.get("expirationDate")
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq


def extract_in_memory_option_chains(
    client: Any,
    symbol: str,
    target_expirations: List[Dict[str, Any]],
    strike_window: int = 14,
    strategy: str = "SINGLE",
    strike_proximities: bool = True,
) -> Tuple[
    Optional[float], Optional[float], List[Dict[str, Any]], Dict[str, Any]
]:
    clean_sym = validate_symbol(symbol)
    telemetry: Dict[str, Any] = {
        "rejected_zero_strike_count": 0,
        "rejected_expired_contract_count": 0,
        "rejected_negative_mark_count": 0,
        "rejected_negative_price_count": 0,
        "fallback_to_default_chain": False,
    }

    all_contracts: List[Dict[str, Any]] = []
    underlying_price = None
    vol_30d = None

    def _parse_chain_payload(payload: Dict[str, Any], provenance: str = "TARGETED_EXPIRATION") -> None:
        nonlocal underlying_price, vol_30d
        if underlying_price is None:
            underlying_price = safe_float(payload.get("underlyingPrice"))
        if vol_30d is None:
            vol_30d = safe_float(payload.get("volatility"))
        for book_key, default_indicator in [("callExpDateMap", "CALL"), ("putExpDateMap", "PUT")]:
            book = payload.get(book_key, {})
            for date_key, strikes in book.items():
                for strike_key, contract_list in strikes.items():
                    for c in contract_list:
                        s_val = safe_float(c.get("strikePrice"))
                        dte_val = c.get("daysToExpiration")
                        mark_val = safe_float(c.get("mark"))
                        bid_val = safe_float(c.get("bid"))
                        ask_val = safe_float(c.get("ask"))
                        if s_val is None or s_val <= 0:
                            telemetry["rejected_zero_strike_count"] += 1
                            continue
                        if dte_val is None or int(dte_val) < 0:
                            telemetry["rejected_expired_contract_count"] += 1
                            continue
                        if mark_val is not None and mark_val < 0:
                            telemetry["rejected_negative_mark_count"] += 1
                            continue
                        if (bid_val is not None and bid_val < 0) or (
                            ask_val is not None and ask_val < 0
                        ):
                            telemetry["rejected_negative_price_count"] += 1
                            continue

                        contract_item = dict(c)
                        contract_item["putCallIndicator"] = str(
                            c.get("putCallIndicator")
                            or c.get("putCallType")
                            or default_indicator
                        ).upper()
                        contract_item["provenance"] = provenance
                        all_contracts.append(contract_item)

    if target_expirations:
        for exp in target_expirations:
            exp_date_raw = exp.get("expirationDate")
            if not exp_date_raw:
                continue

            date_obj = None
            try:
                date_obj = datetime.strptime(str(exp_date_raw)[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass

            call_kwargs = {
                "strike_count": strike_window,
                "from_date": date_obj if date_obj is not None else exp_date_raw,
                "to_date": date_obj if date_obj is not None else exp_date_raw,
                "strategy": strategy,
            }

            @retry_vendor_call(max_retries=2, base_delay=0.15)
            def _fetch_target_chain() -> Any:
                return client.get_option_chain(clean_sym, **call_kwargs)

            try:
                r = _fetch_target_chain()
                parsed = parse_client_response(r)
                if parsed and ("callExpDateMap" in parsed or "putExpDateMap" in parsed):
                    _parse_chain_payload(parsed, provenance="TARGETED_EXPIRATION")
            except (KeyError, ValueError, TypeError, AttributeError) as e:
                logger.warning("Targeted expiration chain failed for %s (%s): %s", clean_sym, exp_date_raw, e)

    if not all_contracts:
        @retry_vendor_call(max_retries=2, base_delay=0.2)
        def _fetch_default_chain() -> Any:
            return client.get_option_chain(clean_sym)

        try:
            r = _fetch_default_chain()
            parsed = parse_client_response(r)
            if parsed and ("callExpDateMap" in parsed or "putExpDateMap" in parsed):
                telemetry["fallback_to_default_chain"] = True
                _parse_chain_payload(parsed, provenance="DEFAULT_CHAIN_FALLBACK")
        except Exception as e:
            logger.warning("Default chain fallback failed for %s: %s", clean_sym, e)

    return vol_30d, underlying_price, all_contracts, telemetry