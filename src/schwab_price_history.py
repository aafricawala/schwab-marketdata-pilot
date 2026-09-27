"""
schwab_price_history.py

Price-history (candles) extraction with retry and in-memory filtering.
Extracted verbatim from schwab_raw_marketdata.py (no logic change).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from schwab_utils import safe_float, validate_symbol
from schwab_vendor_resilience import parse_client_response, retry_vendor_call

logger = logging.getLogger("schwab_raw_marketdata")
logger.addHandler(logging.NullHandler())


def extract_in_memory_price_history(
    client: Any, symbol: str, config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    clean_sym = validate_symbol(symbol)
    p_type = config.get("HISTORICAL_PERIOD_TYPE", "year")
    p_val = config.get("HISTORICAL_PERIOD", 1)
    f_type = config.get("HISTORICAL_FREQUENCY_TYPE", "daily")
    f_val = config.get("HISTORICAL_FREQUENCY", 1)
    ext_hrs = config.get("HISTORICAL_NEED_EXTENDED_HOURS", False)

    kwargs = {
        "period_type": p_type,
        "period": p_val,
        "frequency_type": f_type,
        "frequency": f_val,
        "need_extended_hours": ext_hrs,
    }

    @retry_vendor_call(max_retries=3, base_delay=0.25)
    def _fetch_candles() -> Any:
        return client.get_price_history(clean_sym, **kwargs)

    try:
        r = _fetch_candles()
        d = parse_client_response(r)
        if d:
            candles = d.get("candles", []) or []
            return [
                c
                for c in candles
                if safe_float(c.get("close")) is not None
                and safe_float(c.get("open")) is not None
            ]
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        logger.warning("Price history extraction encountered an error for %s: %s", clean_sym, e)
    return []