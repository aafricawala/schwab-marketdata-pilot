# Filename.py: schwab_underlying_grounding.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

# Filename.py: schwab_underlying_grounding.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

"""
# Execute this line of logic to process the data
schwab_underlying_grounding.py

# Execute this line of logic to process the data
Purpose:
# Execute this line of logic to process the data
This module acts as an orchestrator for assembling the "grounding" data for a financial asset.
# Execute this line of logic to process the data
It fetches the raw quote and fundamental data from the Schwab API and structures it into standardized
# Execute this line of logic to process the data
dictionaries representing Phase 0 (grounding), Step 1 (fundamentals), short locate status,
# Execute this line of logic to process the data
and liquidity metrics.

# Execute this line of logic to process the data
Prerequisites:
# Execute this line of logic to process the data
- Requires standard libraries (`logging`, `datetime`, `typing`, `zoneinfo`).
# Execute this line of logic to process the data
- Requires `schwab_utils` for validation and safe conversions.
# Execute this line of logic to process the data
- Requires `schwab_vendor_resilience` for API calling with automatic retries.
# Execute this line of logic to process the data
- Requires specialized classification and fundamental resolver modules (`schwab_instrument_classification`,
  # Execute this line of logic to process the data
  `schwab_fundamental_resolvers`, `schwab_short_locate`, `schwab_liquidity_book`).

# Execute this line of logic to process the data
What this module does:
# Execute this line of logic to process the data
1. Validates the provided ticker symbol.
# Execute this line of logic to process the data
2. Fetches the latest quote and fundamental data from the vendor API, handling retries automatically.
# Execute this line of logic to process the data
3. Parses the raw JSON response to extract the specific asset data.
# Execute this line of logic to process the data
4. Identifies the asset type (e.g., warrant, mutual fund, ADR) by looking at descriptions and subtypes.
# Execute this line of logic to process the data
5. Determines if the asset is currently halted, unquoted, or if the data is too old.
# Execute this line of logic to process the data
6. Calls out to dedicated "resolver" functions to clean up specific fields (like shares outstanding, PE ratios, dividends, and margins).
# Execute this line of logic to process the data
7. Calls out to dedicated modules to resolve short selling availability and liquidity.
# Execute this line of logic to process the data
8. Assembles and returns a final, highly structured dictionary categorized by pipeline steps.

# Execute this line of logic to process the data
Configuration knobs:
# Assign a value or initialize a variable
- API retries: `max_retries=3`, `base_delay=0.2` seconds.
# Execute this line of logic to process the data
- Quote age thresholds and classification logic are imported from `schwab_instrument_classification`.

# Execute this line of logic to process the data
Outputs:
# Execute this line of logic to process the data
- A dictionary containing nested blocks: `phase_0_grounding`, `step_1_fundamentals`,
  # Execute this line of logic to process the data
  `short_locate_status`, and `step_8_and_9_liquidity_and_sizing`.

# Execute this line of logic to process the data
Notes:
# Execute this line of logic to process the data
- This file relies heavily on "Batch 2" resolvers to apply business logic and clean the data.
# Execute this line of logic to process the data
- The original logic remains unchanged; the inline blocks were simply extracted into the resolver modules.
"""
# Enable modern type hinting features.
# Import specific components from a module
from __future__ import annotations

# Import the logging library to track events.
# Import the required external module
import logging
# Import datetime and timezone for handling quote timestamps.
# Import specific components from a module
from datetime import datetime, timezone
# Import typing hints for dictionaries and any types.
# Import specific components from a module
from typing import Any, Dict
# Import ZoneInfo for timezone handling (e.g., converting to Eastern Time).
# Import specific components from a module
from zoneinfo import ZoneInfo

# Import utility functions to safely cast floats and validate ticker symbols.
# Import specific components from a module
from schwab_utils import safe_float, validate_symbol

# Import the resilience wrapper (retry logic) and response parser for vendor API calls.
# Import specific components from a module
from schwab_vendor_resilience import parse_client_response, retry_vendor_call
# Import the function to generate a default "halted" payload when data is missing.
# Import specific components from a module
from schwab_grounding_schema import build_halted_grounding
# Import classification functions to determine the exact type of the financial instrument.
# Import specific components from a module
from schwab_instrument_classification import (
    # Execute this line of logic to process the data
    classify_desc_pooled_match,
    # Execute this line of logic to process the data
    classify_foreign_adr,
    # Execute this line of logic to process the data
    classify_foreign_country,
    # Execute this line of logic to process the data
    classify_fund_type,
    # Execute this line of logic to process the data
    classify_mutual_fund,
    # Execute this line of logic to process the data
    classify_quote_age,
    # Execute this line of logic to process the data
    classify_structural_wrapper,
    # Execute this line of logic to process the data
    classify_warrant,
    # Execute this line of logic to process the data
    functionally_zero,
# Execute this line of logic to process the data
)
# Import resolver functions to clean up and standardize fundamental metrics.
# Import specific components from a module
from schwab_fundamental_resolvers import (
    # Execute this line of logic to process the data
    resolve_dividend,
    # Execute this line of logic to process the data
    resolve_margin_sanity,
    # Execute this line of logic to process the data
    resolve_pe_eps,
    # Execute this line of logic to process the data
    resolve_shares_outstanding,
# Execute this line of logic to process the data
)
# Import the function to resolve the asset's shortability status.
# Import specific components from a module
from schwab_short_locate import resolve_short_locate
# Import the function to resolve the asset's liquidity profile.
# Import specific components from a module
from schwab_liquidity_book import resolve_liquidity

# Initialize a logger specifically for this marketdata module.
# Assign a value or initialize a variable
logger = logging.getLogger("schwab_raw_marketdata")
# Attach a null handler to avoid errors if logging isn't configured globally.
# Log an important message or event
logger.addHandler(logging.NullHandler())


# Define the main function to extract and standardize underlying asset data.
# Define a new function or method
def extract_strict_underlying_data(
    # The authenticated API client instance.
    # Execute this line of logic to process the data
    client: Any,
    # The ticker symbol requested by the user.
    # Execute this line of logic to process the data
    symbol: str,
    # The Eastern Time timezone object for timestamp conversion.
    # Execute this line of logic to process the data
    tz_et: ZoneInfo
# Execute this line of logic to process the data
) -> Dict[str, Any]:
    # Clean and validate the requested symbol (e.g., trim whitespace, uppercase).
    # Assign a value or initialize a variable
    clean_sym = validate_symbol(symbol)

    # Define an inner function to fetch the quote, decorated with the retry mechanism.
    # Assign a value or initialize a variable
    @retry_vendor_call(max_retries=3, base_delay=0.2)
    # Define a new function or method
    def _fetch_quote(sym: str) -> Any:
        # Execute the get_quote method on the API client.
        # Return the final computed result to the caller
        return client.get_quote(sym)

    # Start a try-catch block to handle potential errors
    try:
        # Attempt to fetch the quote and parse the JSON response.
        # Assign a value or initialize a variable
        res_dict = parse_client_response(_fetch_quote(clean_sym))
    # Catch and handle an exception
    except Exception as e:
        # If fetching fails entirely (even after retries), log a warning.
        # Log an important message or event
        logger.warning("Quote fetch raised for %s: %s", clean_sym, e)
        # Set the response dictionary to None.
        # Assign a value or initialize a variable
        res_dict = None

    # If the response is not a valid dictionary or is empty.
    # Check a conditional statement
    if not isinstance(res_dict, dict) or not res_dict:
        # Return a standardized "halted" payload since we have no data.
        # Return the final computed result to the caller
        return build_halted_grounding(clean_sym, tz_et, None, None)

    # The API might nest the data under the uppercase symbol, original symbol, lowercase symbol, or not at all.
    # Assign a value or initialize a variable
    candidate = (
        # Execute this line of logic to process the data
        res_dict.get(clean_sym)
        # Execute this line of logic to process the data
        or res_dict.get(symbol)
        # Execute this line of logic to process the data
        or res_dict.get(symbol.lower())
        # Execute this line of logic to process the data
        or res_dict
    # Execute this line of logic to process the data
    )

    # If the candidate object is a dictionary, we need to check if it's nested one more level deep.
    # Check a conditional statement
    if isinstance(candidate, dict):
        # If the clean symbol exists as a key, drill down.
        # Check a conditional statement
        if clean_sym in candidate and isinstance(candidate[clean_sym], dict):
            # Assign a value or initialize a variable
            candidate = candidate[clean_sym]
        # If the original symbol exists as a key, drill down.
        # Execute this line of logic to process the data
        elif symbol in candidate and isinstance(candidate[symbol], dict):
            # Assign a value or initialize a variable
            candidate = candidate[symbol]

    # Assign the final data dictionary, defaulting to empty if it's not a dict.
    # Assign a value or initialize a variable
    data = candidate if isinstance(candidate, dict) else {}

    # If we failed to find any data for the asset.
    # Check a conditional statement
    if not data:
        # Return the halted payload.
        # Return the final computed result to the caller
        return build_halted_grounding(clean_sym, tz_et, None, None)

    # Extract the 'reference' block, defaulting to an empty dict if missing.
    # Assign a value or initialize a variable
    ref = data.get("reference", {}) if isinstance(data.get("reference"), dict) else {}
    # Extract the 'quote' block, defaulting to an empty dict if missing.
    # Assign a value or initialize a variable
    quote = data.get("quote", {}) if isinstance(data.get("quote"), dict) else {}
    # Extract the 'fundamental' block, defaulting to an empty dict if missing.
    # Assign a value or initialize a variable
    fund = data.get("fundamental", {}) if isinstance(data.get("fundamental"), dict) else {}

    # Extract and uppercase the asset sub-type string.
    # Assign a value or initialize a variable
    asset_sub = str(ref.get("assetSubType", "") or "").upper()
    # Extract and uppercase the asset main-type string.
    # Assign a value or initialize a variable
    asset_main = str(ref.get("assetMainType", "") or "").upper()
    # Extract and uppercase the company description.
    # Assign a value or initialize a variable
    desc = str(ref.get("description", "") or "").upper()

    # If neither quote data nor fundamental data is present.
    # Check a conditional statement
    if not quote and not fund:
        # Return the halted payload.
        # Return the final computed result to the caller
        return build_halted_grounding(clean_sym, tz_et, None, None)

    # Safely convert the raw shares outstanding string/number to a float.
    # Assign a value or initialize a variable
    raw_shares = safe_float(fund.get("sharesOutstanding"))

    # --- Classification (Batch 2) — original source position ---
    # Determine if this instrument is a warrant.
    # Assign a value or initialize a variable
    is_warrant = classify_warrant(asset_sub, asset_main, desc, clean_sym)
    # Determine if this instrument is a mutual fund.
    # Assign a value or initialize a variable
    is_mutual_fund = classify_mutual_fund(asset_sub, asset_main, clean_sym)
    # Determine if it's some other type of pooled fund (like an ETF).
    # Assign a value or initialize a variable
    is_fund_type = classify_fund_type(asset_sub, asset_main, is_mutual_fund)
    # Check if the description matches common phrases for pooled investments.
    # Assign a value or initialize a variable
    desc_pooled_match = classify_desc_pooled_match(desc)
    # Determine if it's a structural wrapper (like an ETF or ETN) based on previous classifications.
    # Assign a value or initialize a variable
    is_structural_wrapper = classify_structural_wrapper(
        # Execute this line of logic to process the data
        is_warrant, is_fund_type, desc_pooled_match
    # Execute this line of logic to process the data
    )

    # Safely extract the last traded price.
    # Assign a value or initialize a variable
    last_p = safe_float(quote.get("lastPrice"))
    # Safely extract the closing price.
    # Assign a value or initialize a variable
    close_p = safe_float(quote.get("closePrice"))
    # Extract the raw quote time in milliseconds, defaulting to 0.
    # Assign a value or initialize a variable
    q_time_raw = quote.get("quoteTime", 0)

    # If a quote time was provided.
    # Check a conditional statement
    if q_time_raw:
        # Get the current UTC timestamp in seconds.
        # Assign a value or initialize a variable
        now_ts = datetime.now(timezone.utc).timestamp()
        # Convert the quote time from milliseconds to seconds.
        # Assign a value or initialize a variable
        quote_ts = q_time_raw / 1000.0
        # Convert the quote timestamp into an ISO-formatted string in the Eastern timezone.
        # Assign a value or initialize a variable
        q_time_iso = (
            # Assign a value or initialize a variable
            datetime.fromtimestamp(quote_ts, tz=timezone.utc)
            # Execute this line of logic to process the data
            .astimezone(tz_et)
            # Execute this line of logic to process the data
            .isoformat()
        # Execute this line of logic to process the data
        )
        # Calculate how old the quote is in seconds, flooring at 0.0.
        # Assign a value or initialize a variable
        q_age = max(0.0, round(now_ts - quote_ts, 2))
    # Execute this line of logic to process the data
    else:
        # If no quote time exists, set both fields to None.
        # Assign a value or initialize a variable
        q_time_iso = None
        # Assign a value or initialize a variable
        q_age = None

    # Determine if the asset is halted or unquoted based on zero prices or missing data.
    # Assign a value or initialize a variable
    is_halted_or_unquoted = (
        # Execute this line of logic to process the data
        (functionally_zero(last_p) and functionally_zero(close_p))
        # Assign a value or initialize a variable
        or (desc == "" and last_p is None)
    # Execute this line of logic to process the data
    )

    # Assign a quote classification state.
    # Check a conditional statement
    if is_halted_or_unquoted:
        # Mark as halted/unquoted.
        # Assign a value or initialize a variable
        q_class = "UNAVAILABLE_ASSET_HALTED_OR_UNQUOTED"
    # Execute this line of logic to process the data
    else:
        # Otherwise, classify based on how many seconds old the quote is.
        # Assign a value or initialize a variable
        q_class = classify_quote_age(q_age)

    # Extract raw fundamental metrics safely to float.
    # Assign a value or initialize a variable
    raw_pe = safe_float(fund.get("peRatio"))
    # Assign a value or initialize a variable
    raw_eps = safe_float(fund.get("eps"))
    # Assign a value or initialize a variable
    raw_div_amt = safe_float(fund.get("divAmount"))
    # Assign a value or initialize a variable
    raw_div_y = safe_float(fund.get("divYield"))
    # Assign a value or initialize a variable
    raw_div_freq = safe_float(fund.get("divFreq"))

    # Determine the country of origin by checking multiple potential locations in the payload.
    # Assign a value or initialize a variable
    country = str(
        # Execute this line of logic to process the data
        ref.get("country")
        # Execute this line of logic to process the data
        or quote.get("country")
        # Execute this line of logic to process the data
        or fund.get("country")
        # Execute this line of logic to process the data
        or ""
    # Execute this line of logic to process the data
    ).strip().upper()

    # Classify if the country is foreign (not US).
    # Assign a value or initialize a variable
    is_foreign_country = classify_foreign_country(country)
    # Determine if this asset is an American Depositary Receipt (ADR) for a foreign company.
    # Assign a value or initialize a variable
    is_foreign_adr = classify_foreign_adr(desc, asset_sub, is_foreign_country)

    # --- Resolvers (Batch 2) ---
    # Resolve the shares outstanding value and state string.
    # Assign a value or initialize a variable
    shares_val, shares_state = resolve_shares_outstanding(
        # Execute this line of logic to process the data
        raw_shares,
        # Execute this line of logic to process the data
        is_halted_or_unquoted,
        # Execute this line of logic to process the data
        is_warrant,
        # Execute this line of logic to process the data
        is_structural_wrapper,
        # Execute this line of logic to process the data
        is_foreign_adr,
    # Execute this line of logic to process the data
    )

    # Resolve the PE ratio and EPS values alongside their state strings.
    # Assign a value or initialize a variable
    pe_val, pe_state, eps_val, eps_state = resolve_pe_eps(
        # Execute this line of logic to process the data
        raw_pe,
        # Execute this line of logic to process the data
        raw_eps,
        # Execute this line of logic to process the data
        is_halted_or_unquoted,
        # Execute this line of logic to process the data
        is_warrant,
        # Execute this line of logic to process the data
        is_structural_wrapper,
        # Execute this line of logic to process the data
        is_foreign_adr,
    # Execute this line of logic to process the data
    )

    # Resolve the dividend yield, its basis string, and its frequency state.
    # Assign a value or initialize a variable
    raw_div_y, div_y_basis, raw_div_freq, div_freq_state = resolve_dividend(
        # Execute this line of logic to process the data
        raw_div_y, raw_div_amt, raw_div_freq, is_halted_or_unquoted
    # Execute this line of logic to process the data
    )

    # Extract profit margin metrics.
    # Assign a value or initialize a variable
    net_m = safe_float(fund.get("netProfitMarginTTM"))
    # Assign a value or initialize a variable
    op_m = safe_float(fund.get("operatingMarginTTM"))
    # Assign a value or initialize a variable
    gross_m = safe_float(fund.get("grossMarginTTM"))

    # Resolve whether the margin fields look suspect or erroneous.
    # Assign a value or initialize a variable
    margin_suspect, margin_reason, margin_state = resolve_margin_sanity(net_m, op_m)

    # Resolve the short locate/borrow status dictionary.
    # Assign a value or initialize a variable
    short_dict = resolve_short_locate(ref, quote, is_halted_or_unquoted)

    # Resolve the liquidity profile dictionary.
    # Assign a value or initialize a variable
    liq_dict = resolve_liquidity(quote, fund, is_mutual_fund, is_halted_or_unquoted)

    # --- Assembly tail (verbatim) ---
    # Assemble the final fundamental dictionary block.
    # Assign a value or initialize a variable
    fund_dict: Dict[str, Any] = {
        # Include beta (volatility relative to the market).
        # Execute this line of logic to process the data
        "beta": safe_float(fund.get("beta")),
        # Set beta state based on its existence.
        # Execute this line of logic to process the data
        "beta_state": (
            # Execute this line of logic to process the data
            "AS_REPORTED" if fund.get("beta") is not None else "VENDOR_UNAVAILABLE"
        # Execute this line of logic to process the data
        ),
        # Include the resolved PE ratio.
        # Execute this line of logic to process the data
        "peRatio": pe_val,
        # Include the resolved PE state.
        # Execute this line of logic to process the data
        "peRatio_state": pe_state,
        # Include the Price/Earnings-to-Growth ratio.
        # Execute this line of logic to process the data
        "pegRatio": safe_float(fund.get("pegRatio")),
        # Set PEG ratio state based on its existence.
        # Execute this line of logic to process the data
        "pegRatio_state": (
            # Execute this line of logic to process the data
            "AS_REPORTED"
            # Check a conditional statement
            if fund.get("pegRatio") is not None
            # Execute this line of logic to process the data
            else "VENDOR_UNAVAILABLE"
        # Execute this line of logic to process the data
        ),
        # Include the Price-to-Cash-Flow ratio.
        # Execute this line of logic to process the data
        "pcfRatio": safe_float(fund.get("pcfRatio")),
        # Set PCF ratio state based on its existence.
        # Execute this line of logic to process the data
        "pcfRatio_state": (
            # Execute this line of logic to process the data
            "AS_REPORTED"
            # Check a conditional statement
            if fund.get("pcfRatio") is not None
            # Execute this line of logic to process the data
            else "VENDOR_UNAVAILABLE"
        # Execute this line of logic to process the data
        ),
        # Include the Price-to-Book ratio.
        # Execute this line of logic to process the data
        "pbRatio": safe_float(fund.get("pbRatio")),
        # Include total debt to equity ratio.
        # Execute this line of logic to process the data
        "totalDebtToEquity": safe_float(fund.get("totalDebtToEquity")),
        # Hardcode the debt to equity basis as unverified raw data.
        # Execute this line of logic to process the data
        "totalDebtToEquity_basis": "VENDOR_RAW_UNVERIFIED",
        # Include trailing twelve month gross margin.
        # Execute this line of logic to process the data
        "grossMarginTTM": gross_m,
        # Include trailing twelve month net profit margin.
        # Execute this line of logic to process the data
        "netProfitMarginTTM": net_m,
        # Include trailing twelve month operating margin.
        # Execute this line of logic to process the data
        "operatingMarginTTM": op_m,
        # Flag if the margin fields are suspect.
        # Execute this line of logic to process the data
        "margin_fields_suspect": margin_suspect,
        # Provide the reason the margins are suspect.
        # Execute this line of logic to process the data
        "margin_fields_suspect_reason": margin_reason,
        # State of the margin suspect flag.
        # Execute this line of logic to process the data
        "margin_fields_suspect_state": margin_state,
        # Include Return on Equity (ROE).
        # Execute this line of logic to process the data
        "returnOnEquity": safe_float(fund.get("returnOnEquity")),
        # Set ROE state.
        # Execute this line of logic to process the data
        "returnOnEquity_state": (
            # Execute this line of logic to process the data
            "AS_REPORTED"
            # Check a conditional statement
            if fund.get("returnOnEquity") is not None
            # Execute this line of logic to process the data
            else "VENDOR_UNAVAILABLE"
        # Execute this line of logic to process the data
        ),
        # Include Return on Assets (ROA).
        # Execute this line of logic to process the data
        "returnOnAssets": safe_float(fund.get("returnOnAssets")),
        # Set ROA state.
        # Execute this line of logic to process the data
        "returnOnAssets_state": (
            # Execute this line of logic to process the data
            "AS_REPORTED"
            # Check a conditional statement
            if fund.get("returnOnAssets") is not None
            # Execute this line of logic to process the data
            else "VENDOR_UNAVAILABLE"
        # Execute this line of logic to process the data
        ),
        # Include resolved Earnings Per Share (EPS).
        # Execute this line of logic to process the data
        "eps": eps_val,
        # Include resolved EPS state.
        # Execute this line of logic to process the data
        "eps_state": eps_state,
        # Include year-over-year revenue change.
        # Execute this line of logic to process the data
        "revChangeYear": safe_float(fund.get("revChangeYear")),
        # Set revenue change state.
        # Execute this line of logic to process the data
        "revChangeYear_state": (
            # Execute this line of logic to process the data
            "AS_REPORTED"
            # Check a conditional statement
            if fund.get("revChangeYear") is not None
            # Execute this line of logic to process the data
            else "VENDOR_UNAVAILABLE"
        # Execute this line of logic to process the data
        ),
        # Include dividend yield, defaulting to 0.0 if missing.
        # Execute this line of logic to process the data
        "divYield": raw_div_y if raw_div_y is not None else 0.0,
        # Include the basis for the dividend yield calculation.
        # Execute this line of logic to process the data
        "divYield_basis": div_y_basis,
        # Include the raw dividend yield.
        # Execute this line of logic to process the data
        "divYield_raw": raw_div_y if raw_div_y is not None else 0.0,
        # Format the dividend amount as a currency string, defaulting to $0.00.
        # Execute this line of logic to process the data
        "divAmount": f"${raw_div_amt:.2f}" if raw_div_amt is not None else "$0.00",
        # Hardcode the amount basis to ANNUAL.
        # Execute this line of logic to process the data
        "div_amount_basis": "ANNUAL",
        # Include the raw dividend frequency number.
        # Execute this line of logic to process the data
        "divFreq": raw_div_freq,
        # Include the resolved shares outstanding value.
        # Execute this line of logic to process the data
        "sharesOutstanding": shares_val,
        # Include the resolved shares outstanding state.
        # Execute this line of logic to process the data
        "shares_outstanding_state": shares_state,
        # Include the market capitalization.
        # Execute this line of logic to process the data
        "marketCap": safe_float(fund.get("marketCap")),
        # Hardcode the market cap unit string.
        # Execute this line of logic to process the data
        "marketCap_unit": "VENDOR_RAW_UNVERIFIED",
    # Execute this line of logic to process the data
    }

    # If a dividend frequency state string was produced, add it to the dictionary.
    # Check a conditional statement
    if div_freq_state:
        # Assign a value or initialize a variable
        fund_dict["divFreq_state"] = div_freq_state

    # Return the fully assembled multi-step dictionary.
    # Return the final computed result to the caller
    return {
        # The Phase 0 grounding block.
        # Execute this line of logic to process the data
        "phase_0_grounding": {
            # Cleaned ticker symbol.
            # Execute this line of logic to process the data
            "symbol": clean_sym,
            # Name of the company.
            # Execute this line of logic to process the data
            "company_name": desc,
            # Formatted last traded price.
            # Execute this line of logic to process the data
            "lastPrice": f"${last_p:.2f}" if last_p is not None else None,
            # Formatted closing price.
            # Execute this line of logic to process the data
            "closePrice": f"${close_p:.2f}" if close_p is not None else None,
            # Quote timestamp as an ISO string.
            # Execute this line of logic to process the data
            "quoteTime_ISO_ET": q_time_iso,
            # Quote age in seconds.
            # Execute this line of logic to process the data
            "quote_age_seconds": q_age,
            # The classification of how fresh the quote is.
            # Execute this line of logic to process the data
            "quote_age_classification": q_class,
        # Execute this line of logic to process the data
        },
        # The Step 1 fundamental dictionary we just built.
        # Execute this line of logic to process the data
        "step_1_fundamentals": fund_dict,
        # The short locate status block.
        # Execute this line of logic to process the data
        "short_locate_status": short_dict,
        # The liquidity metrics block.
        # Execute this line of logic to process the data
        "step_8_and_9_liquidity_and_sizing": liq_dict,
    # Execute this line of logic to process the data
    }
