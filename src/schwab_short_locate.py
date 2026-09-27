"""
schwab_short_locate.py

Short-locate state resolver: normalizes shortable / hard-to-borrow / HTB rate
from ref, quote, and shortLocate sub-envelopes.

Extracted verbatim from schwab_raw_marketdata.py (no logic change).
"""
from __future__ import annotations

from typing import Any, Dict

from schwab_utils import safe_float


def resolve_short_locate(
    ref: Dict[str, Any],
    quote: Dict[str, Any],
    is_halted_or_unquoted: bool,
) -> Dict[str, Any]:
    short_stat = ref.get("shortLocate", quote.get("shortLocate", {}))
    if not isinstance(short_stat, dict):
        short_stat = {}
    is_shortable = (
        ref.get("isShortable")
        if ref.get("isShortable") is not None
        else quote.get("isShortable", short_stat.get("isShortable"))
    )
    is_htb = (
        ref.get("isHardToBorrow")
        if ref.get("isHardToBorrow") is not None
        else quote.get("isHardToBorrow", short_stat.get("isHardToBorrow"))
    )
    raw_htb_rate = safe_float(
        ref.get("htbRate", quote.get("htbRate", short_stat.get("rate")))
    )

    if is_halted_or_unquoted:
        short_dict: Dict[str, Any] = {
            "state": "UNKNOWN",
            "reason": "asset_halted_or_unquoted_locate_unavailable",
        }
    elif is_shortable is None and is_htb is None and raw_htb_rate is None:
        short_dict = {
            "state": "UNKNOWN",
            "reason": "locate_data_not_reported_by_venue_or_tier",
        }
    else:
        htb_rate_val = raw_htb_rate
        raw_htb_store = None
        if is_htb is False:
            htb_status = "NOT_APPLICABLE_ETB"
        elif is_htb is None:
            htb_status = "VENDOR_UNAVAILABLE_LOCATE_PENDING"
        elif raw_htb_rate is not None and raw_htb_rate < 0.0:
            htb_status = "INVALID_NEGATIVE_VENDOR_RATE"
            raw_htb_store, htb_rate_val = raw_htb_rate, None
        elif raw_htb_rate == 0.0:
            htb_status = "HTB_FLAG_ACTIVE_RATE_PENDING_BROKER_LOCATE"
        elif raw_htb_rate is not None:
            htb_status = "LOCATE_AVAILABLE"
        else:
            htb_status = "VENDOR_UNAVAILABLE_LOCATE_PENDING"

        short_dict = {
            "state": (
                "FULL_PASSTHROUGH"
                if all(v is not None for v in [is_shortable, is_htb])
                else "PARTIAL_PASSTHROUGH"
            ),
            "isShortable": bool(is_shortable) if is_shortable is not None else True,
            "isHardToBorrow": bool(is_htb) if is_htb is not None else False,
            "htbRate": htb_rate_val,
            "htb_rate_status": htb_status,
        }
        if raw_htb_store is not None:
            short_dict["htbRate_raw"] = raw_htb_store

    return short_dict