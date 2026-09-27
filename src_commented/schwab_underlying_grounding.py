"""
schwab_underlying_grounding.py

Purpose:
This module acts as an orchestrator for assembling the "grounding" data for a financial asset.
It fetches the raw quote and fundamental data from the Schwab API and structures it into standardized
dictionaries representing Phase 0 (grounding), Step 1 (fundamentals), short locate status,
and liquidity metrics.

Prerequisites:
- Requires standard libraries (`logging`, `datetime`, `typing`, `zoneinfo`).
- Requires `schwab_utils` for validation and safe conversions.
- Requires `schwab_vendor_resilience` for API calling with automatic retries.
- Requires specialized classification and fundamental resolver modules (`schwab_instrument_classification`,
  `schwab_fundamental_resolvers`, `schwab_short_locate`, `schwab_liquidity_book`).

What this module does:
1. Validates the provided ticker symbol.
2. Fetches the latest quote and fundamental data from the vendor API, handling retries automatically.
3. Parses the raw JSON response to extract the specific asset data.
4. Identifies the asset type (e.g., warrant, mutual fund, ADR) by looking at descriptions and subtypes.
5. Determines if the asset is currently halted, unquoted, or if the data is too old.
6. Calls out to dedicated "resolver" functions to clean up specific fields (like shares outstanding, PE ratios, dividends, and margins).
7. Calls out to dedicated modules to resolve short selling availability and liquidity.
8. Assembles and returns a final, highly structured dictionary categorized by pipeline steps.

Configuration knobs:
- API retries: `max_retries=3`, `base_delay=0.2` seconds.
- Quote age thresholds and classification logic are imported from `schwab_instrument_classification`.

Outputs:
- A dictionary containing nested blocks: `phase_0_grounding`, `step_1_fundamentals`,
  `short_locate_status`, and `step_8_and_9_liquidity_and_sizing`.

Notes:
- This file relies heavily on "Batch 2" resolvers to apply business logic and clean the data.
- The original logic remains unchanged; the inline blocks were simply extracted into the resolver modules.
"""
# Enable modern type hinting features.
from __future__ import annotations

# Import the logging library to track events.
import logging
# Import datetime and timezone for handling quote timestamps.
from datetime import datetime, timezone
# Import typing hints for dictionaries and any types.
from typing import Any, Dict
# Import ZoneInfo for timezone handling (e.g., converting to Eastern Time).
from zoneinfo import ZoneInfo

# Import utility functions to safely cast floats and validate ticker symbols.
from schwab_utils import safe_float, validate_symbol

# Import the resilience wrapper (retry logic) and response parser for vendor API calls.
from schwab_vendor_resilience import parse_client_response, retry_vendor_call
# Import the function to generate a default "halted" payload when data is missing.
from schwab_grounding_schema import build_halted_grounding
# Import classification functions to determine the exact type of the financial instrument.
from schwab_instrument_classification import (
    classify_desc_pooled_match,
    classify_foreign_adr,
    classify_foreign_country,
    classify_fund_type,
    classify_mutual_fund,
    classify_quote_age,
    classify_structural_wrapper,
    classify_warrant,
    functionally_zero,
)
# Import resolver functions to clean up and standardize fundamental metrics.
from schwab_fundamental_resolvers import (
    resolve_dividend,
    resolve_margin_sanity,
    resolve_pe_eps,
    resolve_shares_outstanding,
)
# Import the function to resolve the asset's shortability status.
from schwab_short_locate import resolve_short_locate
# Import the function to resolve the asset's liquidity profile.
from schwab_liquidity_book import resolve_liquidity

# Initialize a logger specifically for this marketdata module.
logger = logging.getLogger("schwab_raw_marketdata")
# Attach a null handler to avoid errors if logging isn't configured globally.
logger.addHandler(logging.NullHandler())


# Define the main function to extract and standardize underlying asset data.
def extract_strict_underlying_data(
    # The authenticated API client instance.
    client: Any,
    # The ticker symbol requested by the user.
    symbol: str,
    # The Eastern Time timezone object for timestamp conversion.
    tz_et: ZoneInfo
) -> Dict[str, Any]:
    # Clean and validate the requested symbol (e.g., trim whitespace, uppercase).
    clean_sym = validate_symbol(symbol)

    # Define an inner function to fetch the quote, decorated with the retry mechanism.
    @retry_vendor_call(max_retries=3, base_delay=0.2)
    def _fetch_quote(sym: str) -> Any:
        # Execute the get_quote method on the API client.
        return client.get_quote(sym)

    try:
        # Attempt to fetch the quote and parse the JSON response.
        res_dict = parse_client_response(_fetch_quote(clean_sym))
    except Exception as e:
        # If fetching fails entirely (even after retries), log a warning.
        logger.warning("Quote fetch raised for %s: %s", clean_sym, e)
        # Set the response dictionary to None.
        res_dict = None

    # If the response is not a valid dictionary or is empty.
    if not isinstance(res_dict, dict) or not res_dict:
        # Return a standardized "halted" payload since we have no data.
        return build_halted_grounding(clean_sym, tz_et, None, None)

    # The API might nest the data under the uppercase symbol, original symbol, lowercase symbol, or not at all.
    candidate = (
        res_dict.get(clean_sym)
        or res_dict.get(symbol)
        or res_dict.get(symbol.lower())
        or res_dict
    )

    # If the candidate object is a dictionary, we need to check if it's nested one more level deep.
    if isinstance(candidate, dict):
        # If the clean symbol exists as a key, drill down.
        if clean_sym in candidate and isinstance(candidate[clean_sym], dict):
            candidate = candidate[clean_sym]
        # If the original symbol exists as a key, drill down.
        elif symbol in candidate and isinstance(candidate[symbol], dict):
            candidate = candidate[symbol]

    # Assign the final data dictionary, defaulting to empty if it's not a dict.
    data = candidate if isinstance(candidate, dict) else {}

    # If we failed to find any data for the asset.
    if not data:
        # Return the halted payload.
        return build_halted_grounding(clean_sym, tz_et, None, None)

    # Extract the 'reference' block, defaulting to an empty dict if missing.
    ref = data.get("reference", {}) if isinstance(data.get("reference"), dict) else {}
    # Extract the 'quote' block, defaulting to an empty dict if missing.
    quote = data.get("quote", {}) if isinstance(data.get("quote"), dict) else {}
    # Extract the 'fundamental' block, defaulting to an empty dict if missing.
    fund = data.get("fundamental", {}) if isinstance(data.get("fundamental"), dict) else {}

    # Extract and uppercase the asset sub-type string.
    asset_sub = str(ref.get("assetSubType", "") or "").upper()
    # Extract and uppercase the asset main-type string.
    asset_main = str(ref.get("assetMainType", "") or "").upper()
    # Extract and uppercase the company description.
    desc = str(ref.get("description", "") or "").upper()

    # If neither quote data nor fundamental data is present.
    if not quote and not fund:
        # Return the halted payload.
        return build_halted_grounding(clean_sym, tz_et, None, None)

    # Safely convert the raw shares outstanding string/number to a float.
    raw_shares = safe_float(fund.get("sharesOutstanding"))

    # --- Classification (Batch 2) — original source position ---
    # Determine if this instrument is a warrant.
    is_warrant = classify_warrant(asset_sub, asset_main, desc, clean_sym)
    # Determine if this instrument is a mutual fund.
    is_mutual_fund = classify_mutual_fund(asset_sub, asset_main, clean_sym)
    # Determine if it's some other type of pooled fund (like an ETF).
    is_fund_type = classify_fund_type(asset_sub, asset_main, is_mutual_fund)
    # Check if the description matches common phrases for pooled investments.
    desc_pooled_match = classify_desc_pooled_match(desc)
    # Determine if it's a structural wrapper (like an ETF or ETN) based on previous classifications.
    is_structural_wrapper = classify_structural_wrapper(
        is_warrant, is_fund_type, desc_pooled_match
    )

    # Safely extract the last traded price.
    last_p = safe_float(quote.get("lastPrice"))
    # Safely extract the closing price.
    close_p = safe_float(quote.get("closePrice"))
    # Extract the raw quote time in milliseconds, defaulting to 0.
    q_time_raw = quote.get("quoteTime", 0)

    # If a quote time was provided.
    if q_time_raw:
        # Get the current UTC timestamp in seconds.
        now_ts = datetime.now(timezone.utc).timestamp()
        # Convert the quote time from milliseconds to seconds.
        quote_ts = q_time_raw / 1000.0
        # Convert the quote timestamp into an ISO-formatted string in the Eastern timezone.
        q_time_iso = (
            datetime.fromtimestamp(quote_ts, tz=timezone.utc)
            .astimezone(tz_et)
            .isoformat()
        )
        # Calculate how old the quote is in seconds, flooring at 0.0.
        q_age = max(0.0, round(now_ts - quote_ts, 2))
    else:
        # If no quote time exists, set both fields to None.
        q_time_iso = None
        q_age = None

    # Determine if the asset is halted or unquoted based on zero prices or missing data.
    is_halted_or_unquoted = (
        (functionally_zero(last_p) and functionally_zero(close_p))
        or (desc == "" and last_p is None)
    )

    # Assign a quote classification state.
    if is_halted_or_unquoted:
        # Mark as halted/unquoted.
        q_class = "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
    else:
        # Otherwise, classify based on how many seconds old the quote is.
        q_class = classify_quote_age(q_age)

    # Extract raw fundamental metrics safely to float.
    raw_pe = safe_float(fund.get("peRatio"))
    raw_eps = safe_float(fund.get("eps"))
    raw_div_amt = safe_float(fund.get("divAmount"))
    raw_div_y = safe_float(fund.get("divYield"))
    raw_div_freq = safe_float(fund.get("divFreq"))

    # Determine the country of origin by checking multiple potential locations in the payload.
    country = str(
        ref.get("country")
        or quote.get("country")
        or fund.get("country")
        or ""
    ).strip().upper()

    # Classify if the country is foreign (not US).
    is_foreign_country = classify_foreign_country(country)
    # Determine if this asset is an American Depositary Receipt (ADR) for a foreign company.
    is_foreign_adr = classify_foreign_adr(desc, asset_sub, is_foreign_country)

    # --- Resolvers (Batch 2) ---
    # Resolve the shares outstanding value and state string.
    shares_val, shares_state = resolve_shares_outstanding(
        raw_shares,
        is_halted_or_unquoted,
        is_warrant,
        is_structural_wrapper,
        is_foreign_adr,
    )

    # Resolve the PE ratio and EPS values alongside their state strings.
    pe_val, pe_state, eps_val, eps_state = resolve_pe_eps(
        raw_pe,
        raw_eps,
        is_halted_or_unquoted,
        is_warrant,
        is_structural_wrapper,
        is_foreign_adr,
    )

    # Resolve the dividend yield, its basis string, and its frequency state.
    raw_div_y, div_y_basis, raw_div_freq, div_freq_state = resolve_dividend(
        raw_div_y, raw_div_amt, raw_div_freq, is_halted_or_unquoted
    )

    # Extract profit margin metrics.
    net_m = safe_float(fund.get("netProfitMarginTTM"))
    op_m = safe_float(fund.get("operatingMarginTTM"))
    gross_m = safe_float(fund.get("grossMarginTTM"))

    # Resolve whether the margin fields look suspect or erroneous.
    margin_suspect, margin_reason, margin_state = resolve_margin_sanity(net_m, op_m)

    # Resolve the short locate/borrow status dictionary.
    short_dict = resolve_short_locate(ref, quote, is_halted_or_unquoted)

    # Resolve the liquidity profile dictionary.
    liq_dict = resolve_liquidity(quote, fund, is_mutual_fund, is_halted_or_unquoted)

    # --- Assembly tail (verbatim) ---
    # Assemble the final fundamental dictionary block.
    fund_dict: Dict[str, Any] = {
        # Include beta (volatility relative to the market).
        "beta": safe_float(fund.get("beta")),
        # Set beta state based on its existence.
        "beta_state": (
            "AS_REPORTED" if fund.get("beta") is not None else "VENDOR_UNAVAILABLE"
        ),
        # Include the resolved PE ratio.
        "peRatio": pe_val,
        # Include the resolved PE state.
        "peRatio_state": pe_state,
        # Include the Price/Earnings-to-Growth ratio.
        "pegRatio": safe_float(fund.get("pegRatio")),
        # Set PEG ratio state based on its existence.
        "pegRatio_state": (
            "AS_REPORTED"
            if fund.get("pegRatio") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        # Include the Price-to-Cash-Flow ratio.
        "pcfRatio": safe_float(fund.get("pcfRatio")),
        # Set PCF ratio state based on its existence.
        "pcfRatio_state": (
            "AS_REPORTED"
            if fund.get("pcfRatio") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        # Include the Price-to-Book ratio.
        "pbRatio": safe_float(fund.get("pbRatio")),
        # Include total debt to equity ratio.
        "totalDebtToEquity": safe_float(fund.get("totalDebtToEquity")),
        # Hardcode the debt to equity basis as unverified raw data.
        "totalDebtToEquity_basis": "VENDOR_RAW_UNVERIFIED",
        # Include trailing twelve month gross margin.
        "grossMarginTTM": gross_m,
        # Include trailing twelve month net profit margin.
        "netProfitMarginTTM": net_m,
        # Include trailing twelve month operating margin.
        "operatingMarginTTM": op_m,
        # Flag if the margin fields are suspect.
        "margin_fields_suspect": margin_suspect,
        # Provide the reason the margins are suspect.
        "margin_fields_suspect_reason": margin_reason,
        # State of the margin suspect flag.
        "margin_fields_suspect_state": margin_state,
        # Include Return on Equity (ROE).
        "returnOnEquity": safe_float(fund.get("returnOnEquity")),
        # Set ROE state.
        "returnOnEquity_state": (
            "AS_REPORTED"
            if fund.get("returnOnEquity") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        # Include Return on Assets (ROA).
        "returnOnAssets": safe_float(fund.get("returnOnAssets")),
        # Set ROA state.
        "returnOnAssets_state": (
            "AS_REPORTED"
            if fund.get("returnOnAssets") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        # Include resolved Earnings Per Share (EPS).
        "eps": eps_val,
        # Include resolved EPS state.
        "eps_state": eps_state,
        # Include year-over-year revenue change.
        "revChangeYear": safe_float(fund.get("revChangeYear")),
        # Set revenue change state.
        "revChangeYear_state": (
            "AS_REPORTED"
            if fund.get("revChangeYear") is not None
            else "VENDOR_UNAVAILABLE"
        ),
        # Include dividend yield, defaulting to 0.0 if missing.
        "divYield": raw_div_y if raw_div_y is not None else 0.0,
        # Include the basis for the dividend yield calculation.
        "divYield_basis": div_y_basis,
        # Include the raw dividend yield.
        "divYield_raw": raw_div_y if raw_div_y is not None else 0.0,
        # Format the dividend amount as a currency string, defaulting to $0.00.
        "divAmount": f"${raw_div_amt:.2f}" if raw_div_amt is not None else "$0.00",
        # Hardcode the amount basis to ANNUAL.
        "div_amount_basis": "ANNUAL",
        # Include the raw dividend frequency number.
        "divFreq": raw_div_freq,
        # Include the resolved shares outstanding value.
        "sharesOutstanding": shares_val,
        # Include the resolved shares outstanding state.
        "shares_outstanding_state": shares_state,
        # Include the market capitalization.
        "marketCap": safe_float(fund.get("marketCap")),
        # Hardcode the market cap unit string.
        "marketCap_unit": "VENDOR_RAW_UNVERIFIED",
    }

    # If a dividend frequency state string was produced, add it to the dictionary.
    if div_freq_state:
        fund_dict["divFreq_state"] = div_freq_state

    # Return the fully assembled multi-step dictionary.
    return {
        # The Phase 0 grounding block.
        "phase_0_grounding": {
            # Cleaned ticker symbol.
            "symbol": clean_sym,
            # Name of the company.
            "company_name": desc,
            # Formatted last traded price.
            "lastPrice": f"${last_p:.2f}" if last_p is not None else None,
            # Formatted closing price.
            "closePrice": f"${close_p:.2f}" if close_p is not None else None,
            # Quote timestamp as an ISO string.
            "quoteTime_ISO_ET": q_time_iso,
            # Quote age in seconds.
            "quote_age_seconds": q_age,
            # The classification of how fresh the quote is.
            "quote_age_classification": q_class,
        },
        # The Step 1 fundamental dictionary we just built.
        "step_1_fundamentals": fund_dict,
        # The short locate status block.
        "short_locate_status": short_dict,
        # The liquidity metrics block.
        "step_8_and_9_liquidity_and_sizing": liq_dict,
    }
