# src/schwab_raw_marketdata.py
from __future__ import annotations
import math
import re
from datetime import datetime, timezone
from pathlib import Path
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


def extract_strict_underlying_data(
    client: Any, symbol: str, tz_et: ZoneInfo
) -> Dict[str, Any]:
    r = client.get_quote(symbol)
    res_dict = _parse_client_response(r)
    if res_dict is None:
        raise ValueError(f"Failed to fetch valid quote response for {symbol}")

    clean_sym = symbol.strip().upper()
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

    ref = data.get("reference", {})
    quote = data.get("quote", {})
    fund = data.get("fundamental", {})
    asset_sub = str(ref.get("assetSubType", "") or "").upper()
    asset_main = str(ref.get("assetMainType", "") or "").upper()
    desc = str(ref.get("description", "") or "").upper()

    # Structural Pooled Vehicle Classification (Defensive Regex + Vendor Attributes, Zero Hardcoded Symbols)
    is_fund_type = (
        asset_sub in ["ETF", "ETN", "MUTUAL_FUND", "CEF", "UIT", "OPEN_END_FUND", "CLOSED_END_FUND"]
        or asset_main in ["ETF", "ETN", "MUTUAL_FUND", "FUND", "COLLECTIVE_INVESTMENT"]
    )
    desc_pooled_match = bool(
        re.search(
            r"\b(ETF|ETN|FUND|TRUST|INDEX|PORTFOLIO|SHARES|NOTE|ETRACS|HOLDINGS|COMMODITY|CURRENCY|GOLD|SILVER|AGRICULTURE|BULL|BEAR|2X|3X)\b",
            desc,
        )
    )
    raw_shares = safe_float(fund.get("sharesOutstanding"))
    is_structural_wrapper = is_fund_type or (desc_pooled_match and (raw_shares is None or raw_shares == 0.0 or is_fund_type))

    last_p = safe_float(quote.get("lastPrice"))
    close_p = safe_float(quote.get("closePrice"))
    q_time_raw = quote.get("quoteTime", 0)
    if q_time_raw:
        q_time_iso = (
            datetime.fromtimestamp(q_time_raw / 1000.0, tz=timezone.utc)
            .astimezone(tz_et)
            .isoformat()
        )
        q_age = round(
            (datetime.now(timezone.utc).timestamp() - (q_time_raw / 1000.0)), 2
        )
    else:
        q_time_iso = None
        q_age = None

    is_halted_or_unquoted = (last_p is None and close_p is None)

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

    is_foreign_adr = (
        bool(re.search(r"\bADR\b", desc))
        or asset_sub == "ADR"
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
    elif is_structural_wrapper:
        shares_val = None
        shares_state = "UNAVAILABLE_FOR_ETN_OR_FUND"
    elif last_p == 0.0 or close_p == 0.0:
        shares_state = "CONFIRMED"
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
    elif is_structural_wrapper:
        pe_val, pe_state = None, "NOT_APPLICABLE_ETF_OR_FUND"
        eps_val, eps_state = None, "VENDOR_UNAVAILABLE_ETF_OR_ETN_NO_EPS"
    elif last_p == 0.0 or close_p == 0.0:
        pe_val, pe_state = raw_pe, "AS_REPORTED"
        eps_val, eps_state = raw_eps, "AS_REPORTED"
    else:
        pe_val = raw_pe
        pe_state = "AS_REPORTED" if raw_pe is not None else "VENDOR_UNAVAILABLE"
        if is_foreign_adr and raw_eps is None:
            eps_val, eps_state = None, "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED"
        else:
            eps_val = raw_eps
            eps_state = "AS_REPORTED" if raw_eps is not None else "VENDOR_UNAVAILABLE"

    is_zero_div = raw_div_y == 0.0 or raw_div_amt == 0.0 or raw_div_y is None
    div_y_basis = (
        "AS_REPORTED_ZERO_NON_PAYER"
        if is_zero_div and not is_halted_or_unquoted
        else (
            "ANNUAL_VENDOR_CONFIRMED"
            if raw_div_y is not None and raw_div_y > 0.0
            else "VENDOR_UNAVAILABLE"
        )
    )

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
            margin_suspect, margin_reason, margin_state = True, "vendor_net_and_operating_margins_identical", "SUSPECT_VENDOR_DATA"
        else:
            margin_suspect, margin_reason, margin_state = False, "margins_structurally_differentiated", "CONFIRMED"
    else:
        margin_suspect, margin_reason, margin_state = None, None, "VENDOR_UNAVAILABLE_INPUTS_ABSENT"

    short_stat = ref.get("shortLocate", quote.get("shortLocate", {}))
    is_shortable = ref.get("isShortable") if ref.get("isShortable") is not None else quote.get("isShortable", short_stat.get("isShortable"))
    is_htb = ref.get("isHardToBorrow") if ref.get("isHardToBorrow") is not None else quote.get("isHardToBorrow", short_stat.get("isHardToBorrow"))
    raw_htb_rate = safe_float(ref.get("htbRate", quote.get("htbRate", short_stat.get("rate"))))

    if is_shortable is None and is_htb is None and raw_htb_rate is None:
        short_dict: Dict[str, Any] = {"state": "UNKNOWN", "reason": "locate_data_not_reported_by_venue_or_tier"}
    else:
        htb_rate_val = raw_htb_rate
        raw_htb_store = None
        if not is_htb:
            htb_status = "NOT_APPLICABLE_ETB"
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
            "state": "FULL_PASSTHROUGH" if all(v is not None for v in [is_shortable, is_htb]) else "PARTIAL_PASSTHROUGH",
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

    if is_halted_or_unquoted:
        liq_state, book_reason, book_note = "UNVERIFIED_EMPTY_ORDER_BOOK", "asset_halted_or_unquoted", "EMPTY_ORDER_BOOK_ASSET_HALTED"
    elif bid_s == 0.0 and ask_s == 0.0:
        liq_state = "UNVERIFIED_EMPTY_ORDER_BOOK"
        if tot_vol is not None and tot_vol > 0.0:
            book_reason, book_note = "zero_bid_ask_depth_with_reported_volume", "ZERO_BID_ASK_DEPTH_REPORTED"
        else:
            book_reason, book_note = "zero_book_activity_recorded", "EMPTY_ORDER_BOOK_NO_VOLUME"

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
        "vol10DayAvg_state": "AS_REPORTED" if fund.get("vol10DayAvg") is not None else "VENDOR_UNAVAILABLE",
        "vol3MonthAvg_state": "VENDOR_FIELD_NOT_PROVIDED",
        "vol1YearAvg": safe_float(fund.get("vol1YearAvg")),
        "vol1YearAvg_state": (
            "VENDOR_SUSPECT_ZERO" if fund.get("vol1YearAvg") == 0.0
            else ("AS_REPORTED" if fund.get("vol1YearAvg") is not None else "VENDOR_UNAVAILABLE")
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
        "marketCap_unit": "VENDOR_RAW_UNVERIFIED",
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
            "quote_age_classification": q_class,
        },
        "step_1_fundamentals": fund_dict,
        "short_locate_status": short_dict,
        "step_8_and_9_liquidity_and_sizing": liq_dict,
    }


def extract_in_memory_price_history(
    client: Any, symbol: str, config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    clean_sym = symbol.strip().upper()
    p_type = config.get("HISTORICAL_PERIOD_TYPE", "year")
    p_val = config.get("HISTORICAL_PERIOD", 1)
    f_type = config.get("HISTORICAL_FREQUENCY_TYPE", "daily")
    f_val = config.get("HISTORICAL_FREQUENCY", 1)
    ext_hrs = config.get("HISTORICAL_NEED_EXTENDED_HOURS", False)

    attempts = [
        {},
        {
            "period_type": p_type,
            "period": p_val,
            "frequency_type": f_type,
            "frequency": f_val,
            "need_extended_hours_data": ext_hrs,
        },
        {
            "period_type": str(p_type).upper(),
            "period": p_val,
            "frequency_type": str(f_type).upper(),
            "frequency": f_val,
            "need_extended_hours_data": ext_hrs,
        },
    ]

    for kwargs in attempts:
        try:
            r = client.get_price_history(clean_sym, **kwargs)
            d = _parse_client_response(r)
            if d:
                candles = d.get("candles", []) or []
                valid_candles = [
                    c
                    for c in candles
                    if safe_float(c.get("close")) is not None
                    and safe_float(c.get("open")) is not None
                ]
                if valid_candles:
                    return valid_candles
        except Exception:
            continue
    return []


def extract_in_memory_option_expirations(
    client: Any, symbol: str
) -> List[Dict[str, Any]]:
    clean_sym = symbol.strip().upper()
    methods = ["get_option_expirations", "get_option_expiration_chain"]
    for m in methods:
        if hasattr(client, m):
            try:
                fn = getattr(client, m)
                r = fn(clean_sym)
                d = _parse_client_response(r)
                if d:
                    return d.get("expirationList", []) or []
            except Exception:
                continue
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
    telemetry = {
        "rejected_zero_strike_count": 0,
        "rejected_expired_contract_count": 0,
        "rejected_negative_mark_count": 0,
        "rejected_negative_price_count": 0,
    }

    clean_sym = symbol.strip().upper()
    all_contracts: List[Dict[str, Any]] = []
    underlying_price = None
    vol_30d = None

    def _parse_chain_payload(payload: Dict[str, Any]) -> None:
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
                        all_contracts.append(contract_item)

    if target_expirations:
        for exp in target_expirations:
            exp_date_raw = exp.get("expirationDate")
            if not exp_date_raw:
                continue

            date_obj = None
            try:
                date_obj = datetime.strptime(str(exp_date_raw)[:10], "%Y-%m-%d").date()
            except Exception:
                pass

            call_attempts = []
            if date_obj is not None:
                call_attempts.append({
                    "strike_count": strike_window,
                    "from_date": date_obj,
                    "to_date": date_obj,
                    "strategy": strategy,
                })
            call_attempts.append({
                "strike_count": strike_window,
                "from_date": exp_date_raw,
                "to_date": exp_date_raw,
                "strategy": strategy,
            })

            payload = None
            for kwargs in call_attempts:
                try:
                    r = client.get_option_chain(clean_sym, **kwargs)
                    parsed = _parse_client_response(r)
                    if parsed and ("callExpDateMap" in parsed or "putExpDateMap" in parsed):
                        payload = parsed
                        break
                except Exception:
                    continue

            if payload:
                _parse_chain_payload(payload)

    if not all_contracts:
        try:
            r = client.get_option_chain(clean_sym)
            parsed = _parse_client_response(r)
            if parsed and ("callExpDateMap" in parsed or "putExpDateMap" in parsed):
                _parse_chain_payload(parsed)
        except Exception:
            pass

    return vol_30d, underlying_price, all_contracts, telemetry