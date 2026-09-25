# src/schwab_raw_marketdata.py
from __future__ import annotations
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import pandas as pd

def safe_float(v: Any) -> Optional[float]:
    if v is None or pd.isna(v):
        return None
    try:
        f = float(str(v).replace("$", "").replace(",", "").strip())
        if math.isnan(f) or math.isinf(f):
            return None
        return 0.0 if (f == 0.0 or abs(f) < 1e-12) else f
    except (ValueError, TypeError):
        return None

def safe_div(n: Any, d: Any) -> Optional[float]:
    fn, fd = safe_float(n), safe_float(d)
    if fn is None or fd is None or fd == 0.0:
        return None
    res = fn / fd
    return None if math.isnan(res) or math.isinf(res) else res

def _parse_client_response(resp: Any) -> Optional[Dict[str, Any]]:
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp
    if hasattr(resp, "status_code"):
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                return None
        return None
    return None

def extract_market_open_status(client: Any) -> bool:
    try:
        r = client.get_market_hours("equity")
        d = _parse_client_response(r)
        if d:
            eq = d.get("equity", {})
            for m in ["EQ", "equity"]:
                if m in eq and "isOpen" in eq[m]:
                    return bool(eq[m]["isOpen"])
    except Exception:
        pass
    now_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
    if now_et.weekday() >= 5:
        return False
    return (9, 30) <= (now_et.hour, now_et.minute) < (16, 0)

def extract_strict_underlying_data(client: Any, symbol: str, tz_et: ZoneInfo) -> Dict[str, Any]:
    r = client.get_quote(symbol)
    res_dict = _parse_client_response(r)
    if res_dict is None:
        raise ValueError(f"Failed to fetch valid quote response for {symbol}")
    data = res_dict.get(symbol, {})
    ref = data.get("reference", {})
    quote = data.get("quote", {})
    fund = data.get("fundamental", {})
    asset_sub = str(ref.get("assetSubType", "") or "").upper()
    asset_main = str(ref.get("assetMainType", "") or "").upper()
    desc = str(ref.get("description", "") or "").upper()

    is_structural_wrapper = (
        asset_sub in ["ETF", "ETN", "MUTUAL_FUND", "CEF"] or
        asset_main in ["ETF", "ETN", "MUTUAL_FUND", "FUND"] or
        bool(re.search(r"\b(ETN|ETF|FUND|TRUST|INDEX NOTE|CEF|CLOSED-END|DLY|BULL|BEAR|2X|3X)\b", desc))
    )

    last_p = safe_float(quote.get("lastPrice"))
    close_p = safe_float(quote.get("closePrice"))
    q_time_raw = quote.get("quoteTime", 0)
    if q_time_raw:
        q_time_iso = datetime.fromtimestamp(q_time_raw / 1000.0, tz=timezone.utc).astimezone(tz_et).isoformat()
        q_age = round((datetime.now(timezone.utc).timestamp() - (q_time_raw / 1000.0)), 2)
    else:
        q_time_iso = None
        q_age = None

    if q_age is not None:
        q_class = "REAL_TIME" if q_age <= 60.0 else ("RECENT" if q_age <= 600.0 else ("DELAYED" if q_age <= 3600.0 else "STALE"))
    else:
        q_class = "UNKNOWN"

    raw_shares = safe_float(fund.get("sharesOutstanding"))
    raw_pe = safe_float(fund.get("peRatio"))
    raw_eps = safe_float(fund.get("eps"))
    raw_div_amt = safe_float(fund.get("divAmount"))
    raw_div_y = safe_float(fund.get("divYield"))
    raw_div_freq = safe_float(fund.get("divFreq"))

    is_foreign_adr = (
        bool(re.search(r"\bADR\b", desc)) or
        asset_sub == "ADR" or
        bool(re.search(r"\b(CHINA|ISRAEL|UNITED KINGDOM|BERMUDA|NETHERLANDS|GERMANY|SWITZERLAND|FRANCE|IRELAND|JAPAN|TAIWAN|BRAZIL|CANADA|KOREA|SOUTH AFRICA)\b", desc))
    )

    shares_val = raw_shares
    if is_structural_wrapper:
        shares_val = None
        shares_state = "UNAVAILABLE_FOR_ETN_OR_FUND"
    elif last_p == 0.0 or close_p == 0.0:
        shares_state = "CONFIRMED"
    elif is_foreign_adr:
        if raw_shares is not None:
            shares_state = "VENDOR_PROVIDED_FOREIGN_ISSUER_UNVERIFIED"
        else:
            shares_state = "UNAVAILABLE_FOR_FOREIGN_ADR"
    elif raw_shares is not None and raw_shares > 0:
        shares_state = "CONFIRMED"
    else:
        shares_state = "VENDOR_UNAVAILABLE"

    if is_structural_wrapper:
        pe_val = None
        pe_state = "NOT_APPLICABLE_ETF_OR_FUND"
        eps_val = None
        eps_state = "VENDOR_UNAVAILABLE_ETF_OR_ETN_NO_EPS"
    elif last_p == 0.0 or close_p == 0.0:
        pe_val = raw_pe
        pe_state = "AS_REPORTED"
        eps_val = raw_eps
        eps_state = "AS_REPORTED"
    else:
        pe_val = raw_pe
        pe_state = "AS_REPORTED" if raw_pe is not None else "VENDOR_UNAVAILABLE"
        if is_foreign_adr and raw_eps is None:
            eps_val = None
            eps_state = "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED"
        else:
            eps_val = raw_eps
            eps_state = "AS_REPORTED" if raw_eps is not None else "VENDOR_UNAVAILABLE"

    is_zero_div = (raw_div_y == 0.0 or raw_div_amt == 0.0)
    div_y_basis = "AS_REPORTED_ZERO_NON_PAYER" if is_zero_div else ("ANNUAL_VENDOR_CONFIRMED" if raw_div_y is not None else "VENDOR_UNAVAILABLE")

    div_freq_state = None
    if not is_zero_div and raw_div_y is not None and raw_div_freq is None:
        div_freq_state = "VENDOR_UNAVAILABLE_FREQUENCY_UNSPECIFIED"

    net_m = safe_float(fund.get("netProfitMarginTTM"))
    op_m = safe_float(fund.get("operatingMarginTTM"))
    gross_m = safe_float(fund.get("grossMarginTTM"))

    if net_m is not None and op_m is not None:
        if abs(net_m - op_m) < 1e-6 and abs(net_m) > 0.0:
            margin_suspect = True
            margin_reason = "vendor_net_and_operating_margins_identical"
            margin_state = "SUSPECT_VENDOR_DATA"
        else:
            margin_suspect = False
            margin_reason = "margins_structurally_differentiated"
            margin_state = "CONFIRMED"
    else:
        margin_suspect = None
        margin_reason = None
        margin_state = "VENDOR_UNAVAILABLE_INPUTS_ABSENT"

    short_stat = quote.get("shortLocate", {})
    is_shortable = bool(short_stat.get("isShortable", quote.get("isShortable", True)))
    is_htb = bool(short_stat.get("isHardToBorrow", quote.get("isHardToBorrow", False)))
    raw_htb_rate = safe_float(short_stat.get("rate", quote.get("htbRate")))

    htb_rate_val = raw_htb_rate
    raw_htb_store = None
    if not is_htb:
        htb_status = "NOT_APPLICABLE_ETB"
    elif raw_htb_rate is not None and raw_htb_rate < 0.0:
        htb_status = "INVALID_NEGATIVE_VENDOR_RATE"
        raw_htb_store = raw_htb_rate
        htb_rate_val = None
    elif raw_htb_rate == 0.0:
        htb_status = "HTB_FLAG_ACTIVE_RATE_PENDING_BROKER_LOCATE"
    elif raw_htb_rate is not None:
        htb_status = "LOCATE_AVAILABLE"
    else:
        htb_status = "VENDOR_UNAVAILABLE_LOCATE_PENDING"

    short_dict: Dict[str, Any] = {
        "state": "FULL_PASSTHROUGH",
        "isShortable": is_shortable,
        "isHardToBorrow": is_htb,
        "htbRate": htb_rate_val,
        "htb_rate_status": htb_status
    }
    if raw_htb_store is not None:
        short_dict["htbRate_raw"] = raw_htb_store

    bid_p = safe_float(quote.get("bidPrice"))
    ask_p = safe_float(quote.get("askPrice"))
    bid_s = safe_float(quote.get("bidSize", 0.0))
    ask_s = safe_float(quote.get("askSize", 0.0))
    tot_vol = safe_float(quote.get("totalVolume", 0.0))

    liq_state = "FULL_PASSTHROUGH"
    book_note = None
    book_reason = None
    spread_warn = None

    if bid_s == 0.0 and ask_s == 0.0:
        liq_state = "UNVERIFIED_EMPTY_ORDER_BOOK"
        if tot_vol is not None and tot_vol > 0.0:
            book_reason = "zero_bid_ask_depth_with_reported_volume"
            book_note = "ZERO_BID_ASK_DEPTH_REPORTED"
        else:
            book_reason = "zero_book_activity_recorded"
            book_note = "EMPTY_ORDER_BOOK_NO_VOLUME"

    if bid_p is not None and ask_p is not None and bid_p > 0.0:
        rel_spr = (ask_p - bid_p) / bid_p
        if rel_spr > 2.0:
            spread_warn = "EXTREME_SPREAD_EXCEEDS_200_PCT_HEURISTIC"

    liq_dict: Dict[str, Any] = {
        "state": liq_state,
        "bidPrice": f"${bid_p:.2f}" if bid_p is not None else None,
        "askPrice": f"${ask_p:.2f}" if ask_p is not None else None,
        "bidSize": bid_s,
        "askSize": ask_s,
        "totalVolume": tot_vol,
        "vol10DayAvg": safe_float(fund.get("vol10DayAvg")),
        "vol10DayAvg_state": "AS_REPORTED" if fund.get("vol10DayAvg") is not None else "VENDOR_UNAVAILABLE",
        "vol3MonthAvg_state": "VENDOR_FIELD_NOT_PROVIDED",
        "vol1YearAvg": safe_float(fund.get("vol1YearAvg")),
        "vol1YearAvg_state": "VENDOR_SUSPECT_ZERO" if fund.get("vol1YearAvg") == 0.0 else ("AS_REPORTED" if fund.get("vol1YearAvg") is not None else "VENDOR_UNAVAILABLE")
    }
    if book_reason:
        liq_dict["reason"] = book_reason
    if book_note:
        liq_dict["book_liquidity_note"] = book_note
    if spread_warn:
        liq_dict["spread_warning"] = spread_warn

    fund_dict: Dict[str, Any] = {
        "beta": safe_float(fund.get("beta")),
        "beta_state": "AS_REPORTED" if fund.get("beta") is not None else "VENDOR_UNAVAILABLE",
        "peRatio": pe_val,
        "peRatio_state": pe_state,
        "pegRatio": safe_float(fund.get("pegRatio")),
        "pegRatio_state": "AS_REPORTED" if fund.get("pegRatio") is not None else "VENDOR_UNAVAILABLE",
        "pcfRatio": safe_float(fund.get("pcfRatio")),
        "pcfRatio_state": "AS_REPORTED" if fund.get("pcfRatio") is not None else "VENDOR_UNAVAILABLE",
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
        "returnOnEquity_state": "AS_REPORTED" if fund.get("returnOnEquity") is not None else "VENDOR_UNAVAILABLE",
        "returnOnAssets": safe_float(fund.get("returnOnAssets")),
        "returnOnAssets_state": "AS_REPORTED" if fund.get("returnOnAssets") is not None else "VENDOR_UNAVAILABLE",
        "eps": eps_val,
        "eps_state": eps_state,
        "revChangeYear": safe_float(fund.get("revChangeYear")),
        "revChangeYear_state": "AS_REPORTED" if fund.get("revChangeYear") is not None else "VENDOR_UNAVAILABLE",
        "divYield": raw_div_y if raw_div_y is not None else 0.0,
        "divYield_basis": div_y_basis,
        "divYield_raw": raw_div_y if raw_div_y is not None else 0.0,
        "divAmount": f"${raw_div_amt:.2f}" if raw_div_amt is not None else "$0.00",
        "div_amount_basis": "ANNUAL",
        "divFreq": raw_div_freq,
        "sharesOutstanding": shares_val,
        "shares_outstanding_state": shares_state,
        "marketCap": safe_float(fund.get("marketCap")),
        "marketCap_unit": "VENDOR_RAW_UNVERIFIED"
    }
    if div_freq_state:
        fund_dict["divFreq_state"] = div_freq_state

    return {
        "phase_0_grounding": {
            "symbol": symbol,
            "company_name": desc,
            "lastPrice": f"${last_p:.2f}" if last_p is not None else None,
            "closePrice": f"${close_p:.2f}" if close_p is not None else None,
            "quoteTime_ISO_ET": q_time_iso,
            "quote_age_seconds": q_age,
            "quote_age_classification": q_class
        },
        "step_1_fundamentals": fund_dict,
        "short_locate_status": short_dict,
        "step_8_and_9_liquidity_and_sizing": liq_dict
    }

def extract_in_memory_price_history(client: Any, symbol: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        r = client.get_price_history(
            symbol,
            period_type=config.get("HISTORICAL_PERIOD_TYPE", "year"),
            period=config.get("HISTORICAL_PERIOD", 1),
            frequency_type=config.get("HISTORICAL_FREQUENCY_TYPE", "daily"),
            frequency=config.get("HISTORICAL_FREQUENCY", 1),
            need_extended_hours_data=config.get("HISTORICAL_NEED_EXTENDED_HOURS", False)
        )
        d = _parse_client_response(r)
        if d:
            candles = d.get("candles", []) or []
            valid_candles = [
                c for c in candles
                if safe_float(c.get("close")) is not None and safe_float(c.get("close")) > 0.01
                and safe_float(c.get("open")) is not None and safe_float(c.get("open")) > 0.01
            ]
            return valid_candles
    except Exception:
        pass
    return []

def extract_in_memory_option_expirations(client: Any, symbol: str) -> List[Dict[str, Any]]:
    try:
        r = client.get_option_expiration_chain(symbol)
        d = _parse_client_response(r)
        if d:
            return d.get("expirationList", []) or []
    except Exception:
        pass
    return []

def resolve_optimal_expirations(exp_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    valid = [e for e in exp_list if safe_float(e.get("daysToExpiration")) is not None and int(e["daysToExpiration"]) >= 0]
    if not valid:
        return []
    sorted_exps = sorted(valid, key=lambda x: int(x["daysToExpiration"]))
    front = sorted_exps[0]
    t1_cands = [e for e in sorted_exps if int(e["daysToExpiration"]) <= 30]
    t2_cands = [e for e in sorted_exps if int(e["daysToExpiration"]) >= 30]
    t1 = t1_cands[-1] if t1_cands else sorted_exps[0]
    t2 = t2_cands[0] if t2_cands else sorted_exps[-1]
    targets = [front, t1, t2]
    seen = set()
    uniq = []
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
    strike_proximities: bool = True
) -> Tuple[Optional[float], Optional[float], List[Dict[str, Any]], Dict[str, Any]]:
    telemetry = {
        "rejected_zero_strike_count": 0,
        "rejected_expired_contract_count": 0,
        "rejected_negative_mark_count": 0,
        "rejected_negative_price_count": 0
    }
    if not target_expirations:
        return None, None, [], telemetry
    all_contracts: List[Dict[str, Any]] = []
    underlying_price = None
    vol_30d = None
    for exp in target_expirations:
        exp_date = exp.get("expirationDate")
        try:
            r = client.get_option_chain(
                symbol,
                strike_count=strike_window,
                from_date=exp_date,
                to_date=exp_date,
                strategy=strategy
            )
            payload = _parse_client_response(r)
            if not payload:
                continue
            if underlying_price is None:
                underlying_price = safe_float(payload.get("underlyingPrice"))
            if vol_30d is None:
                vol_30d = safe_float(payload.get("volatility"))
            for book_key in ["callExpDateMap", "putExpDateMap"]:
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
                            if (bid_val is not None and bid_val < 0) or (ask_val is not None and ask_val < 0):
                                telemetry["rejected_negative_price_count"] += 1
                                continue
                            all_contracts.append(c)
        except Exception:
            continue
    return vol_30d, underlying_price, all_contracts, telemetry
