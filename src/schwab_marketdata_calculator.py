# src/schwab_marketdata_calculator.py
from __future__ import annotations
import logging, math, re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import numpy as np, pandas as pd

logger = logging.getLogger("schwab_marketdata_calculator")
logger.addHandler(logging.NullHandler())

def _safe_float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool): return None
    if isinstance(v, (int, float, np.number)): return None if (math.isnan(float(v)) or math.isinf(float(v))) else float(v)
    if isinstance(v, str):
        c = re.sub(r"[$,% ]", "", v.strip())
        if not c or c.lower() in ("nan", "none", "null"): return None
        try:
            f = float(c)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except (ValueError, TypeError): return None
    return None

def _safe_div(n: Any, d: Any) -> Optional[float]:
    num, den = _safe_float(n), _safe_float(d)
    return None if (num is None or den is None or den == 0.0) else num / den

class MasterThesisCalculator:
    def __init__(self, raw_data: Optional[Dict[str, Any]] = None, price_history: Optional[Union[pd.DataFrame, List[Dict[str, Any]]]] = None, options_data: Optional[Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]] = None, params: Optional[Dict[str, Any]] = None) -> None:
        self.raw = raw_data if isinstance(raw_data, dict) else {}
        self.params = params if isinstance(params, dict) else {}
        self.price_history_df = price_history.copy() if isinstance(price_history, pd.DataFrame) else (pd.DataFrame(price_history) if isinstance(price_history, list) and price_history else pd.DataFrame())
        self.options_df = options_data.copy() if isinstance(options_data, pd.DataFrame) else (self._flatten_options_chain_dict(options_data) if isinstance(options_data, dict) else (pd.DataFrame(options_data) if isinstance(options_data, list) and options_data else pd.DataFrame()))
        raw_spot = None
        d = self.raw.get("step_3_and_7_derivatives")
        if isinstance(d, dict) and isinstance(d.get("surface_parameters"), dict): raw_spot = d["surface_parameters"].get("underlyingPrice")
        g = self.raw.get("phase_0_grounding")
        g_last = g.get("lastPrice") if isinstance(g, dict) else None
        g_close = g.get("closePrice") if isinstance(g, dict) else None
        if raw_spot is not None and _safe_float(raw_spot) is not None:
            self.spot = _safe_float(raw_spot)
            self.spot_provenance = {"source": "options_payload_underlyingPrice", "vintage_risk": "LOW", "observed_price": self.spot}
        elif g_last is not None and _safe_float(g_last) is not None:
            self.spot = _safe_float(g_last)
            self.spot_provenance = {"source": "phase_0_grounding_last_price", "vintage_risk": "MEDIUM", "observed_price": self.spot}
        elif g_close is not None and _safe_float(g_close) is not None:
            self.spot = _safe_float(g_close)
            self.spot_provenance = {"source": "phase_0_grounding_close_price", "vintage_risk": "MEDIUM", "observed_price": self.spot}
        else:
            self.spot = None
            self.spot_provenance = {"source": "UNRESOLVED", "vintage_risk": "UNKNOWN", "observed_price": None}
        self.prior_close = _safe_float(g_close)
        rf = self.raw.get("step_1_fundamentals")
        self.fundamentals = rf if isinstance(rf, dict) else {}
        rl = self.raw.get("step_8_and_9_liquidity_and_sizing")
        self.liquidity = rl if isinstance(rl, dict) else {}
        self.trading_days_per_year = _safe_float(self.params.get("TRADING_DAYS_PER_YEAR")) or 252.0
        self.max_skew_relative_spread = _safe_float(self.params.get("MAX_SKEW_RELATIVE_SPREAD")) or 0.50
        self.max_30d_dte_tolerance = int(self.params.get("MAX_30D_DTE_TOLERANCE", 7))

    def _flatten_options_chain_dict(self, options_chain: Dict[str, Any]) -> pd.DataFrame:
        records = []
        u = options_chain.get("underlying", {})
        u_p = _safe_float(options_chain.get("underlyingPrice") or (u.get("last") if isinstance(u, dict) else None) or (u.get("close") if isinstance(u, dict) else None))
        for m_k, ind in (("callExpDateMap", "CALL"), ("putExpDateMap", "PUT")):
            e_map = options_chain.get(m_k, {})
            if not isinstance(e_map, dict): continue
            for e_k, strikes in e_map.items():
                try: dte = int(e_k.split(":")[1])
                except (IndexError, ValueError): dte = None
                if not isinstance(strikes, dict): continue
                for s_str, c_list in strikes.items():
                    strike = _safe_float(s_str)
                    if strike is None or strike <= 0.0 or not isinstance(c_list, list): continue
                    for c in c_list:
                        if not isinstance(c, dict): continue
                        records.append({
                            "putCallIndicator": c.get("putCallIndicator", ind), "daysToExpiration": c.get("daysToExpiration", dte),
                            "strikePrice": strike, "bid": _safe_float(c.get("bid")), "ask": _safe_float(c.get("ask")),
                            "mark": _safe_float(c.get("mark")), "totalVolume": _safe_float(c.get("totalVolume")) or 0.0,
                            "openInterest": _safe_float(c.get("openInterest")) or 0.0, "volatility": _safe_float(c.get("volatility")),
                            "delta": _safe_float(c.get("delta")), "underlyingPrice": u_p,
                        })
        return pd.DataFrame(records)

    def calculate_metrics(self) -> Dict[str, Any]: return self._execute_suite()
    def calculate_all(self) -> Dict[str, Any]: return self._execute_suite()

    def _execute_suite(self) -> Dict[str, Any]:
        return {
            "step_0_grounding": self._calc_session_gap(),
            "step_1_fundamentals_and_quality": self._calc_step_1_fundamentals_and_divergence(),
            "step_3_and_7_derivatives_and_surface": self._calc_derivatives_surface(),
            "step_5_technicals_and_flows": self._calc_technicals_and_flows(),
        }

    def _calc_session_gap(self) -> Dict[str, Any]:
        if self.spot is None or self.prior_close is None or self.prior_close <= 0.0:
            return {"session_gap_pct": None, "state": "UNKNOWN", "reason": "missing_spot_or_prior_close"}
        return {"session_gap_pct": round(((self.spot - self.prior_close) / self.prior_close) * 100.0, 4), "state": "CALCULATED", "session_gap_anchor": "PRIOR_SESSION_CLOSE_QUOTE"}

    def _calc_step_1_fundamentals_and_divergence(self) -> Dict[str, Any]:
        f = self.fundamentals
        shares, rep_mcap = _safe_float(f.get("sharesOutstanding")), _safe_float(f.get("marketCap"))
        pe, eps = _safe_float(f.get("peRatio")), _safe_float(f.get("eps"))
        div_amt = _safe_float(f.get("divAmount"))
        div_y_raw = _safe_float(f.get("divYield_raw")) or _safe_float(f.get("divYield"))
        pb, pcf, dteq = _safe_float(f.get("pbRatio")), _safe_float(f.get("pcfRatio")), _safe_float(f.get("totalDebtToEquity"))
        div_y_basis = str(f.get("divYield_basis", "AS_REPORTED")).strip()
        sh_state, eps_state = str(f.get("shares_outstanding_state", "")).strip(), str(f.get("eps_state", "")).strip()

        divergence = {"derived_market_cap": None, "reported_market_cap": rep_mcap, "market_cap_divergence_abs_usd": None, "market_cap_divergence_pct": None, "market_cap_divergence_state": "UNVERIFIED_COMPONENTS", "market_cap_divergence_reason": None}
        der_mcap = self.spot * shares if (self.spot is not None and shares is not None and shares > 0.0) else None
        if der_mcap is not None: divergence["derived_market_cap"] = der_mcap

        if sh_state == "UNAVAILABLE_FOR_ETN_OR_FUND":
            divergence["market_cap_divergence_state"], divergence["market_cap_divergence_reason"] = "UNVERIFIED_COMPONENTS", "vendor_does_not_provide_shares_for_etn_or_fund"
        elif shares is None or "UNAVAILABLE" in sh_state:
            divergence["market_cap_divergence_state"], divergence["market_cap_divergence_reason"] = "UNVERIFIED_COMPONENTS", ("requires_verified_shares_outstanding" if ("FOREIGN" in sh_state or "UNAVAILABLE" in sh_state) else "derived_market_cap_unavailable")
        elif rep_mcap is None or rep_mcap <= 0.0:
            divergence["market_cap_divergence_state"], divergence["market_cap_divergence_reason"] = "DERIVED_ONLY_VENDOR_ABSENT", "vendor_does_not_provide_market_cap"
        elif der_mcap is None:
            divergence["market_cap_divergence_state"], divergence["market_cap_divergence_reason"] = "UNVERIFIED_COMPONENTS", "derived_market_cap_unavailable"
        else:
            diff_abs = abs(der_mcap - rep_mcap)
            diff_pct = (diff_abs / rep_mcap) * 100.0
            divergence["market_cap_divergence_abs_usd"], divergence["market_cap_divergence_pct"] = diff_abs, round(diff_pct, 4)
            if diff_pct <= 0.50: divergence["market_cap_divergence_state"] = "ALIGNED"
            elif diff_pct <= 5.0: divergence["market_cap_divergence_state"] = "FLOAT_OR_CLASS_DIFFERENTIAL"
            elif diff_pct > 20.0 and diff_abs > 50_000_000_000.0: divergence["market_cap_divergence_state"] = "INTEGRITY_FAILURE_REQUIRES_REVIEW"
            elif diff_abs > 5_000_000_000.0: divergence["market_cap_divergence_state"] = "SCHEMA_OR_CLASS_SUSPECTED"
            else: divergence["market_cap_divergence_state"] = "DIVERGENT_VINTAGE_OR_SCHEMA"

        pe_eps_disp, imp_pe, disp_pct, disp_state, pe_note = False, None, None, None, None
        if pe is not None and pe > 0.0 and eps is not None and eps > 0.0 and self.spot is not None:
            imp_pe = round(self.spot / eps, 2)
            disp_pct = round(abs(pe - imp_pe) / imp_pe * 100.0, 2)
            if disp_pct > 10.0:
                pe_eps_disp = True
                if disp_pct > 100.0:
                    disp_state = "SEVERE_VINTAGE_DISPARITY"
                    pe_note = "SEVERE_DISPARITY_CAUSE_UNVERIFIED"
                else:
                    disp_state = "VINTAGE_DISPARITY"
                    pe_note = "reported_pe_reflects_forward_consensus_vs_trailing_eps"
            else:
                disp_state = "WITHIN_TOLERANCE"

        payout, p_state, p_reason, p_health = None, "UNKNOWN", None, "N/A"
        is_fund = (sh_state == "UNAVAILABLE_FOR_ETN_OR_FUND" or eps_state == "VENDOR_UNAVAILABLE_ETF_OR_ETN_NO_EPS")
        d_cov_unk, s_cov_unk, cov_unk, cov_unk_r = False, False, False, None

        if is_fund:
            if div_y_raw is not None and div_y_raw > 0.0: cov_unk, cov_unk_r = True, "etn_or_fund_no_earnings_or_shares"
        else:
            d_cov_unk = (eps is None) and (div_y_raw is not None and div_y_raw > 0.0)
            s_cov_unk = (shares is None) and (div_y_raw is not None and div_y_raw > 0.0)

        if div_y_basis == "AS_REPORTED_ZERO_NON_PAYER" or div_amt == 0.0:
            p_state, p_reason, p_health = "NOT_APPLICABLE_NON_PAYER", "non_payer_no_distribution", "NOT_APPLICABLE"
        elif is_fund:
            p_state, p_reason, p_health = "N/A", "etn_fund_no_corporate_eps", "CAPITAL_STRUCTURE_UNVERIFIED"
        elif eps_state == "VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED":
            p_state, p_reason, p_health = "N/A", "eps_suppressed_for_foreign_adr", "CAPITAL_STRUCTURE_UNVERIFIED"
        elif div_amt is not None and eps is not None:
            if eps == 0.0: p_state, p_reason = "N/A", "eps_zero_denominator_hazard"
            elif abs(eps) < 0.01: p_state, p_reason = "N/A", "eps_sub_cent_denominator_hazard"
            elif eps < 0.0: p_state, p_reason = "N/A", "eps_negative_unstable_for_payout"
            else:
                freq = _safe_float(f.get("divFreq")) or 4.0
                ann_div = div_amt if div_y_basis == "ANNUAL_VENDOR_CONFIRMED" else (div_amt * freq)
                c_pr = (ann_div / eps) * 100.0
                if c_pr > 1000.0: p_state, p_reason = "N/A", "payout_ratio_economically_implausible"
                else:
                    payout, p_state = round(c_pr, 2), "CALCULATED"
                    p_health = "CAPITAL_IMPAIRMENT_RISK" if c_pr > 100.0 else "SUSTAINABLE"
        else: p_reason = "missing_dividend_or_eps_data"

        div_y_delta = None
        if div_y_raw is not None and div_y_raw > 15.0 and self.spot is not None and self.spot > 0.0 and div_amt is not None:
            c_yd = (div_amt / self.spot) * 100.0
            div_y_delta = round(abs(div_y_raw - c_yd), 2)
            if div_y_delta > max(0.05 * div_y_raw, (0.01 / self.spot) * 100.0) and div_y_basis == "ANNUAL_VENDOR_CONFIRMED":
                div_y_basis = "ANNUAL_VENDOR_ASSERTED_UNVERIFIED"

        ey, ey_st, ey_r, ey_note = None, "CALCULATED", None, None
        if pe is not None and pe > 0.0:
            ey = round((1.0 / pe) * 100.0, 4)
            if eps is None: ey_note = "derived_solely_from_vendor_pe_ratio_eps_unavailable"
        elif eps is not None and eps > 0.0 and self.spot is not None and self.spot > 0.0:
            ey = round((eps / self.spot) * 100.0, 4)
        else: ey_st, ey_r = "N/A", "earnings_negative_or_unstable_pe_ratio_non_positive"

        b_cnt = sum(1 for m in [ey, payout, der_mcap] if m is not None)
        cfo_y = round((1.0 / pcf) * 100.0, 4) if (pcf is not None and pcf > 0.0) else None
        act_mcap = der_mcap or rep_mcap
        imp_bv = round(act_mcap / pb, 2) if (act_mcap is not None and pb is not None and pb > 0.0) else None
        imp_d = None
        d_unit = str(self.params.get("TOTAL_DEBT_TO_EQUITY_UNIT", "PERCENTAGE")).strip().upper()
        if imp_bv is not None and dteq is not None:
            imp_d = round(imp_bv * (dteq / 100.0), 2) if d_unit in ("PERCENTAGE", "PCT") else round(imp_bv * dteq, 2)

        res = {
            "market_cap_divergence": divergence, "earnings_yield_pct": ey, "earnings_yield_state": ey_st, "earnings_yield_reason": ey_r,
            "pe_eps_vintage_disparity": pe_eps_disp, "pe_eps_disparity_state": disp_state, "implied_trailing_pe": imp_pe,
            "pe_eps_disparity_pct": disp_pct, "pe_basis_note": pe_note, "imputed_dividend_payout_ratio_pct": payout,
            "dividend_payout_ratio_state": p_state, "dividend_payout_ratio_reason": p_reason, "dividend_payout_ratio_health": p_health,
            "cfo_yield_pct": cfo_y, "imputed_book_value_of_equity": imp_bv, "imputed_total_debt": imp_d,
            "state": "CALCULATED" if b_cnt > 0 else "PARTIAL",
        }
        if is_fund:
            res["coverage_unknown"] = cov_unk
            if cov_unk_r: res["coverage_unknown_reason"] = cov_unk_r
        else:
            res["distribution_coverage_unknown"], res["share_count_coverage_unknown"] = d_cov_unk, s_cov_unk
        if ey_note: res["earnings_yield_basis_note"] = ey_note
        if div_y_delta is not None:
            res["div_yield_vendor_vs_computed_delta_pct"] = div_y_delta
            res["divYield_basis_verified"] = div_y_basis
        return res

    def _calc_derivatives_surface(self) -> Dict[str, Any]:
        if self.options_df.empty:
            return {
                "spot_provenance": self.spot_provenance, "state": "UNKNOWN", "reason": "options_chain_empty_or_unavailable",
                "skew_30d": {"state": "UNKNOWN", "reason": "options_chain_empty_or_unavailable", "skew_delta_anchor": "REJECTED_BEFORE_SELECTION"},
                "flow_ratios": {"state": "UNKNOWN", "reason": "options_chain_empty_or_unavailable"},
            }
        df = self.options_df.copy()
        for col in ["strikePrice", "daysToExpiration", "bid", "ask", "mark", "volatility", "delta", "totalVolume", "openInterest"]:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce")
        u_spot = self.spot or df["strikePrice"].median()

        flow_res = {"put_call_volume_ratio": None, "put_call_open_interest_ratio": None, "state": "CALCULATED"}
        if {"putCallIndicator", "totalVolume", "openInterest"}.issubset(set(df.columns)):
            puts = df[df["putCallIndicator"].astype(str).str.upper() == "PUT"]
            calls = df[df["putCallIndicator"].astype(str).str.upper() == "CALL"]
            flow_res["put_call_volume_ratio"] = _safe_div(puts["totalVolume"].fillna(0.0).sum(), calls["totalVolume"].fillna(0.0).sum())
            flow_res["put_call_open_interest_ratio"] = _safe_div(puts["openInterest"].fillna(0.0).sum(), calls["openInterest"].fillna(0.0).sum())

        cmi = {"constant_maturity_30d_iv": None, "vendor_raw_chain_volatility_metadata": _safe_float(self.raw.get("step_3_and_7_derivatives", {}).get("surface_parameters", {}).get("volatility_30d_surface")), "state": "UNKNOWN", "reason": None}
        dtes = sorted(df["daysToExpiration"].dropna().unique())
        sub_30, sup_30 = [d for d in dtes if 4 <= d <= 30], [d for d in dtes if d >= 30]
        span, bracket_q = None, None
        if sub_30 and sup_30:
            t1, t2 = max(sub_30), min(sup_30)
            span = int(t2 - t1)
            bracket_q = "TIGHT" if span <= 10 else "WIDE"
            cmi["t1_dte"], cmi["t2_dte"], cmi["bracket_span_days"], cmi["bracket_quality"] = int(t1), int(t2), span, bracket_q
            if t1 == t2:
                s_atm = df[(df["daysToExpiration"] == t1) & (df["strikePrice"] == df["strikePrice"].iloc[(df["strikePrice"] - u_spot).abs().argmin()])]
                iv_v = s_atm["volatility"].dropna().mean()
                if not math.isnan(iv_v): cmi["constant_maturity_30d_iv"], cmi["state"] = round(iv_v, 4), "CALCULATED"
            else:
                s1_atm = df[df["daysToExpiration"] == t1].iloc[(df[df["daysToExpiration"] == t1]["strikePrice"] - u_spot).abs().argmin()]
                s2_atm = df[df["daysToExpiration"] == t2].iloc[(df[df["daysToExpiration"] == t2]["strikePrice"] - u_spot).abs().argmin()]
                iv1, iv2 = s1_atm.get("volatility"), s2_atm.get("volatility")
                if iv1 and iv2 and not math.isnan(iv1) and not math.isnan(iv2):
                    v1, v2 = (iv1 ** 2) * (t1 / 365.0), (iv2 ** 2) * (t2 / 365.0)
                    v30 = v1 + (30.0 / 365.0 - t1 / 365.0) * ((v2 - v1) / (t2 / 365.0 - t1 / 365.0))
                    if v30 > 0: cmi["constant_maturity_30d_iv"], cmi["state"] = round(math.sqrt(v30 / (30.0 / 365.0)), 4), "CALCULATED"
        else: cmi["reason"] = "cannot_bracket_30d_tenor_for_cmi_interpolation"

        skew = {"skew_tenor_dte": None, "skew_delta_anchor": "REJECTED_BEFORE_SELECTION", "skew_30d_iv_differential": None, "skew_delta_symmetry_gap": None, "skew_actual_put_delta": None, "skew_actual_call_delta": None, "spread_tolerance_source": "DEFAULT_EXECUTION_BOUNDARY", "state": "UNKNOWN", "reason": None}
        v_dtes = [d for d in dtes if d >= 4]
        if v_dtes:
            t_dte = min(v_dtes, key=lambda d: abs(d - 30))
            eff_tol = 10 if len(v_dtes) <= 4 else self.max_30d_dte_tolerance
            if abs(t_dte - 30) <= eff_tol:
                ch30 = df[df["daysToExpiration"] == t_dte].copy()
                puts = ch30[(ch30["putCallIndicator"] == "PUT") & (ch30["strikePrice"] <= u_spot)].dropna(subset=["delta", "volatility", "ask", "bid"])
                calls = ch30[(ch30["putCallIndicator"] == "CALL") & (ch30["strikePrice"] >= u_spot)].dropna(subset=["delta", "volatility", "ask", "bid"])
                skew["skew_tenor_dte"] = int(t_dte)
                if not puts.empty and not calls.empty:
                    bp = puts.iloc[(puts["delta"].abs() - 0.25).abs().argmin()]
                    bc = calls.iloc[(calls["delta"].abs() - 0.25).abs().argmin()]
                    p_mid, c_mid = (bp["bid"] + bp["ask"]) / 2.0, (bc["bid"] + bc["ask"]) / 2.0
                    p_sp = (bp["ask"] - bp["bid"]) / (p_mid if p_mid > 0 else 1.0)
                    c_sp = (bc["ask"] - bc["bid"]) / (c_mid if c_mid > 0 else 1.0)
                    p_fail, c_fail = p_sp > self.max_skew_relative_spread, c_sp > self.max_skew_relative_spread
                    if p_fail or c_fail:
                        skew["reason"] = "skew_wings_exceed_spread_tolerance"
                        skew["skew_delta_anchor"] = "REJECTED_AT_WING_SPREAD_GATE"
                        skew["observed_put_relative_spread"], skew["observed_call_relative_spread"] = round(p_sp, 4), round(c_sp, 4)
                        skew["spread_zero_bid_flag"] = (bp["bid"] == 0.0 or bc["bid"] == 0.0)
                        skew["rejected_wing"] = "BOTH" if (p_fail and c_fail) else ("PUT" if p_fail else "CALL")
                        if span is not None: skew["cmi_bracket_ref"] = "constant_maturity_30d_iv"
                    else:
                        pd_val, cd_val = float(bp["delta"]), float(bc["delta"])
                        skew["skew_delta_anchor"] = "PRIMARY_25D_SYMMETRIC"
                        skew["skew_actual_put_delta"], skew["skew_actual_call_delta"] = round(pd_val, 4), round(cd_val, 4)
                        skew["skew_delta_symmetry_gap"] = round(abs(abs(pd_val) - abs(cd_val)), 4)
                        skew["skew_30d_iv_differential"] = round(float(bp["volatility"]) - float(bc["volatility"]), 4)
                        skew["state"] = "CALCULATED"
                else: skew["reason"] = "missing_otm_contracts_around_25_delta"
            else:
                skew["reason"] = f"no_options_chain_near_30d_within_tolerance_{eff_tol}"
                if span is not None: skew["cmi_bracket_ref"] = "constant_maturity_30d_iv"

        strad = {"state": "UNKNOWN", "reason": "no_front_expiry_contracts"}
        f_dtes = [d for d in dtes if d >= 4]
        if f_dtes and u_spot is not None:
            f_dte = min(f_dtes)
            f_ch = df[df["daysToExpiration"] == f_dte]
            atm_s = f_ch.iloc[(f_ch["strikePrice"] - u_spot).abs().argmin()]["strikePrice"]
            atm_c, atm_p = f_ch[(f_ch["strikePrice"] == atm_s) & (f_ch["putCallIndicator"] == "CALL")], f_ch[(f_ch["strikePrice"] == atm_s) & (f_ch["putCallIndicator"] == "PUT")]
            if not atm_c.empty and not atm_p.empty:
                c_c, p_c = (atm_c.iloc[0]["bid"] + atm_c.iloc[0]["ask"]) / 2.0, (atm_p.iloc[0]["bid"] + atm_p.iloc[0]["ask"]) / 2.0
                cost = c_c + p_c
                strad = {"front_expiry_dte": int(f_dte), "atm_strike": float(atm_s), "combined_straddle_cost": round(cost, 2), "expected_move_pct": round((0.85 * cost / u_spot) * 100.0, 4), "factor_basis": "PRACTITIONER_FAT_TAIL_ADJUSTED_CONVENTION", "state": "CALCULATED"}

        return {"spot_provenance": self.spot_provenance, "flow_ratios": flow_res, "constant_maturity_30d_iv": cmi, "skew_30d": skew, "atm_event_straddle": strad}

    def _calc_technicals_and_flows(self) -> Dict[str, Any]:
        piv = {"state": "UNKNOWN", "reason": "insufficient_price_history_for_pivots"}
        if len(self.price_history_df) >= 2:
            pb = self.price_history_df.iloc[-2]
            h, l, c = _safe_float(pb.get("high")), _safe_float(pb.get("low")), _safe_float(pb.get("close"))
            if h is not None and l is not None and c is not None and h >= l:
                p = (h + l + c) / 3.0
                piv = {"Pivot": round(p, 2), "R1": round(2 * p - l, 2), "R2": round(p + (h - l), 2), "R3": round(h + 2 * (p - l), 2), "S1": round(2 * p - h, 2), "S2": round(p - (h - l), 2), "S3": round(l - 2 * (h - p), 2), "state": "CALCULATED"}

        rv = {"state": "UNKNOWN", "reason": "empty_price_history"}
        if len(self.price_history_df) > 1:
            rv = {
                "state": "CALCULATED",
                "10d_tactical": self._calc_rv_horizon(self.price_history_df, 10),
                "30d_intermediate": self._calc_rv_horizon(self.price_history_df, 30),
                "252d_macro": self._calc_rv_horizon(self.price_history_df, 252, 180, is_macro=True),
            }
        return {"classical_floor_pivots": piv, "realized_volatility": rv}

    def _calc_rv_horizon(self, df: pd.DataFrame, window: int, min_bars: int = 4, is_macro: bool = False) -> Dict[str, Any]:
        sdf = df.tail(window + 1).copy()
        if len(sdf) < min_bars:
            return {"state": "INSUFFICIENT_HISTORY", "target_window_bars": window, "actual_sample_bars": len(sdf), "return_observations": max(0, len(sdf) - 1), "reason": f"sample_bars_below_minimum_{min_bars}"}
        for col in ["open", "high", "low", "close"]:
            if col in sdf.columns: sdf[col] = pd.to_numeric(sdf[col], errors="coerce")
        sdf = sdf.dropna(subset=["high", "low", "close"])
        n_clean = len(sdf)
        if n_clean < min_bars:
            return {"state": "INSUFFICIENT_HISTORY", "target_window_bars": window, "actual_sample_bars": n_clean, "return_observations": max(0, n_clean - 1), "reason": f"clean_sample_bars_below_minimum_{min_bars}"}
        l_season = ("UNSEASONED_LISTING" if n_clean < 250 else "ESTABLISHED_LISTING") if is_macro else "ESTABLISHED_LISTING"
        rets = np.log(sdf["close"] / sdf["close"].shift(1)).dropna()
        n_obs = len(rets)
        c2c = float(np.sqrt(self.trading_days_per_year) * rets.std(ddof=1) * 100.0) if n_obs > 1 else None
        hl = np.log(sdf["high"] / sdf["low"])
        park = float(np.sqrt(self.trading_days_per_year * ((1.0 / (4.0 * np.log(2.0))) * (hl ** 2).mean())) * 100.0)
        co = np.log(sdf["close"] / sdf["open"])
        gk = float(np.sqrt(self.trading_days_per_year * max(0.0, ((0.5 * (hl ** 2)) - ((2.0 * np.log(2.0) - 1.0) * (co ** 2))).mean())) * 100.0)
        disp = round(abs(c2c - gk), 4) if c2c is not None else None
        p = {"status": "FULL_HISTORY" if n_clean >= window else "PARTIAL_HISTORY", "actual_sample_bars": n_clean, "return_observations": n_obs, "close_to_close": round(c2c, 4) if c2c is not None else None, "parkinson": round(park, 4), "garman_klass": round(gk, 4), "estimator_dispersion_pp": disp, "estimator_methodology": "Garman-Klass (1980) zero-drift invariant"}
        if is_macro: p["listing_seasoning"], p["total_available_bars"] = l_season, len(df)
        return p