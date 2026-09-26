# schwab_raw_marketdata.py
from __future__ import annotations
import functools
import logging
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import pandas as pd

from schwab_utils import safe_div, safe_float, validate_symbol

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


def _parse_client_response(resp: Any) -> Optional[Dict[str, Any]]:
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


@retry_vendor_call(max_retries=2, base_delay=0.1)
def extract_market_open_status(client: Any) -> bool:
    try:
        r = client.get_market_hours("equity")
        d = _parse_client_response(r)
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


def _build_halted_grounding(
    clean_sym: str, tz_et: ZoneInfo, q_age: Optional[float], q_time_iso: Optional[str]
) -> Dict[str, Any]:
    """Synthetic halted/unquoted grounding payload for empty or malformed quote envelopes."""
    return {
        "phase_0_grounding": {
            "symbol": clean_sym,
            "company_name": "",
            "lastPrice": None,
            "closePrice": None,
            "quoteTime_ISO_ET": q_time_iso,
            "quote_age_seconds": q_age,
            "quote_age_classification": "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED",
        },
        "step_1_fundamentals": {
            "beta": None,
            "beta_state": "VENDOR_UNAVAILABLE",
            "peRatio": None,
            "peRatio_state": "VENDOR_UNAVAILABLE_ASSET_HALTED",
            "pegRatio": None,
            "pegRatio_state": "VENDOR_UNAVAILABLE",
            "pcfRatio": None,
            "pcfRatio_state": "VENDOR_UNAVAILABLE",
            "pbRatio": None,
            "totalDebtToEquity": None,
            "totalDebtToEquity_basis": "VENDOR_RAW_UNVERIFIED",
            "grossMarginTTM": None,
            "netProfitMarginTTM": None,
            "operatingMarginTTM": None,
            "margin_fields_suspect": None,
            "margin_fields_suspect_reason": None,
            "margin_fields_suspect_state": "VENDOR_UNAVAILABLE_INPUTS_ABSENT",
            "returnOnEquity": None,
            "returnOnEquity_state": "VENDOR_UNAVAILABLE",
            "returnOnAssets": None,
            "returnOnAssets_state": "VENDOR_UNAVAILABLE",
            "eps": None,
            "eps_state": "VENDOR_UNAVAILABLE_ASSET_HALTED",
            "revChangeYear": None,
            "revChangeYear_state": "VENDOR_UNAVAILABLE",
            "divYield": 0.0,
            "divYield_basis": "VENDOR_UNAVAILABLE",
            "divYield_raw": 0.0,
            "divAmount": "$0.00",
            "div_amount_basis": "ANNUAL",
            "divFreq": 0.0,
            "sharesOutstanding": None,
            "shares_outstanding_state": "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED",
            "marketCap": None,
            "marketCap_unit": "VENDOR_RAW_UNVERIFIED",
        },
        "short_locate_status": {
            "state": "UNKNOWN",
            "reason": "asset_halted_or_unquoted_locate_unavailable",
        },
        "step_8_and_9_liquidity_and_sizing": {
            "state": "UNVERIFIED_EMPTY_ORDER_BOOK",
            "bidPrice": None,
            "askPrice": None,
            "bidSize": 0.0,
            "askSize": 0.0,
            "totalVolume": 0.0,
            "vol10DayAvg": None,
            "vol10DayAvg_state": "VENDOR_UNAVAILABLE",
            "vol3MonthAvg_state": "VENDOR_FIELD_NOT_PROVIDED",
            "vol1YearAvg": None,
            "vol1YearAvg_state": "VENDOR_UNAVAILABLE",
            "reason": "asset_halted_or_unquoted",
            "book_liquidity_note": "EMPTY_ORDER_BOOK_ASSET_HALTED",
        },
    }


def extract_strict_underlying_data(
    client: Any, symbol: str, tz_et: ZoneInfo
) -> Dict[str, Any]:
    clean_sym = validate_symbol(symbol)

    @retry_vendor_call(max_retries=3, base_delay=0.2)
    def _fetch_quote(sym: str) -> Any:
        return client.get_quote(sym)

    try:
        res_dict = _parse_client_response(_fetch_quote(clean_sym))
    except Exception as e:
        logger.warning("Quote fetch raised for %s: %s", clean_sym, e)
        res_dict = None

    if not isinstance(res_dict, dict) or not res_dict:
        return _build_halted_grounding(clean_sym, tz_et, None, None)

    candidate = (
        res_dict.get(clean_sym)
        or res_dict.get(symbol)
        or res_dict.get(symbol.lower())
        or res_dict
    )
    if isinstance(candidate, dict):
        if clean_sym in candidate and isinstance(candidate[clean_sym], dict):
            candidate = candidate[clean_sym]
        elif symbol in candidate and isinstance(candidate[symbol], dict):
            candidate = candidate[symbol]
    data = candidate if isinstance(candidate, dict) else {}

    if not data:
        return _build_halted_grounding(clean_sym, tz_et, None, None)

    ref = data.get("reference", {}) if isinstance(data.get("reference"), dict) else {}
    quote = data.get("quote", {}) if isinstance(data.get("quote"), dict) else {}
    fund = data.get("fundamental", {}) if isinstance(data.get("fundamental"), dict) else {}
    asset_sub = str(ref.get("assetSubType", "") or "").upper()
    asset_main = str(ref.get("assetMainType", "") or "").upper()
    desc = str(ref.get("description", "") or "").upper()

    if not quote and not fund:
        return _build_halted_grounding(clean_sym, tz_et, None, None)

    is_warrant = (
        asset_sub in ["WARRANT", "WARNT"]
        or asset_main in ["WARRANT", "WARNT"]
        or bool(re.search(r"\b(WARRANT|WARNT|WRNT)\b", desc))
        or bool(re.search(r"(\.WS|[\.\/\-\s]WS|\.WT|[\.\/\-\s]WT|^[A-Z]{3,4}WW)$", clean_sym))
    )

    is_mutual_fund = (
        asset_sub in ["MUTUAL_FUND", "OPEN_END_FUND"]
        or asset_main in ["MUTUAL_FUND"]
        or bool(re.search(r"^[A-Z]{4}X$", clean_sym))
    )

    is_fund_type = (
        is_mutual_fund
        or asset_sub in ["ETF", "ETN", "CEF", "UIT", "CLOSED_END_FUND"]
        or asset_main in ["ETF", "ETN", "FUND", "COLLECTIVE_INVESTMENT"]
    )

    desc_pooled_match = bool(
        re.search(
            r"\b(ETF|ETN|MUTUAL FUND|INDEX FUND|TRUST|INDEX|PORTFOLIO|ETRACS|TREASURY BOND|BOND FUND|ADMIRAL|INVESTOR CLASS)\b",
            desc,
        )
    )

    is_structural_wrapper = not is_warrant and (is_fund_type or desc_pooled_match)
    raw_shares = safe_float(fund.get("sharesOutstanding"))

    last_p = safe_float(quote.get("lastPrice"))
    close_p = safe_float(quote.get("closePrice"))
    q_time_raw = quote.get("quoteTime", 0)

    if q_time_raw:
        now_ts = datetime.now(timezone.utc).timestamp()
        quote_ts = q_time_raw / 1000.0
        q_time_iso = (
            datetime.fromtimestamp(quote_ts, tz=timezone.utc)
            .astimezone(tz_et)
            .isoformat()
        )
        q_age = max(0.0, round(now_ts - quote_ts, 2))
    else:
        q_time_iso = None
        q_age = None

    def _functionally_zero(v: Optional[float]) -> bool:
        return v is None or abs(v) < 0.01

    is_halted_or_unquoted = (
        (_functionally_zero(last_p) and _functionally_zero(close_p))
        or (desc == "" and last_p is None)
    )

    if is_halted_or_unquoted:
        q_class = "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
    elif q_age is not None:
        q_class = (
            "REAL_TIME"
            if q_age <= 60.0
            else (
                "RECENT"
                if q_age <= 600.0
                else ("DELAYED" if q_age <= 3600.0 else "STALE")
            )
        )
    else:
        q_class = "UNKNOWN"

    raw_pe = safe_float(fund.get("peRatio"))
    raw_eps = safe_float(fund.get("eps"))
    raw_div_amt = safe_float(fund.get("divAmount"))
    raw_div_y = safe_float(fund.get("divYield"))
    raw_div_freq = safe_float(fund.get("divFreq"))

    country = str(
        ref.get("country")
        or quote.get("country")
        or fund.get("country")
        or ""
    ).strip().upper()
    is_foreign_country = (
        bool(country)
        and bool(re.match(r"^[A-Z]{2,3}$", country))
        and (country not in ["US", "USA"])
    )

    is_foreign_adr = (
        bool(re.search(r"\bADR\b", desc))
        or asset_sub == "ADR"
        or is_foreign_country
        or bool(
            re.search(
                r"\b(CHINA|ISRAEL|UNITED KINGDOM|BERMUDA|NETHERLANDS|GERMANY|SWITZERLAND|FRANCE|IRELAND|JAPAN|TAIWAN|BRAZIL|CANADA|KOREA|SOUTH AFRICA)\b",
                desc,
            )
        )
    )

    shares_val = raw_shares
    if is_halted_or_unquoted:
        shares_state = "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
    elif is_warrant:
        shares_val = None
        shares_state = "UNAVAILABLE_FOR_WARRANT"
    elif is_structural_wrapper:
        shares_val = None
        shares_state = "UNAVAILABLE_FOR_ETN_OR_FUND"
    elif is_foreign_adr:
        shares_state = (
            "VENDOR_PROVIDED_FOREIGN_ISSUER_UNVERIFIED"
            if raw_shares is not None
            else "UNAVAILABLE_FOR_FOREIGN_ADR"
        )
    elif raw_shares is not None and raw_shares > 0:
        shares_state = "CONFIRMED"
    else:
        shares_state = "VENDOR_UNAVAILABLE"

    if is_halted_or_unquoted:
        pe_val, pe_state = None, "VENDOR_UNAVAILABLE_ASSET_HALTED"
        eps_val, eps_state = None, "VENDOR_UNAVAILABLE_ASSET_HALTED"
    elif is_warrant:
        pe_val, pe_state = None, "NOT_APPLICABLE_WARRANT"
        eps_val, eps_state = None, "VENDOR_UNAVAILABLE_WARRANT_NO_EPS"
    elif is_structural_wrapper:
        pe_val, pe_state = None, "NOT_APPLICABLE_ETF_OR_FUND"
        eps_val, eps_state = None, "VENDOR_UNAVAILABLE_ETF_OR_ETN_NO_EPS"
    elif raw_pe is not None and (
        raw_pe >= 9999.0
        or raw_pe <= -9999.0
        or math.isinf(raw_pe)
        or math.isnan(raw_pe)
    ):
        pe_val, pe_state = None, "VENDOR_SENTINEL_MAGNITUDE"
        eps_val = raw_eps
        eps_state = "AS_REPORTED" if raw_eps is not None else "VENDOR_UNAVAILABLE"
    else:
        pe_val = raw_pe
        pe_state = "AS_REPORTED" if raw_pe is not None else "VENDOR_UNAVAILABLE"
        if is_foreign_adr and raw_eps is None:
            eps_val, eps_state = None, "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED"
        else:
            eps_val = raw_eps
            eps_state = "AS_REPORTED" if raw_eps is not None else "VENDOR_UNAVAILABLE"

    if raw_div_y is None:
        div_y_basis = "VENDOR_UNAVAILABLE"
    elif raw_div_y == 0.0 or raw_div_amt == 0.0:
        div_y_basis = "AS_REPORTED_ZERO_NON_PAYER" if not is_halted_or_unquoted else "VENDOR_UNAVAILABLE"
    elif raw_div_y > 0.0:
        div_y_basis = "ANNUAL_VENDOR_CONFIRMED"
    else:
        div_y_basis = "VENDOR_UNAVAILABLE"

    is_zero_div = (raw_div_y == 0.0 or raw_div_amt == 0.0 or raw_div_y is None)
    div_freq_state = None
    if not is_zero_div and raw_div_y is not None and raw_div_y > 0.0:
        if raw_div_freq is None or raw_div_freq == 0.0:
            div_freq_state = "VENDOR_UNAVAILABLE_FREQUENCY_UNSPECIFIED"
            raw_div_freq = 0.0
    elif is_zero_div:
        if raw_div_freq is not None and raw_div_freq > 0.0:
            div_freq_state = "GHOST_FREQUENCY_RECONCILED_NON_PAYER"
            raw_div_freq = 0.0
        else:
            raw_div_freq = 0.0

    net_m = safe_float(fund.get("netProfitMarginTTM"))
    op_m = safe_float(fund.get("operatingMarginTTM"))
    gross_m = safe_float(fund.get("grossMarginTTM"))

    if net_m is not None and op_m is not None:
        if abs(net_m - op_m) < 1e-6 and abs(net_m) > 0.0:
            margin_suspect, margin_reason, margin_state = (
                True,
                "vendor_net_and_operating_margins_identical",
                "SUSPECT_VENDOR_DATA",
            )
        else:
            margin_suspect, margin_reason, margin_state = (
                False,
                "margins_structurally_differentiated",
                "CONFIRMED",
            )
    else:
        margin_suspect, margin_reason, margin_state = (
            None,
            None,
            "VENDOR_UNAVAILABLE_INPUTS_ABSENT",
        )

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

    bid_p = safe_float(quote.get("bidPrice"))
    ask_p = safe_float(quote.get("askPrice"))
    bid_s = safe_float(quote.get("bidSize", 0.0))
    ask_s = safe_float(quote.get("askSize", 0.0))
    tot_vol = safe_float(quote.get("totalVolume", 0.0))

    liq_state = "FULL_PASSTHROUGH"
    book_note, book_reason, spread_warn = None, None, None

    if is_mutual_fund:
        liq_state = "NOT_APPLICABLE_MUTUAL_FUND_NO_INTRADAY_BOOK"
        book_reason = "mutual_fund_nav_priced_once_daily"
        book_note = "NO_INTRADAY_ORDER_BOOK_MUTUAL_FUND"
    elif is_halted_or_unquoted:
        liq_state = "UNVERIFIED_EMPTY_ORDER_BOOK"
        book_reason = "asset_halted_or_unquoted"
        book_note = "EMPTY_ORDER_BOOK_ASSET_HALTED"
    elif bid_s == 0.0 and ask_s == 0.0:
        liq_state = "UNVERIFIED_EMPTY_ORDER_BOOK"
        if tot_vol is not None and tot_vol > 0.0:
            book_reason = "zero_bid_ask_depth_with_reported_volume"
            book_note = "ZERO_BID_ASK_DEPTH_REPORTED"
        else:
            book_reason = "zero_book_activity_recorded"
            book_note = "EMPTY_ORDER_BOOK_NO_VOLUME"

    if bid_p is not None and ask_p is not None and bid_p > 0.0:
        if (ask_p - bid_p) / bid_p > 2.0:
            spread_warn = "EXTREME_SPREAD_EXCEEDS_200_PCT_HEURISTIC"

    liq_dict: Dict[str, Any] = {
        "state": liq_state,
        "bidPrice": f"${bid_p:.2f}" if bid_p is not None else None,
        "askPrice": f"${ask_p:.2f}" if ask_p is not None else None,
        "bidSize": bid_s,
        "askSize": ask_s,
        "totalVolume": tot_vol,
        "vol10DayAvg": safe_float(fund.get("vol10DayAvg")),
        "vol10DayAvg_state": (
            "AS_REPORTED"
            if fund.get("vol10DayAvg") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "vol3MonthAvg_state": "VENDOR_FIELD_NOT_PROVIDED",
        "vol1YearAvg": safe_float(fund.get("vol1YearAvg")),
        "vol1YearAvg_state": (
            "VENDOR_SUSPECT_ZERO"
            if fund.get("vol1YearAvg") == 0.0
            else (
                "AS_REPORTED"
                if fund.get("vol1YearAvg") is not None
                else "VENDOR_UNAVAILABLE"
            )
        ),
    }
    if book_reason:
        liq_dict["reason"] = book_reason
    if book_note:
        liq_dict["book_liquidity_note"] = book_note
    if spread_warn:
        liq_dict["spread_warning"] = spread_warn

    fund_dict: Dict[str, Any] = {
        "beta": safe_float(fund.get("beta")),
        "beta_state": (
            "AS_REPORTED" if fund.get("beta") is not None else "VENDOR_UNAVAILABLE"
        ),
        "peRatio": pe_val,
        "peRatio_state": pe_state,
        "pegRatio": safe_float(fund.get("pegRatio")),
        "pegRatio_state": (
            "AS_REPORTED"
            if fund.get("pegRatio") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "pcfRatio": safe_float(fund.get("pcfRatio")),
        "pcfRatio_state": (
            "AS_REPORTED"
            if fund.get("pcfRatio") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "pbRatio": safe_float(fund.get("pbRatio")),
        "totalDebtToEquity": safe_float(fund.get("totalDebtToEquity")),
        "totalDebtToEquity_basis": "VENDOR_RAW_UNVERIFIED",
        "grossMarginTTM": gross_m,
        "netProfitMarginTTM": net_m,
        "operatingMarginTTM": op_m,
        "margin_fields_suspect": margin_suspect,
        "margin_fields_suspect_reason": margin_reason,
        "margin_fields_suspect_state": margin_state,
        "returnOnEquity": safe_float(fund.get("returnOnEquity")),
        "returnOnEquity_state": (
            "AS_REPORTED"
            if fund.get("returnOnEquity") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "returnOnAssets": safe_float(fund.get("returnOnAssets")),
        "returnOnAssets_state": (
            "AS_REPORTED"
            if fund.get("returnOnAssets") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "eps": eps_val,
        "eps_state": eps_state,
        "revChangeYear": safe_float(fund.get("revChangeYear")),
        "revChangeYear_state": (
            "AS_REPORTED"
            if fund.get("revChangeYear") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        "divYield": raw_div_y if raw_div_y is not None else 0.0,
        "divYield_basis": div_y_basis,
        "divYield_raw": raw_div_y if raw_div_y is not None else 0.0,
        "divAmount": f"${raw_div_amt:.2f}" if raw_div_amt is not None else "$0.00",
        "div_amount_basis": "ANNUAL",
        "divFreq": raw_div_freq,
        "sharesOutstanding": shares_val,
        "shares_outstanding_state": shares_state,
        "marketCap": safe_float(fund.get("marketCap")),
        "marketCap_unit": "VENDOR_RAW_UNVERIFIED",
    }
    if div_freq_state:
        fund_dict["divFreq_state"] = div_freq_state

    return {
        "phase_0_grounding": {
            "symbol": clean_sym,
            "company_name": desc,
            "lastPrice": f"${last_p:.2f}" if last_p is not None else None,
            "closePrice": f"${close_p:.2f}" if close_p is not None else None,
            "quoteTime_ISO_ET": q_time_iso,
            "quote_age_seconds": q_age,
            "quote_age_classification": q_class,
        },
        "step_1_fundamentals": fund_dict,
        "short_locate_status": short_dict,
        "step_8_and_9_liquidity_and_sizing": liq_dict,
    }


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
        d = _parse_client_response(r)
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
        d = _parse_client_response(r)
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
                parsed = _parse_client_response(r)
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
            parsed = _parse_client_response(r)
            if parsed and ("callExpDateMap" in parsed or "putExpDateMap" in parsed):
                telemetry["fallback_to_default_chain"] = True
                _parse_chain_payload(parsed, provenance="DEFAULT_CHAIN_FALLBACK")
        except Exception as e:
            logger.warning("Default chain fallback failed for %s: %s", clean_sym, e)

    return vol_30d, underlying_price, all_contracts, telemetry