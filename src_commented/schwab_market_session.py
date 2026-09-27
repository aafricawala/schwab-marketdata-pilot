"""
schwab_market_session.py

Market-session state: open/closed resolution with vendor-first, local-clock fallback.
Extracted verbatim from schwab_raw_marketdata.py (no logic change).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from schwab_vendor_resilience import parse_client_response, retry_vendor_call

logger = logging.getLogger("schwab_raw_marketdata")
logger.addHandler(logging.NullHandler())


@retry_vendor_call(max_retries=2, base_delay=0.1)
def extract_market_open_status(client: Any) -> bool:
    try:
        r = client.get_market_hours("equity")
        d = parse_client_response(r)
        if d:
            eq = d.get("equity", {})
            for m in ["EQ", "equity"]:
                if m in eq and "isOpen" in eq[m]:
                    return bool(eq[m]["isOpen"])
    except (KeyError, ValueError, TypeError, AttributeError) as e:
        logger.warning("Could not resolve market open status via client: %s", e)

    now_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return False
    return (9, 30) <= (now_et.hour, now_et.minute) < (16, 0)