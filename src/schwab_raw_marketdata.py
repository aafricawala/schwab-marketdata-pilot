# src/schwab_raw_marketdata.py
from __future__ import annotations
import math, re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import pandas as pd

ALLOWED_DIV_FREQS = {1.0, 2.0, 4.0, 12.0}

def safe_float(v: Any) -> Optional[float]:
    if v is None or pd.isna(v): return None
    try:
        f = float(str(v).replace("$", "").replace(",", "").strip())
        if math.isnan(f) or math.isinf(f): return None
        return 0.0 if f == 0.0 else f
    except (ValueError, TypeError): return None

def extract_market_open_status(client: Any, *args: Any, **kwargs: Any) -> Optional[bool]:
    try:
        if hasattr(client, "get_market_hours"):
            h = client.get_market_hours("equity")
            if isinstance(h, dict):
                if "isOpen" in h: return bool(h.get("isOpen", False))
                eq = h.get("equity", {}).get("EQ", {})
                if "isOpen" in eq: return bool(eq.get("isOpen", False))
    except Exception: pass
    return None

def resolve_optimal_expirations(exp_records: List[Dict[str, Any]]) -> List[str]:
    if not exp_records: return []
    valid = [r for r in exp_records if safe_float(r.get("daysToExpiration", -1)) is not None and safe_float(r.get("daysToExpiration")) >= 4]
    if not valid: return []
    s = sorted(valid, key=lambda x: safe_float(x.get("daysToExpiration", 9999)))
    f = s[0].get("expirationDate")
    le30 = [r for r in s if safe_float(r.get("daysToExpiration")) <= 30]
    ge30 = [r for r in s if safe_float(r.get("daysToExpiration")) > 30]
    t1 = le30[-1].get("expirationDate") if le30 else (s[1].get("expirationDate") if len(s) > 1 else f)
    t2 = ge30[0].get("expirationDate") if ge30 else (s[-1].get("expirationDate") if s else f)
    res = []
    for x in [f, t1, t2]:
        if x and x not in res: res.append(x)
    return res

def extract_strict_underlying_data(client: Any, symbol: str, tz: Optional[ZoneInfo] = None) -> Dict[str, Any]:
    clean_sym = symbol.strip().upper()
    raw_payload = client.get_quote(symbol=clean_sym, fields="quote,fundamental,reference")
    payload = raw_payload.get(clean_sym) or raw_payload.get(clean_sym.lower()) or raw_payload
    if isinstance(payload, dict) and clean_sym in payload and isinstance(payload[clean_sym], dict):
        payload = payload[clean_sym]
    quote = payload.get("quote", {}) if isinstance(payload, dict) else {}
    fund = payload.get("fundamental", {}) if isinstance(payload, dict) else {}
    ref = payload.get("reference", {}) if isinstance(payload, dict) else {}

    asset_type = str(ref.get("assetType") or quote.get("assetType") or "").upper()
    description = str(ref.get("description") or quote.get("description") or "").upper()
    is_adr = bool(ref.get("isAdr") or asset_type == "ADR" or "ADR" in description)
    country = str(ref.get("country") or quote.get("country") or "").upper()
    is_foreign = is_adr or (bool(country) and country not in {"US", "USA"})

    raw_shares = safe_float(fund.get("sharesOutstanding"))
    raw_pe = safe_float(fund.get("peRatio"))
    raw_div_y = safe_float(fund.get("dividendYield") or fund.get("divYield"))
    raw_div_a = safe_float(fund.get("dividendAmount") or fund.get("divAmount"))
    gross_m = safe_float(fund.get("grossMarginTTM") or fund.get("grossMargin"))
    net_m = safe_float(fund.get("netProfitMarginTTM") or fund.get("netProfitMargin"))
    op_m = safe_float(fund.get("operatingMarginTTM") or fund.get("operatingMargin"))
    m_absent = (gross_m is None and net_m is None and op_m is None)
    tot_debt = safe_float(fund.get("totalDebtToEquity"))

    last_p = safe_float(quote.get("lastPrice"))
    close_p = safe_float(quote.get("closePrice"))
    bid_p = safe_float(quote.get("bidPrice"))
    ask_p = safe_float(quote.get("askPrice"))
    bid_sz = safe_float(quote.get("bidSize"))
    ask_sz = safe_float(quote.get("askSize"))
    tot_vol = safe_float(quote.get("totalVolume"))

    is_unquoted_halted = (last_p is None and close_p is None and tot_vol is None)

    is_wrapper_explicit = (
        not is_unquoted_halted and (
            asset_type in {"ETF", "ETN", "MUTUAL_FUND", "COLLECTIVE_INVESTMENT", "CLOSED_END_FUND"}
            or bool(re.search(r"\b(ETN|ETF|FUND|TRUST|INDEX NOTE|CEF|CLOSED-END)\b", description))
        )
    )
    is_structural_wrapper = (
        is_wrapper_explicit or (
            not is_unquoted_halted and m_absent and tot_debt is None and (raw_pe is None or raw_pe <= 0.0)
            and (raw_shares is None or (raw_div_y is not None and raw_div_y > 10.0))
        )
    )

    q_epoch = quote.get("quoteTime")
    zone = tz or ZoneInfo("America/New_York")
    now_utc = datetime.now(timezone.utc)
    q_iso = datetime.fromtimestamp(q_epoch / 1000.0, tz=timezone.utc).astimezone(zone).isoformat() if q_epoch and safe_float(q_epoch) and q_epoch > 0 else None
    quote_age = max(0.0, (now_utc.timestamp() - (q_epoch / 1000.0))) if q_epoch and safe_float(q_epoch) and q_epoch > 0 else None
    if quote_age is not None:
        q_class = "REAL_TIME" if quote_age < 60.0 else ("RECENT" if quote_age <= 600.0 else ("DELAYED" if quote_age <= 3600.0 else "STALE"))
        q_reason = None
    else:
        q_class = "UNKNOWN"
        q_reason = "quote_time_unavailable_or_halted_asset"

    comp_name = description if description else clean_sym
    grounding = {
        "symbol": clean_sym,
        "company_name": comp_name,
        "lastPrice": f"${last_p:.2f}" if last_p is not None else None,
        "closePrice": f"${close_p:.2f}" if close_p is not None else None,
        "quoteTime_ISO_ET": q_iso,
        "quote_age_seconds": round(quote_age, 2) if quote_age is not None else None,
        "quote_age_classification": q_class
    }
    if q_reason:
        grounding["quote_age_reason"] = q_reason
    if is_unquoted_halted and not description:
        grounding["company_name_status"] = "FALLBACK_TICKER_ONLY_UNQUOTED"

    roe = safe_float(fund.get("returnOnEquity") or fund.get("roe"))
    roa = safe_float(fund.get("returnOnAssets") or fund.get("roa"))
    if net_m is not None and op_m is not None:
        m_suspect = bool(net_m == op_m)
        m_suspect_state = "AS_REPORTED"
        m_suspect_reason = "vendor_net_and_operating_margins_identical" if m_suspect else None
    else:
        m_suspect = None
        m_suspect_state = "VENDOR_UNAVAILABLE_INPUTS_ABSENT"
        m_suspect_reason = None

    if is_unquoted_halted:
        shares_out = raw_shares
        shares_state = "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
    elif is_structural_wrapper:
        shares_out = None
        shares_state = "UNAVAILABLE_FOR_ETN_OR_FUND"
    elif raw_shares is not None and raw_shares > 0:
        shares_out = raw_shares
        shares_state = "VENDOR_PROVIDED_FOREIGN_ISSUER_UNVERIFIED" if is_foreign else "CONFIRMED"
    else:
        shares_out = None
        shares_state = "UNAVAILABLE_FOR_FOREIGN_ADR" if is_foreign else "VENDOR_UNAVAILABLE"

    eps_val = safe_float(fund.get("eps") or fund.get("epsTTM"))
    if is_unquoted_halted and eps_val is None:
        eps = None
        eps_state = "VENDOR_UNAVAILABLE_ASSET_HALTED"
    elif is_structural_wrapper:
        eps = None
        eps_state = "VENDOR_UNAVAILABLE_ETF_OR_ETN_NO_EPS"
    elif is_foreign and (eps_val is None or eps_val == 0.0 or abs(eps_val) < 0.01):
        eps = None
        eps_state = "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED"
    elif eps_val is not None:
        eps = eps_val
        eps_state = "AS_REPORTED"
    else:
        eps = 0.0 if ("eps" in fund and fund.get("eps") == 0) else None
        eps_state = "AS_REPORTED" if eps == 0.0 else "VENDOR_UNAVAILABLE"

    if is_unquoted_halted and raw_pe is None:
        pe_out = None
        pe_state = "VENDOR_UNAVAILABLE_ASSET_HALTED"
    elif is_structural_wrapper:
        pe_out = None
        pe_state = "NOT_APPLICABLE_ETF_OR_FUND"
    else:
        pe_out = raw_pe
        pe_state = "AS_REPORTED" if raw_pe is not None else "VENDOR_UNAVAILABLE"

    raw_div_f = safe_float(fund.get("dividendFreq") or fund.get("divFreq"))
    is_non_payer = (raw_div_y == 0.0 or raw_div_a == 0.0 or (raw_div_y is None and raw_div_a is None))
    if is_non_payer:
        div_y, div_y_raw, div_amt, freq, div_basis = 0.0, 0.0, 0.0, 0.0, "AS_REPORTED_ZERO_NON_PAYER"
    else:
        div_y = raw_div_y
        div_y_raw = raw_div_y
        div_amt = raw_div_a if raw_div_a is not None else 0.0
        freq = raw_div_f if raw_div_f in ALLOWED_DIV_FREQS else None
        div_basis = "ANNUAL_VENDOR_CONFIRMED" if raw_div_y is not None else "VENDOR_UNAVAILABLE"

    raw_mcap = safe_float(fund.get("marketCap") or fund.get("marketCapitalization"))

    step1 = {
        "beta": safe_float(fund.get("beta")),
        "beta_state": "AS_REPORTED" if safe_float(fund.get("beta")) is not None else "VENDOR_UNAVAILABLE",
        "peRatio": pe_out,
        "peRatio_state": pe_state,
        "pegRatio": safe_float(fund.get("pegRatio")),
        "pegRatio_state": "AS_REPORTED" if safe_float(fund.get("pegRatio")) is not None else "VENDOR_UNAVAILABLE",
        "pcfRatio": safe_float(fund.get("pcfRatio")),
        "pcfRatio_state": "AS_REPORTED" if safe_float(fund.get("pcfRatio")) is not None else "VENDOR_UNAVAILABLE",
        "pbRatio": safe_float(fund.get("pbRatio")),
        "totalDebtToEquity": tot_debt,
        "totalDebtToEquity_basis": "VENDOR_RAW_UNVERIFIED",
        "grossMarginTTM": gross_m,
        "netProfitMarginTTM": net_m,
        "operatingMarginTTM": op_m,
        "margin_fields_suspect": m_suspect,
        "margin_fields_suspect_reason": m_suspect_reason,
        "margin_fields_suspect_state": m_suspect_state,
        "returnOnEquity": roe,
        "returnOnEquity_state": "AS_REPORTED" if roe is not None else "VENDOR_UNAVAILABLE",
        "returnOnAssets": roa,
        "returnOnAssets_state": "AS_REPORTED" if roa is not None else "VENDOR_UNAVAILABLE",
        "eps": eps,
        "eps_state": eps_state,
        "revChangeYear": safe_float(fund.get("revChangeYear")),
        "revChangeYear_state": "AS_REPORTED",
        "divYield": div_y,
        "divYield_basis": div_basis,
        "divYield_raw": div_y_raw,
        "divAmount": f"${div_amt:.2f}",
        "div_amount_basis": "ANNUAL",
        "divFreq": freq,
        "sharesOutstanding": shares_out,
        "shares_outstanding_state": shares_state,
        "marketCap": raw_mcap,
        "marketCap_unit": "VENDOR_RAW_UNVERIFIED"
    }

    is_short = ref.get("isShortable")
    is_htb = ref.get("isHardToBorrow")
    raw_htb_r = safe_float(ref.get("htbRate"))
    if raw_htb_r is not None and raw_htb_r < 0.0:
        htb_r, htb_status = None, "INVALID_NEGATIVE_VENDOR_RATE"
    elif is_htb and (raw_htb_r == 0.0 or raw_htb_r is None):
        htb_r, htb_status = 0.0, "HTB_FLAG_ACTIVE_RATE_PENDING_BROKER_LOCATE"
    elif is_htb:
        htb_r, htb_status = raw_htb_r or 0.0, "RATE_CONFIRMED"
    else:
        htb_r, htb_status = raw_htb_r or 0.0, "NOT_APPLICABLE_ETB"

    short_loc = {
        "state": "FULL_PASSTHROUGH",
        "isShortable": is_short if isinstance(is_short, bool) else True,
        "isHardToBorrow": is_htb if isinstance(is_htb, bool) else False,
        "htbRate": htb_r,
        "htb_rate_status": htb_status
    }
    if raw_htb_r is not None and raw_htb_r < 0.0:
        short_loc["htbRate_raw"] = raw_htb_r

    is_zero_book = (tot_vol == 0.0 and (bid_sz == 0.0 or bid_sz is None) and (ask_sz == 0.0 or ask_sz is None))
    is_crossed = (bid_p is not None and ask_p is not None and bid_p == ask_p and (tot_vol == 0.0 or tot_vol is None))

    if is_unquoted_halted:
        liq_state, liq_reason = "UNKNOWN", "quote_book_empty_asset_halted_or_unquoted"
    elif is_crossed:
        liq_state, liq_reason = "SUSPECT_CROSSED_OR_ZERO_DEPTH", "bid_ask_identical_zero_trading_volume"
    elif is_zero_book:
        liq_state, liq_reason = "ZERO_BOOK_ACTIVITY_RECORDED", "no_volume_and_zero_book_depth"
    else:
        liq_state, liq_reason = "FULL_PASSTHROUGH", None

    v10 = safe_float(fund.get("vol10DayAvg") or fund.get("avg10DaysVolume"))
    v1y = safe_float(fund.get("vol1YearAvg") or fund.get("avg1YearVolume"))
    liq = {
        "state": liq_state,
        "bidPrice": f"${bid_p:.2f}" if bid_p is not None else None,
        "askPrice": f"${ask_p:.2f}" if ask_p is not None else None,
        "bidSize": bid_sz,
        "askSize": ask_sz,
        "totalVolume": tot_vol
    }
    if liq_reason: liq["reason"] = liq_reason
    if v10 is not None and v10 > 0.0:
        liq["vol10DayAvg"] = v10
        liq["vol10DayAvg_state"] = "AS_REPORTED"
    else:
        liq["vol10DayAvg_state"] = "VENDOR_SUSPECT_ZERO" if (v10 == 0.0 and tot_vol and tot_vol > 1000000.0) else "VENDOR_UNAVAILABLE"
    liq["vol3MonthAvg_state"] = "VENDOR_FIELD_NOT_PROVIDED"
    if v1y is not None and v1y > 0.0:
        liq["vol1YearAvg"] = v1y
        liq["vol1YearAvg_state"] = "AS_REPORTED"
    else:
        liq["vol1YearAvg_state"] = "VENDOR_SUSPECT_ZERO" if (v1y == 0.0 and tot_vol and tot_vol > 1000000.0) else "VENDOR_UNAVAILABLE"

    return {
        "phase_0_grounding": grounding,
        "step_1_fundamentals": step1,
        "short_locate_status": short_loc,
        "step_8_and_9_liquidity_and_sizing": liq
    }

def extract_in_memory_price_history(client: Any, symbol: str, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        raw = client.get_price_history(
            symbol=symbol.strip().upper(),
            period_type=cfg.get("HISTORICAL_PERIOD_TYPE", "year"),
            period=cfg.get("HISTORICAL_PERIOD", 1),
            frequency_type=cfg.get("HISTORICAL_FREQUENCY_TYPE", "daily"),
            frequency=cfg.get("HISTORICAL_FREQUENCY", 1),
            need_extended_hours=cfg.get("HISTORICAL_NEED_EXTENDED_HOURS", False)
        )
        candles = raw.get("candles", []) if isinstance(raw, dict) else []
        res = []
        for c in candles:
            o, h, l, cl = safe_float(c.get("open")), safe_float(c.get("high")), safe_float(c.get("low")), safe_float(c.get("close"))
            if all(x is not None and x > 0 for x in [o, h, l, cl]):
                res.append({"datetime": c.get("datetime"), "open": o, "high": h, "low": l, "close": cl, "volume": safe_float(c.get("volume"))})
        return res
    except Exception: return []

def extract_in_memory_option_expirations(client: Any, symbol: str) -> List[Dict[str, Any]]:
    try:
        p = client.get_option_expirations(symbol.strip().upper())
        el = p.get("expirationList", []) if isinstance(p, dict) else []
        return sorted([{"expirationDate": r.get("expirationDate"), "daysToExpiration": int(r.get("daysToExpiration"))} for r in el if r.get("expirationDate") and r.get("daysToExpiration") is not None], key=lambda x: x["daysToExpiration"])
    except Exception: return []

def extract_in_memory_option_chains(client: Any, symbol: str, target_expirations: List[str], strike_count: int = 14, strategy: str = "SINGLE", include_underlying_quote: bool = True) -> Tuple[Optional[float], Optional[float], List[Dict[str, Any]], Dict[str, Any]]:
    if not target_expirations:
        return None, None, [], {"rejected_zero_strike_count": 0, "rejected_expired_contract_count": 0, "rejected_negative_mark_count": 0, "rejected_negative_price_count": 0}
    try:
        f_date, t_date = target_expirations[0], target_expirations[-1]
        raw_chain = client.get_option_chain(symbol=symbol.strip().upper(), contract_type="ALL", strike_count=strike_count, include_underlying_quote=include_underlying_quote, strategy=strategy, from_date=f_date, to_date=t_date)
        vol_30d = safe_float(raw_chain.get("volatility"))
        u_quote = raw_chain.get("underlying", {}) or {}
        u_price = safe_float(u_quote.get("last")) or safe_float(u_quote.get("close")) or safe_float(u_quote.get("mark")) or safe_float(raw_chain.get("underlyingPrice"))
        records, tele = [], {"rejected_zero_strike_count": 0, "rejected_expired_contract_count": 0, "rejected_negative_mark_count": 0, "rejected_negative_price_count": 0}
        def parse_map(m: Dict[str, Any], default_ind: str):
            if not isinstance(m, dict): return
            for exp_key, s_map in m.items():
                parts = exp_key.split(":")
                dte = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
                if dte is not None and dte < 0:
                    tele["rejected_expired_contract_count"] += 1
                    continue
                if not isinstance(s_map, dict): continue
                for _, clist in s_map.items():
                    if not isinstance(clist, list): continue
                    for c in clist:
                        k = safe_float(c.get("strikePrice"))
                        if k is None or k <= 0:
                            tele["rejected_zero_strike_count"] += 1
                            continue
                        bid, ask, mark = safe_float(c.get("bid")), safe_float(c.get("ask")), safe_float(c.get("mark"))
                        if mark is not None and mark < 0:
                            tele["rejected_negative_mark_count"] += 1
                            continue
                        if (bid is not None and bid < 0) or (ask is not None and ask < 0):
                            tele["rejected_negative_price_count"] += 1
                            continue
                        records.append({
                            "putCallIndicator": c.get("putCallIndicator", default_ind),
                            "daysToExpiration": dte if dte is not None else c.get("daysToExpiration"),
                            "strikePrice": k,
                            "bid": bid, "ask": ask, "mark": mark,
                            "totalVolume": safe_float(c.get("totalVolume")),
                            "openInterest": safe_float(c.get("openInterest")),
                            "volatility": safe_float(c.get("volatility")),
                            "delta": safe_float(c.get("delta")),
                            "gamma": safe_float(c.get("gamma")),
                            "theta": safe_float(c.get("theta")),
                            "vega": safe_float(c.get("vega")),
                            "inTheMoney": c.get("inTheMoney")
                        })
        parse_map(raw_chain.get("callExpDateMap", {}), "CALL")
        parse_map(raw_chain.get("putExpDateMap", {}), "PUT")
        return vol_30d, u_price, records, tele
    except Exception:
        return None, None, [], {"rejected_zero_strike_count": 0, "rejected_expired_contract_count": 0, "rejected_negative_mark_count": 0, "rejected_negative_price_count": 0}