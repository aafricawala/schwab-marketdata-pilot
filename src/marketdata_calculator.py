# ==============================================================================
# MODULE: marketdata_calculator.py
# Core Mathematical Modeling & JSON Sanitization Engine for Master Thesis v16.20
# ==============================================================================
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("MasterThesisEngine")

# Explicit set of field names representing dollar/currency amounts
CURRENCY_KEYS = {
    "lastPrice", "closePrice", "bidPrice", "askPrice", "divAmount",
    "cfo_per_share", "imputed_book_value_of_equity", "imputed_total_debt",
    "R3", "R2", "R1", "Pivot", "S1", "S2", "S3", "strikePrice", "mark", "bid", "ask"
}
def safe_div(num: Any, den: Any) -> Optional[float]:
    """Divides two numbers safely without raising ZeroDivisionError or TypeError."""
    try:
        if num is None or den is None or pd.isna(num) or pd.isna(den):
            return None
        n, d = float(num), float(den)
        return n / d if d != 0.0 else None
    except (ValueError, TypeError):
        return None

def clean_for_json(obj: Any, key_name: Optional[str] = None) -> Any:
    """
    Recursively transforms data structures into JSON-compliant primitives:
    - Formats currency keys with '$' and 2 decimal places.
    - Rounds all other floating-point metrics to 2 decimal places.
    - Strips out nulls, NaNs, infinities, and empty structures.
    """
    if isinstance(obj, pd.DataFrame):
        sanitized_df = obj.where(pd.notnull(obj), None)
        cleaned_list = [clean_for_json(row) for row in sanitized_df.to_dict(orient="records")]
        return [item for item in cleaned_list if item not in (None, {}, [])]

    if isinstance(obj, pd.Series):
        sanitized_s = obj.where(pd.notnull(obj), None)
        return clean_for_json(sanitized_s.to_dict())

    if isinstance(obj, dict):
        cleaned_dict = {}
        for k, v in obj.items():
            cleaned_v = clean_for_json(v, key_name=str(k))
            if cleaned_v is not None and cleaned_v != {} and cleaned_v != []:
                cleaned_dict[str(k)] = cleaned_v
        return cleaned_dict

    if isinstance(obj, (list, tuple, set)):
        cleaned_list = [clean_for_json(item) for item in obj]
        return [item for item in cleaned_list if item is not None and item != {} and item != []]

    if isinstance(obj, (datetime, date, pd.Timestamp)):
        return obj.isoformat()

    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        if key_name in CURRENCY_KEYS:
            return f"${obj:.2f}"
        return round(obj, 2)

    if isinstance(obj, int) and not isinstance(obj, bool):
        if key_name in CURRENCY_KEYS:
            return f"${float(obj):.2f}"
        return obj

    if pd.isna(obj):
        return None

    return obj

def export_compact_json(data: Dict[str, Any], filepath: str | Path) -> Tuple[Path, Dict[str, Any]]:
    """Exports cleaned dictionary to minified JSON on disk and returns the cleaned object."""
    path = Path(filepath)
    cleaned_data = clean_for_json(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cleaned_data, f, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return path, cleaned_data

class MasterThesisCalculator:
    """Calculates phase-aligned metrics from in-memory market structures."""

    def __init__(
        self,
        raw_data: Dict[str, Any],
        price_history_df: pd.DataFrame,
        options_df: pd.DataFrame,
        params: Dict[str, Any]
    ):
        self.raw = raw_data
        self.params = params
        self.price_history_df = price_history_df
        self.options_df = options_df
        
        self.spot = self.raw.get("phase_0_grounding", {}).get("lastPrice")
        self.fundamentals = self.raw.get("step_1_fundamentals", {})
        self.liquidity = self.raw.get("step_8_and_9_liquidity_and_sizing", {})

    def calculate_metrics(self) -> Dict[str, Any]:
        return {
            "step_0_grounding": self._calc_step_0(),
            "step_1_fundamentals_and_quality": self._calc_step_1(),
            "step_3_and_7_derivatives_and_surface": self._calc_step_3_and_7(),
            "step_5_technicals_and_flows": self._calc_step_5(),
        }

    def _calc_step_0(self) -> Dict[str, Any]:
        calc = {"session_gap_pct": None}
        prev_close = self.raw.get("phase_0_grounding", {}).get("closePrice")
        df = self.price_history_df
        if not df.empty:
            latest = df.iloc[-1]
            if prev_close and pd.notna(latest.get("open")):
                calc["session_gap_pct"] = safe_div((latest["open"] - prev_close), prev_close) * 100
        return calc

    def _calc_step_1(self) -> Dict[str, Any]:
        pe = self.fundamentals.get("peRatio")
        eps = self.fundamentals.get("eps")
        div = self.fundamentals.get("divAmount")
        pcf = self.fundamentals.get("pcfRatio")
        shares_out = self.fundamentals.get("sharesOutstanding")
        pb = self.fundamentals.get("pbRatio")
        dteq = self.fundamentals.get("totalDebtToEquity")

        mcap = (self.spot * shares_out) if (self.spot and shares_out) else None

        return {
            "earnings_yield_pct": safe_div(1, pe) * 100 if pe else safe_div(eps, self.spot) * 100 if (eps and self.spot) else None,
            "imputed_dividend_payout_ratio_pct": safe_div(div, eps) * 100 if div and eps else None,
            "cfo_per_share": safe_div(self.spot, pcf) if pcf and self.spot else None,
            "cfo_yield_pct": safe_div(1, pcf) * 100 if pcf else None,
            "imputed_book_value_of_equity": safe_div(mcap, pb) if mcap and pb else None,
            "imputed_total_debt": (safe_div(mcap, pb) * (dteq / 100)) if (mcap and pb and dteq) else None
        }

    def _calc_step_3_and_7(self) -> Dict[str, Any]:
        calc = {
            "skew_tenor_dte": None,
            "skew_30d_iv_differential": None,
            "skew_30d_normalized_ratio": None,
            "put_call_volume_ratio": None,
            "put_call_open_interest_ratio": None,
            "realized_volatility_lookback_days": None,
            "realized_volatility_lookback_years": None,
            "realized_volatility_close_to_close": None,
            "realized_volatility_parkinson": None,
            "realized_volatility_garman_klass": None,
            "event_tenor_dte": None,
            "event_implied_move_pct": None,
        }

        df = self.price_history_df
        if not df.empty and len(df) > 1:
            try:
                calc["realized_volatility_lookback_days"] = len(df)
                calc["realized_volatility_lookback_years"] = self.params.get("HISTORICAL_PERIOD", 1)
                log_rets = np.log(df["close"] / df["close"].shift(1)).dropna()
                calc["realized_volatility_close_to_close"] = float(np.sqrt(252) * log_rets.std() * 100)
                
                hl_log = np.log(df["high"] / df["low"])
                parkinson_var = (1 / (4 * np.log(2))) * (hl_log ** 2).mean()
                calc["realized_volatility_parkinson"] = float(np.sqrt(252 * parkinson_var) * 100)
                
                co_log = np.log(df["close"] / df["open"])
                gk_var = (0.5 * (hl_log ** 2)) - ((2 * np.log(2) - 1) * (co_log ** 2))
                calc["realized_volatility_garman_klass"] = float(np.sqrt(252 * gk_var.mean()) * 100)
            except Exception as e:
                logger.warning(f"RV Calculation error: {e}")

        opt = self.options_df
        if not opt.empty:
            puts = opt[opt["putCallIndicator"] == "PUT"]
            calls = opt[opt["putCallIndicator"] == "CALL"]
            calc["put_call_volume_ratio"] = safe_div(puts["totalVolume"].sum(), calls["totalVolume"].sum())
            calc["put_call_open_interest_ratio"] = safe_div(puts["openInterest"].sum(), calls["openInterest"].sum())

            # 30D ~25Δ Skew Resolution
            opt["dte_diff"] = (opt["daysToExpiration"] - 30).abs()
            target_dte = opt["dte_diff"].min()
            chain_30d = opt[opt["dte_diff"] == target_dte]
            if not chain_30d.empty:
                try:
                    calc["skew_tenor_dte"] = int(chain_30d.iloc[0]["daysToExpiration"])
                    chain_30d = chain_30d.assign(delta_abs=chain_30d["delta"].astype(float).abs())
                    put_25d = chain_30d[chain_30d["putCallIndicator"] == "PUT"].iloc[
                        (chain_30d[chain_30d["putCallIndicator"] == "PUT"]["delta_abs"] - 0.25).abs().argmin()
                    ]
                    call_25d = chain_30d[chain_30d["putCallIndicator"] == "CALL"].iloc[
                        (chain_30d[chain_30d["putCallIndicator"] == "CALL"]["delta_abs"] - 0.25).abs().argmin()
                    ]
                    iv_p, iv_c = float(put_25d["volatility"]), float(call_25d["volatility"])
                    calc["skew_30d_iv_differential"] = iv_p - iv_c
                    calc["skew_30d_normalized_ratio"] = safe_div(iv_p, iv_c)
                except Exception:
                    pass

            # Front-Month ATM Straddle Implied Move
            if self.spot:
                try:
                    front_dte = opt["daysToExpiration"].min()
                    front_chain = opt[opt["daysToExpiration"] == front_dte].copy()
                    calc["event_tenor_dte"] = int(front_dte)
                    front_chain["strike_diff"] = (front_chain["strikePrice"].astype(float) - self.spot).abs()
                    atm_strike = front_chain.loc[front_chain["strike_diff"].idxmin(), "strikePrice"]
                    
                    atm_put = front_chain[(front_chain["strikePrice"] == atm_strike) & (front_chain["putCallIndicator"] == "PUT")].iloc[0]
                    atm_call = front_chain[(front_chain["strikePrice"] == atm_strike) & (front_chain["putCallIndicator"] == "CALL")].iloc[0]
                    straddle_cost = float(atm_put["mark"] + atm_call["mark"])
                    calc["event_implied_move_pct"] = safe_div(straddle_cost, self.spot) * 100
                except Exception:
                    pass

        return calc

    def _calc_step_5(self) -> Dict[str, Any]:
        calc = {"classical_floor_pivots": None}
        df = self.price_history_df
        if not df.empty:
            latest = df.iloc[-1]
            H, L, C = latest["high"], latest["low"], latest["close"]
            if all(pd.notna(x) for x in [H, L, C]):
                P = (H + L + C) / 3
                calc["classical_floor_pivots"] = {
                    "R3": float(H + 2 * (P - L)),
                    "R2": float(P + (H - L)),
                    "R1": float((2 * P) - L),
                    "Pivot": float(P),
                    "S1": float((2 * P) - H),
                    "S2": float(P - (H - L)),
                    "S3": float(L - 2 * (H - P)),
                }
        return calc