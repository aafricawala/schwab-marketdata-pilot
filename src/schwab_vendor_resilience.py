"""
schwab_vendor_resilience.py

Cross-cutting vendor resilience: retry decorator and response-envelope normalizer.
Extracted verbatim from schwab_raw_marketdata.py (no logic change).
"""
from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("schwab_raw_marketdata")
logger.addHandler(logging.NullHandler())


def retry_vendor_call(max_retries: int = 3, base_delay: float = 0.25) -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base_delay
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    status = getattr(e, "status_code", None) or getattr(
                        getattr(e, "response", None), "status_code", None
                    )
                    if status and status < 500 and status not in (429, 408):
                        logger.warning(
                            "Vendor client error %s in %s; not retrying: %s",
                            status,
                            func.__name__,
                            e,
                        )
                        raise
                    if attempt < max_retries:
                        logger.warning(
                            "Attempt %s/%s failed in %s: %s. Retrying in %.2fs",
                            attempt,
                            max_retries,
                            func.__name__,
                            e,
                            delay,
                        )
                        time.sleep(delay)
                        delay *= 2.0
                    else:
                        logger.warning(
                            "All %s attempts failed in %s: %s",
                            max_retries,
                            func.__name__,
                            e,
                        )
            raise last_exc

        return wrapper

    return decorator


def parse_client_response(resp: Any) -> Optional[Dict[str, Any]]:
    if resp is None:
        return None
    d = None
    if isinstance(resp, dict):
        d = resp
    elif hasattr(resp, "status_code"):
        if resp.status_code == 200:
            try:
                parsed = resp.json()
                if isinstance(parsed, dict):
                    d = parsed
            except (ValueError, TypeError) as e:
                logger.warning("Failed to decode JSON from 200 response: %s", e)
                return None
        else:
            logger.warning("Vendor call returned non-200 HTTP status: %s", resp.status_code)
            return None

    if d is not None:
        for err_key in ("error", "errors", "fault", "faultcode"):
            if err_key in d:
                logger.warning("Vendor payload envelope reports error flag '%s': %s", err_key, d[err_key])
                return None
    return d