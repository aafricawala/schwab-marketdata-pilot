# src/schwab_marketdata_calculator.py
from __future__ import annotations
import math
from typing import Any, Dict, Optional
import numpy as np
import pandas as pd


def safe_float(v: Any) -> Optional[float]:
  if v is None or pd.isna(v):
    return None
  try:
    f = float(str(v).replace('$', '').replace(',', '').strip())
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


class MasterThesisCalculator:

  def __init__(
      self,
      raw_data: Dict[str, Any],
      price_history_df: pd.DataFrame,
      options_df: pd.DataFrame,
      params: Dict[str, Any],
  ):
    self.raw = raw_data
    self.ph_df = (
        price_history_df
        if isinstance(price_history_df, pd.DataFrame)
        else pd.DataFrame()
    )
    self.opt_df = (
        options_df if isinstance(options_df, pd.DataFrame) else pd.DataFrame()
    )
    self.params = params or {}
    self.spot = safe_float(
        self.raw.get('phase_0_grounding', {}).get('lastPrice')
    )
    self.close = safe_float(
        self.raw.get('phase_0_grounding', {}).get('closePrice')
    )
    self.is_open = bool(
        self.raw.get('phase_0_grounding', {}).get('market_isOpen', False)
    )
    self.quote_age = safe_float(
        self.raw.get('phase_0_grounding', {}).get('quote_age_seconds')
    )
    self.fund = self.raw.get('step_1_fundamentals', {})
    self.deriv = self.raw.get('step_3_and_7_derivatives', {})
    u_p = safe_float(
        self.deriv.get('surface_parameters', {}).get('underlyingPrice')
    )
    if u_p is not None:
      self.calc_spot = u_p
      self.spot_source = 'options_payload_underlyingPrice'
      self.spot_vintage = 'LOW'
    else:
      self.calc_spot = self.spot
      self.spot_source = 'phase_0_grounding_last_price'
      self.spot_vintage = 'MEDIUM'

  def calculate_metrics(self) -> Dict[str, Any]:
    return {
        'step_0_grounding': self._calc_step_0(),
        'step_1_fundamentals_and_quality': self._calc_step_1(),
        'step_3_and_7_derivatives_and_surface': self._calc_step_3_7(),
        'step_5_technicals_and_flows': self._calc_step_5(),
    }

  def _calc_step_0(self) -> Dict[str, Any]:
    gap = (
        safe_div((self.spot - self.close) * 100.0, self.close)
        if self.spot and self.close
        else None
    )
    if self.is_open and self.quote_age is not None and self.quote_age > 3600.0:
      st = 'STALE_QUOTE'
    else:
      st = 'CALCULATED' if gap is not None else 'UNKNOWN'
    return {
        'session_gap_pct': round(gap, 4) if gap is not None else None,
        'state': st,
        'session_gap_anchor': 'PRIOR_SESSION_CLOSE_QUOTE',
    }

  def _calc_step_1(self) -> Dict[str, Any]:
    pe = safe_float(self.fund.get('peRatio'))
    eps = safe_float(self.fund.get('eps'))
    div_amt = safe_float(self.fund.get('divAmount'))
    div_y = safe_float(self.fund.get('divYield'))
    shares = safe_float(self.fund.get('sharesOutstanding'))
    mcap = safe_float(self.fund.get('marketCap'))
    eps_state = str(self.fund.get('eps_state') or '')
    pe_state = str(self.fund.get('peRatio_state') or '')
    shares_state = str(self.fund.get('shares_outstanding_state') or '')

    is_halted = (
        shares_state == 'UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED'
        or eps_state == 'VENDOR_UNAVAILABLE_ASSET_HALTED'
        or pe_state == 'VENDOR_UNAVAILABLE_ASSET_HALTED'
    )
    is_etn = not is_halted and (
        shares_state == 'UNAVAILABLE_FOR_ETN_OR_FUND'
        or eps_state == 'VENDOR_UNAVAILABLE_ETF_OR_ETN_NO_EPS'
        or pe_state == 'NOT_APPLICABLE_ETF_OR_FUND'
    )

    derived_mcap = (
        round(self.calc_spot * shares, 2) if self.calc_spot and shares else None
    )
    mcap_note = None
    if shares_state == 'VENDOR_PROVIDED_FOREIGN_ISSUER_UNVERIFIED':
      mcap_note = 'DERIVED_FROM_UNVERIFIED_FOREIGN_FLOAT'
    elif shares_state == 'UNAVAILABLE_FOR_FOREIGN_ADR':
      mcap_note = 'ADR_DEPOSITARY_SHARES_UNAVAILABLE'

    if derived_mcap is not None and mcap is not None:
      div_abs = abs(derived_mcap - mcap)
      div_pct = round(safe_div(div_abs * 100.0, mcap) or 0.0, 4)
      mcap_div = {
          'derived_market_cap': derived_mcap,
          'reported_market_cap': mcap,
          'market_cap_divergence_abs_usd': div_abs,
          'market_cap_divergence_pct': div_pct,
          'market_cap_divergence_state': (
              'CALCULATED'
              if div_pct <= 5.0
              else 'INTEGRITY_FAILURE_REQUIRES_REVIEW'
          ),
          'market_cap_divergence_reason': (
              'within_5pct_reconciliation_band'
              if div_pct <= 5.0
              else 'divergence_exceeds_5pct_threshold'
          ),
      }
    elif derived_mcap is not None:
      mcap_div = {
          'derived_market_cap': derived_mcap,
          'reported_market_cap': None,
          'market_cap_divergence_abs_usd': None,
          'market_cap_divergence_pct': None,
          'market_cap_divergence_state': 'DERIVED_ONLY_VENDOR_ABSENT',
          'market_cap_divergence_reason': 'vendor_does_not_provide_market_cap',
      }
    else:
      if is_halted:
        div_rsn = 'asset_halted_or_unquoted_quote_unavailable'
      elif is_etn:
        div_rsn = 'vendor_does_not_provide_shares_for_etn_or_fund'
      else:
        div_rsn = 'requires_verified_shares_outstanding'
      mcap_div = {
          'derived_market_cap': None,
          'reported_market_cap': mcap,
          'market_cap_divergence_abs_usd': None,
          'market_cap_divergence_pct': None,
          'market_cap_divergence_state': 'UNVERIFIED_COMPONENTS',
          'market_cap_divergence_reason': div_rsn,
      }
    if mcap_note:
      mcap_div['market_cap_basis_note'] = mcap_note
    calc: Dict[str, Any] = {'market_cap_divergence': mcap_div}

    spot_near_zero = self.calc_spot is not None and self.calc_spot <= 0.01
    eps_non_pos = eps is None or eps <= 0.0 or abs(eps) < 0.01

    near_zero_pe_stub = pe is not None and 0.0 < pe <= 0.05
    class_mismatch_eps = bool(
        self.calc_spot and eps and eps > self.calc_spot * 2.0
    )

    if is_halted:
      calc['earnings_yield_state'] = 'N/A'
      calc['earnings_yield_reason'] = (
          'asset_halted_or_unquoted_quote_unavailable'
      )
    elif is_etn:
      calc['earnings_yield_state'] = 'N/A'
      calc['earnings_yield_reason'] = (
          'earnings_negative_or_unstable_pe_ratio_non_positive'
      )
    elif spot_near_zero:
      calc['earnings_yield_state'] = 'N/A'
      calc['earnings_yield_reason'] = (
          'spot_price_near_zero_or_negative_earnings'
      )
    elif pe and pe > 0:
      if eps_non_pos:
        calc['earnings_yield_state'] = 'N/A'
        if eps is not None and eps < 0.0:
          calc['earnings_yield_reason'] = (
              'pe_ratio_positive_while_trailing_eps_negative_unreconciled'
          )
        elif eps is not None and 0.0 < eps < 0.01:
          calc['earnings_yield_reason'] = (
              'pe_ratio_unsupported_by_sub_cent_reported_eps'
          )
        else:
          calc['earnings_yield_reason'] = (
              'pe_ratio_unsupported_by_non_positive_reported_eps'
          )
      elif near_zero_pe_stub or class_mismatch_eps:
        calc['earnings_yield_state'] = 'N/A'
        calc['earnings_yield_reason'] = (
            'pe_ratio_structurally_inconsistent_with_trailing_eps'
        )
      elif self.calc_spot and (
          (pe * eps / self.calc_spot > 100.0)
          or (self.calc_spot / (pe * eps) > 100.0)
      ):
        calc['earnings_yield_state'] = 'N/A'
        calc['earnings_yield_reason'] = (
            'pe_ratio_structurally_inconsistent_with_trailing_eps'
        )
      else:
        calc['earnings_yield_pct'] = round(safe_div(100.0, pe) or 0.0, 4)
        calc['earnings_yield_state'] = 'CALCULATED'
    elif eps and eps >= 0.01 and self.calc_spot:
      calc['earnings_yield_pct'] = round(
          safe_div(eps * 100.0, self.calc_spot) or 0.0, 4
      )
      calc['earnings_yield_state'] = 'CALCULATED'
    else:
      calc['earnings_yield_state'] = 'N/A'
      calc['earnings_yield_reason'] = (
          'spot_price_near_zero_or_negative_earnings'
          if (spot_near_zero or (eps is not None and eps <= 0.0))
          else 'earnings_negative_or_unstable_pe_ratio_non_positive'
      )

    has_sub_cent_eps = eps is not None and abs(eps) < 0.01
    imp_pe = (
        safe_div(self.calc_spot, eps)
        if (
            not is_etn
            and not is_halted
            and self.calc_spot
            and eps
            and eps > 0
            and not has_sub_cent_eps
        )
        else None
    )

    if is_halted:
      calc['pe_eps_vintage_disparity'] = None
      calc['pe_eps_disparity_state'] = 'NOT_APPLICABLE_ASSET_HALTED'
    elif is_etn or pe_state == 'NOT_APPLICABLE_ETF_OR_FUND':
      calc['pe_eps_vintage_disparity'] = None
      calc['pe_eps_disparity_state'] = 'NOT_APPLICABLE_ETF_OR_FUND'
    elif not is_etn and pe and pe < 0 and imp_pe and imp_pe > 0:
      calc['pe_eps_vintage_disparity'] = True
      calc['pe_eps_disparity_state'] = 'NEGATIVE_REPORTED_PE_POSITIVE_EPS'
      calc['implied_trailing_pe'] = round(imp_pe, 2)
      calc['pe_basis_note'] = (
          'reported_pe_reflects_negative_forward_consensus_vs_positive_trailing_eps'
      )
    elif not is_etn and pe and pe > 0 and imp_pe and imp_pe > 0:
      disp_pct = round(abs(pe - imp_pe) / imp_pe * 100.0, 2)
      has_disp = disp_pct > 10.0
      disp_state = (
          'SEVERE_VINTAGE_DISPARITY'
          if disp_pct > 100.0
          else ('VINTAGE_DISPARITY' if has_disp else 'WITHIN_TOLERANCE')
      )
      calc['pe_eps_vintage_disparity'] = has_disp
      calc['pe_eps_disparity_state'] = disp_state
      calc['implied_trailing_pe'] = round(imp_pe, 2)
      calc['pe_eps_disparity_pct'] = disp_pct
      if disp_pct > 100.0:
        calc['pe_basis_note'] = 'SEVERE_DISPARITY_CAUSE_UNVERIFIED'
      elif has_disp:
        calc['pe_basis_note'] = (
            'reported_pe_reflects_forward_consensus_vs_trailing_eps'
        )
    else:
      calc['pe_eps_vintage_disparity'] = None
      calc['pe_eps_disparity_state'] = 'NOT_APPLICABLE'

    is_non_payer = div_y == 0.0 or div_amt == 0.0
    if is_halted:
      calc['dividend_payout_ratio_state'] = 'NOT_APPLICABLE_ASSET_HALTED'
      calc['dividend_payout_ratio_reason'] = (
          'asset_halted_or_unquoted_quote_unavailable'
      )
      calc['dividend_payout_ratio_health'] = 'NOT_APPLICABLE'
    elif is_non_payer:
      calc['dividend_payout_ratio_state'] = 'NOT_APPLICABLE_NON_PAYER'
      calc['dividend_payout_ratio_reason'] = 'non_payer_no_distribution'
      calc['dividend_payout_ratio_health'] = 'NOT_APPLICABLE'
    elif is_etn:
      calc['dividend_payout_ratio_state'] = 'NOT_APPLICABLE_ETF_OR_FUND'
      calc['dividend_payout_ratio_reason'] = 'etn_fund_no_corporate_eps'
      calc['dividend_payout_ratio_health'] = 'CAPITAL_STRUCTURE_UNVERIFIED'
    elif eps_state == 'VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED':
      calc['dividend_payout_ratio_state'] = 'NOT_APPLICABLE_FOREIGN_ADR'
      calc['dividend_payout_ratio_reason'] = 'eps_suppressed_for_foreign_adr'
      calc['dividend_payout_ratio_health'] = 'CAPITAL_STRUCTURE_UNVERIFIED'
    elif eps is not None and eps >= 0.01:
      payout = safe_div(div_amt * 100.0, eps)
      calc['imputed_dividend_payout_ratio_pct'] = (
          round(payout, 2) if payout is not None else None
      )
      calc['dividend_payout_ratio_state'] = 'CALCULATED'
      if payout is not None and payout > 100.0:
        calc['dividend_payout_ratio_health'] = 'UNSUSTAINABLE_COVERAGE_DEFICIT'
        calc['payout_exceeds_earnings'] = True
        calc['dividend_deficit_pct'] = round(payout - 100.0, 2)
      elif payout is not None and payout > 75.0:
        calc['dividend_payout_ratio_health'] = 'ELEVATED'
        calc['payout_exceeds_earnings'] = False
      else:
        calc['dividend_payout_ratio_health'] = 'SUSTAINABLE'
        calc['payout_exceeds_earnings'] = False
    else:
      calc['dividend_payout_ratio_state'] = 'UNKNOWN'
      if eps == 0.0:
        calc['dividend_payout_ratio_reason'] = 'eps_zero_denominator_hazard'
      elif eps is not None and abs(eps) < 0.01:
        calc['dividend_payout_ratio_reason'] = 'eps_sub_cent_denominator_hazard'
      elif eps is not None and eps < 0.0:
        calc['dividend_payout_ratio_reason'] = 'negative_eps_unsupported_payout'
      else:
        calc['dividend_payout_ratio_reason'] = 'missing_dividend_or_eps_data'
      calc['dividend_payout_ratio_health'] = 'UNSUSTAINABLE_OR_DISTORTED'

    if is_halted:
      calc['state'] = 'PARTIAL'
      calc['coverage_unknown'] = True
      calc['full_capital_coverage_unknown'] = True
      calc['distribution_coverage_unknown'] = True
      calc['share_count_coverage_unknown'] = True
      calc['coverage_unknown_reason'] = (
          'asset_halted_or_unquoted_quote_unavailable'
      )
    elif is_etn:
      calc['state'] = 'PARTIAL'
      calc['coverage_unknown'] = (
          True
          if (eps is None and shares is None)
          else (True if (div_y and div_y > 0 and eps is None) else False)
      )
      calc['full_capital_coverage_unknown'] = calc['coverage_unknown']
      calc['distribution_coverage_unknown'] = True
      calc['share_count_coverage_unknown'] = True
      if calc['coverage_unknown']:
        calc['coverage_unknown_reason'] = 'etn_or_fund_no_earnings_or_shares'
      if div_y and div_y > 10.0 and self.calc_spot:
        c_y = safe_div(div_amt * 100.0, self.calc_spot)
        if c_y:
          calc['div_yield_vendor_vs_computed_delta_pct'] = round(
              abs(div_y - c_y), 2
          )
          calc['divYield_basis_verified'] = 'ANNUAL_VENDOR_CONFIRMED'
    else:
      has_calc = any(
          calc.get(k) is not None
          for k in ['earnings_yield_pct', 'imputed_dividend_payout_ratio_pct']
      )
      calc['state'] = 'CALCULATED' if has_calc else 'PARTIAL'
      if is_non_payer:
        calc['distribution_coverage_unknown'] = False
        calc['share_count_coverage_unknown'] = False
        calc['coverage_unknown'] = False
        calc['full_capital_coverage_unknown'] = False
        calc['coverage_note'] = 'not_applicable_non_payer_no_distribution'
      else:
        calc['distribution_coverage_unknown'] = eps is None or eps <= 0.0
        calc['share_count_coverage_unknown'] = shares is None
        calc['full_capital_coverage_unknown'] = eps is None or shares is None
        calc['coverage_unknown'] = calc['full_capital_coverage_unknown']
        if eps is None and shares is None:
          calc['coverage_unknown_reason'] = (
              'dividend_payer_missing_eps_and_shares'
          )
        elif eps is None:
          calc['coverage_unknown_reason'] = 'dividend_payer_missing_eps'
        elif shares is None:
          calc['coverage_unknown_reason'] = 'dividend_payer_missing_shares'
      if eps_state == 'VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED':
        calc['distribution_coverage_unknown_reason'] = (
            'adr_eps_suppressed_no_coverage_assessment'
        )
      if pe and pe > 0 and (
          eps is None or eps_state == 'VENDOR_UNAVAILABLE_FOREIGN_ADR_SUPPRESSED'
      ):
        calc['earnings_yield_basis_note'] = (
            'derived_solely_from_vendor_pe_ratio_eps_unavailable'
        )
    return calc

  def _calc_step_3_7(self) -> Dict[str, Any]:
    spot_prov = {
        'source': self.spot_source,
        'vintage_risk': self.spot_vintage,
        'observed_price': self.calc_spot,
    }
    cmi_block = self._calc_cmi_30d(self.opt_df)
    if self.opt_df.empty:
      return {
          'spot_provenance': spot_prov,
          'state': 'UNKNOWN',
          'reason': 'options_chain_empty_or_unavailable',
          'skew_30d': {
              'state': 'UNKNOWN',
              'reason': 'options_chain_empty_or_unavailable',
              'skew_delta_anchor': 'REJECTED_BEFORE_SELECTION',
              'skew_regime': 'UNKNOWN',
          },
          'flow_ratios': {
              'put_call_volume_ratio': None,
              'put_call_open_interest_ratio': None,
              'volume_regime': 'NO_OPTIONS_VOLUME',
              'state': 'UNKNOWN',
              'reason': 'options_chain_empty_or_unavailable',
          },
      }
    df = self.opt_df.copy()
    puts = df[df['putCallIndicator'] == 'PUT']
    calls = df[df['putCallIndicator'] == 'CALL']
    p_vol, c_vol = puts['totalVolume'].sum(), calls['totalVolume'].sum()
    p_oi, c_oi = puts['openInterest'].sum(), calls['openInterest'].sum()
    vr = safe_div(p_vol, c_vol)
    oir = safe_div(p_oi, c_oi)

    tot_vol = (p_vol or 0.0) + (c_vol or 0.0)
    if vr is None:
      regime = 'NO_OPTIONS_VOLUME'
    elif vr < 0.50:
      regime = 'HEAVY_CALL_FLOW'
    elif vr > 2.00:
      regime = 'HEAVY_PUT_FLOW'
    else:
      regime = 'NEUTRAL'

    flow_state = 'CALCULATED' if c_vol > 0 and c_oi > 0 else 'UNKNOWN'
    flow: Dict[str, Any] = {
        'put_call_volume_ratio': round(vr, 4) if vr is not None else None,
        'put_call_open_interest_ratio': round(oir, 4) if oir is not None else None,
        'volume_regime': regime,
        'state': flow_state,
    }
    if flow_state == 'UNKNOWN' and tot_vol == 0.0:
      flow['reason'] = 'options_chain_has_zero_contract_volume'

    if p_vol == 0.0 and c_vol > 0.0:
      flow['flow_ratios_note'] = 'ZERO_PUT_VOLUME_OBSERVED'
    if p_oi == 0.0 and c_oi > 0.0:
      flow['flow_oi_note'] = 'ZERO_PUT_OPEN_INTEREST_OBSERVED'

    skew_block = self._calc_skew_30d(df, cmi_block)
    atm_block = self._calc_atm_straddle(df)
    return {
        'spot_provenance': spot_prov,
        'flow_ratios': flow,
        'constant_maturity_30d_iv': cmi_block,
        'skew_30d': skew_block,
        'atm_event_straddle': atm_block,
    }

  def _calc_cmi_30d(self, df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
      return {
          'state': 'UNKNOWN',
          'reason': 'options_chain_empty_or_unavailable',
      }
    dtes = sorted(
        list({int(d) for d in df['daysToExpiration'].dropna() if int(d) >= 0})
    )
    if not dtes:
      return {'state': 'UNKNOWN', 'reason': 'no_valid_expirations'}
    t1_cand = [d for d in dtes if d <= 30]
    t2_cand = [d for d in dtes if d >= 30]
    t1 = t1_cand[-1] if t1_cand else dtes[0]
    t2 = t2_cand[0] if t2_cand else dtes[-1]
    span = abs(t2 - t1)
    quality = (
        'DEGENERATE_SINGLE_EXPIRATION'
        if span == 0
        else ('TIGHT' if span <= 10 else 'WIDE')
    )

    def get_mean_iv(dte_val: int) -> Optional[float]:
      sub = df[df['daysToExpiration'] == dte_val]
      if sub.empty:
        return None
      sub = sub.assign(d_diff=(sub['strikePrice'] - self.calc_spot).abs())
      atm_k = sub.loc[sub['d_diff'].idxmin(), 'strikePrice']
      vols = sub[sub['strikePrice'] == atm_k]['volatility'].dropna()
      return float(vols.mean()) if not vols.empty else None

    iv1, iv2 = get_mean_iv(t1), get_mean_iv(t2)
    if iv1 is None or iv2 is None or iv1 <= 0.0 or iv2 <= 0.0:
      return {
          'constant_maturity_30d_iv': None,
          'state': 'UNKNOWN',
          'reason': 'invalid_iv_sentinel_detected',
          't1_dte': t1,
          't2_dte': t2,
          'bracket_span_days': span,
          'bracket_quality': quality,
      }

    if t1 == t2:
      iv30 = iv1
    else:
      w1, w2 = abs(t2 - 30) / float(span or 1), abs(30 - t1) / float(span or 1)
      iv30 = (iv1 * w1) + (iv2 * w2)
    return {
        'constant_maturity_30d_iv': round(iv30, 4),
        'state': 'CALCULATED',
        't1_dte': t1,
        't2_dte': t2,
        'bracket_span_days': span,
        'bracket_quality': quality,
    }

  def _calc_skew_30d(
      self, df: pd.DataFrame, cmi_block: Dict[str, Any]
  ) -> Dict[str, Any]:
    b_span = cmi_block.get('bracket_span_days')
    b_qual = cmi_block.get('bracket_quality')
    dtes = sorted(
        list({int(d) for d in df['daysToExpiration'].dropna() if int(d) >= 0})
    )
    if not dtes:
      ret = {
          'state': 'UNKNOWN',
          'reason': 'no_valid_dte_for_skew',
          'skew_delta_anchor': 'REJECTED_BEFORE_SELECTION',
          'skew_regime': 'UNKNOWN',
      }
      if b_span is not None:
        ret['bracket_span_days'] = b_span
      if b_qual:
        ret['bracket_quality'] = b_qual
      return ret
    t_dte = min(dtes, key=lambda d: abs(d - 30))
    sub = df[df['daysToExpiration'] == t_dte]
    puts = sub[sub['putCallIndicator'] == 'PUT'].assign(
        d_diff=(sub['delta'].abs() - 0.25).abs()
    )
    calls = sub[sub['putCallIndicator'] == 'CALL'].assign(
        d_diff=(sub['delta'].abs() - 0.25).abs()
    )
    if puts.empty or calls.empty:
      ret = {
          'skew_tenor_dte': t_dte,
          'state': 'UNKNOWN',
          'reason': 'missing_wing_delta_contracts',
          'skew_delta_anchor': 'REJECTED_BEFORE_SELECTION',
          'skew_regime': 'UNKNOWN',
      }
      if b_span is not None:
        ret['bracket_span_days'] = b_span
      if b_qual:
        ret['bracket_quality'] = b_qual
      return ret
    p_row = puts.loc[puts['d_diff'].idxmin()]
    c_row = calls.loc[calls['d_diff'].idxmin()]
    p_bid, p_ask, p_iv = (
        safe_float(p_row.get('bid')),
        safe_float(p_row.get('ask')),
        safe_float(p_row.get('volatility')),
    )
    c_bid, c_ask, c_iv = (
        safe_float(c_row.get('bid')),
        safe_float(c_row.get('ask')),
        safe_float(c_row.get('volatility')),
    )
    p_mid = safe_float(p_row.get('mark')) or (
        safe_div(p_bid + p_ask, 2)
        if p_bid is not None and p_ask is not None
        else None
    )
    c_mid = safe_float(c_row.get('mark')) or (
        safe_div(c_bid + c_ask, 2)
        if c_bid is not None and c_ask is not None
        else None
    )
    p_spr = (
        2.0
        if (p_bid == 0.0 and p_ask and p_ask > 0)
        else (
            safe_div(abs(p_ask - p_bid), p_mid)
            if p_ask is not None and p_bid is not None and p_mid
            else None
        )
    )
    c_spr = (
        2.0
        if (c_bid == 0.0 and c_ask and c_ask > 0)
        else (
            safe_div(abs(c_ask - c_bid), c_mid)
            if c_ask is not None and c_bid is not None and c_mid
            else None
        )
    )
    max_spr = self.params.get('MAX_SKEW_RELATIVE_SPREAD', 0.50)
    p_fail = p_spr is not None and p_spr > max_spr
    c_fail = c_spr is not None and c_spr > max_spr
    if p_fail or c_fail or p_spr is None or c_spr is None:
      rej_wing = (
          'BOTH' if (p_fail and c_fail) else ('PUT' if p_fail else 'CALL')
      )
      rej_dict = {
          'skew_tenor_dte': t_dte,
          'skew_delta_anchor': 'REJECTED_AT_WING_SPREAD_GATE',
          'skew_regime': 'UNKNOWN',
          'spread_tolerance_source': 'DEFAULT_EXECUTION_BOUNDARY',
          'state': 'UNKNOWN',
          'reason': 'skew_wings_exceed_spread_tolerance',
          'observed_put_relative_spread': (
              round(p_spr, 4) if p_spr is not None else None
          ),
          'observed_call_relative_spread': (
              round(c_spr, 4) if c_spr is not None else None
          ),
          'spread_zero_bid_flag': p_bid == 0.0 or c_bid == 0.0,
          'rejected_wing': rej_wing,
          'cmi_bracket_ref': 'constant_maturity_30d_iv',
      }
      if b_span is not None:
        rej_dict['bracket_span_days'] = b_span
      if b_qual:
        rej_dict['bracket_quality'] = b_qual
      return rej_dict
    diff = p_iv - c_iv if p_iv and c_iv else None
    p_d, c_d = safe_float(p_row.get('delta')), safe_float(c_row.get('delta'))
    p_abs = abs(p_d) if p_d else 0.0
    c_abs = abs(c_d) if c_d else 0.0
    sym_gap = round(abs(p_abs - c_abs), 3)
    p_in_band = 0.20 <= p_abs <= 0.30
    c_in_band = 0.20 <= c_abs <= 0.30
    is_primary = p_in_band and c_in_band and (sym_gap <= 0.05)
    anchor_label = (
        'PRIMARY_25D_SYMMETRIC' if is_primary else 'FALLBACK_NEAREST_SYMMETRIC'
    )
    s_regime = (
        'REVERSE_CALL_SKEW'
        if (diff is not None and diff > 0)
        else 'STANDARD_PUT_SKEW'
    )
    ret = {
        'skew_tenor_dte': t_dte,
        'skew_delta_anchor': anchor_label,
        'skew_30d_iv_differential': round(diff, 3) if diff is not None else None,
        'skew_regime': s_regime,
        'skew_delta_symmetry_gap': sym_gap,
        'skew_actual_put_delta': round(p_d, 3) if p_d is not None else None,
        'skew_actual_call_delta': round(c_d, 3) if c_d is not None else None,
        'spread_tolerance_source': 'DEFAULT_EXECUTION_BOUNDARY',
        'state': 'CALCULATED',
    }
    if b_span is not None:
      ret['bracket_span_days'] = b_span
    if b_qual:
      ret['bracket_quality'] = b_qual
    if not is_primary:
      ret['skew_anchor_reason'] = (
          'PRIMARY_BAND_VIOLATED'
          if not (p_in_band and c_in_band)
          else 'SYMMETRY_GAP_EXCEEDED'
      )
    return ret

  def _calc_atm_straddle(self, df: pd.DataFrame) -> Dict[str, Any]:
    dtes = sorted(
        list({int(d) for d in df['daysToExpiration'].dropna() if int(d) >= 0})
    )
    if not dtes:
      return {'state': 'UNKNOWN', 'reason': 'no_valid_expirations'}
    f_dte = dtes[0]
    sub = df[df['daysToExpiration'] == f_dte].assign(
        d_diff=(df['strikePrice'] - self.calc_spot).abs()
    )
    atm_k = sub.loc[sub['d_diff'].idxmin(), 'strikePrice']
    p_mark = (
        safe_float(
            sub[
                (sub['strikePrice'] == atm_k)
                & (sub['putCallIndicator'] == 'PUT')
            ]['mark'].iloc[0]
        )
        if not sub[
            (sub['strikePrice'] == atm_k) & (sub['putCallIndicator'] == 'PUT')
        ].empty
        else None
    )
    c_mark = (
        safe_float(
            sub[
                (sub['strikePrice'] == atm_k)
                & (sub['putCallIndicator'] == 'CALL')
            ]['mark'].iloc[0]
        )
        if not sub[
            (sub['strikePrice'] == atm_k) & (sub['putCallIndicator'] == 'CALL')
        ].empty
        else None
    )
    if p_mark is not None and c_mark is not None and self.calc_spot:
      cost = p_mark + c_mark
      move_pct = safe_div(cost * 0.85 * 100.0, self.calc_spot)
      return {
          'front_expiry_dte': f_dte,
          'atm_strike': float(atm_k),
          'combined_straddle_cost': round(cost, 2),
          'expected_move_pct': round(move_pct, 4) if move_pct else None,
          'factor_basis': 'PRACTITIONER_FAT_TAIL_ADJUSTED_CONVENTION',
          'state': 'CALCULATED',
      }
    return {'state': 'UNKNOWN', 'reason': 'insufficient_atm_quote_data'}

  def _calc_step_5(self) -> Dict[str, Any]:
    pivots = {'state': 'UNKNOWN', 'reason': 'insufficient_ohlc_bars'}
    rv = {'state': 'UNKNOWN', 'reason': 'insufficient_ohlc_bars'}
    if not self.ph_df.empty:
      clean_bars = self.ph_df.dropna(
          subset=['open', 'high', 'low', 'close']
      ).sort_values('datetime')
      if not clean_bars.empty:
        last_bar = clean_bars.iloc[-1]
        h, l, c = (
            safe_float(last_bar['high']),
            safe_float(last_bar['low']),
            safe_float(last_bar['close']),
        )
        if (
            h is not None
            and l is not None
            and c is not None
            and h > 0
            and l > 0
            and c > 0
        ):
          p = (h + l + c) / 3.0
          if p >= 0.005:
            pivots = {
                'Pivot': round(p, 2),
                'R1': round((2 * p) - l, 2),
                'R2': round(p + (h - l), 2),
                'R3': round(p + 2 * (h - l), 2),
                'S1': round((2 * p) - h, 2),
                'S2': round(p - (h - l), 2),
                'S3': round(p - 2 * (h - l), 2),
                'state': 'CALCULATED',
            }
          else:
            pivots = {'state': 'UNKNOWN', 'reason': 'candle_prices_non_positive'}
        else:
          pivots = {'state': 'UNKNOWN', 'reason': 'candle_prices_non_positive'}

        if (clean_bars['close'] <= 0.01).any() or (
            clean_bars['low'] <= 0.01
        ).any():
          rv = {
              'state': 'UNKNOWN',
              'reason': (
                  'sub_cent_zero_price_bars_unsuitable_for_diffusion_estimators'
              ),
          }
        else:
          rv = self._calc_realized_vol_suite(clean_bars)
    return {'classical_floor_pivots': pivots, 'realized_volatility': rv}

  def _calc_realized_vol_suite(self, df: pd.DataFrame) -> Dict[str, Any]:
    n = len(df)
    if n < 2:
      return {'state': 'UNKNOWN', 'reason': 'insufficient_bars_for_returns'}
    res: Dict[str, Any] = {'state': 'CALCULATED'}
    res['10d_tactical'] = self._calc_rv_horizon(df.tail(11), 10, min_bars=8)
    res['30d_intermediate'] = self._calc_rv_horizon(
        df.tail(31), 30, min_bars=20
    )
    res['252d_macro'] = self._calc_rv_horizon(
        df.tail(253), 252, min_bars=180, check_seasoning=True, total_avail=n
    )
    return res

  def _calc_rv_horizon(
      self,
      df: pd.DataFrame,
      target_win: int,
      min_bars: int,
      check_seasoning: bool = False,
      total_avail: int = 0,
  ) -> Dict[str, Any]:
    n_bars = len(df)
    n_rets = max(0, n_bars - 1)
    c2c_vol = None
    if n_rets >= 2:
      log_ret = np.log(df['close'] / df['close'].shift(1)).dropna()
      c2c_vol = (
          float(log_ret.std(ddof=1) * np.sqrt(252) * 100.0)
          if len(log_ret) > 1
          else None
      )
    if n_bars < min_bars:
      ret_dict = {
          'state': 'INSUFFICIENT_HISTORY',
          'target_window_bars': target_win,
          'actual_sample_bars': n_bars,
          'return_observations': n_rets,
          'reason': f'sample_bars_below_minimum_{min_bars}',
      }
      if c2c_vol is not None:
        ret_dict['computed_realized_vol'] = round(c2c_vol, 2)
      if check_seasoning:
        ret_dict['listing_seasoning'] = (
            'ESTABLISHED_LISTING'
            if total_avail >= 250
            else 'UNSEASONED_LISTING'
        )
        ret_dict['total_available_bars'] = total_avail
      return ret_dict
    hl = np.log(df['high'] / df['low'])
    co = np.log(df['close'] / df['open'])
    park = float(
        np.sqrt((1.0 / (4.0 * np.log(2.0))) * (hl**2).mean())
        * np.sqrt(252)
        * 100.0
    )
    gk = float(
        np.sqrt(
            (0.5 * (hl**2) - ((2.0 * np.log(2.0) - 1.0) * (co**2))).mean()
        )
        * np.sqrt(252)
        * 100.0
    )
    disp = abs((c2c_vol or gk) - gk)
    if target_win == 252 and n_bars < 252:
      st = 'PARTIAL_HISTORY'
    else:
      st = 'FULL_HISTORY'
    ret = {
        'status': st,
        'actual_sample_bars': n_bars,
        'return_observations': n_rets,
        'close_to_close': round(c2c_vol, 4) if c2c_vol else None,
        'parkinson': round(park, 4),
        'garman_klass': round(gk, 4),
        'estimator_dispersion_pp': round(disp, 4),
        'estimator_methodology': 'Garman-Klass (1980) zero-drift invariant',
    }
    if disp > 40.0:
      ret['estimator_dispersion_regime'] = 'EXTREME_DISPERSION'
    if check_seasoning:
      ret['listing_seasoning'] = (
          'ESTABLISHED_LISTING' if total_avail >= 250 else 'UNSEASONED_LISTING'
      )
      ret['total_available_bars'] = total_avail
      if st == 'PARTIAL_HISTORY':
        ret['sample_bars_note'] = (
            'lookback_satisfies_minimum_threshold_below_target'
        )
    return ret