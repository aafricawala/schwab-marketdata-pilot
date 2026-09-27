"""
schwab_instrument_classification.py

Pure classifiers over the vendor reference/quote envelope:
  - instrument type (warrant / mutual fund / fund-type / structural wrapper / ADR / foreign)
  - quote-age bucket (REAL_TIME / RECENT / DELAYED / STALE / UNKNOWN)
  - functionally-zero helper used by halted detection

Extracted verbatim from schwab_raw_marketdata.py (no logic change).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


def classify_warrant(
    asset_sub: str, asset_main: str, desc: str, clean_sym: str
) -> bool:
    return (
        asset_sub in ["WARRANT", "WARNT"]
        or asset_main in ["WARRANT", "WARNT"]
        or bool(re.search(r"\b(WARRANT|WARNT|WRNT)\b", desc))
        or bool(re.search(r"(\.WS|[\.\/\-\s]WS|\.WT|[\.\/\-\s]WT|^[A-Z]{3,4}WW)$", clean_sym))
    )


def classify_mutual_fund(
    asset_sub: str, asset_main: str, clean_sym: str
) -> bool:
    return (
        asset_sub in ["MUTUAL_FUND", "OPEN_END_FUND"]
        or asset_main in ["MUTUAL_FUND"]
        or bool(re.search(r"^[A-Z]{4}X$", clean_sym))
    )


def classify_fund_type(
    asset_sub: str, asset_main: str, mutual_fund_flag: bool
) -> bool:
    return (
        mutual_fund_flag
        or asset_sub in ["ETF", "ETN", "CEF", "UIT", "CLOSED_END_FUND"]
        or asset_main in ["ETF", "ETN", "FUND", "COLLECTIVE_INVESTMENT"]
    )


def classify_desc_pooled_match(desc: str) -> bool:
    return bool(
        re.search(
            r"\b(ETF|ETN|MUTUAL FUND|INDEX FUND|TRUST|INDEX|PORTFOLIO|ETRACS|TREASURY BOND|BOND FUND|ADMIRAL|INVESTOR CLASS)\b",
            desc,
        )
    )


def classify_structural_wrapper(
    warrant_flag: bool, fund_type_flag: bool, pooled_match: bool
) -> bool:
    return not warrant_flag and (fund_type_flag or pooled_match)


def classify_foreign_country(country: str) -> bool:
    return (
        bool(country)
        and bool(re.match(r"^[A-Z]{2,3}$", country))
        and (country not in ["US", "USA"])
    )


def classify_foreign_adr(
    desc: str,
    asset_sub: str,
    foreign_country_flag: bool,
) -> bool:
    return (
        bool(re.search(r"\bADR\b", desc))
        or asset_sub == "ADR"
        or foreign_country_flag
        or bool(
            re.search(
                r"\b(CHINA|ISRAEL|UNITED KINGDOM|BERMUDA|NETHERLANDS|GERMANY|SWITZERLAND|FRANCE|IRELAND|JAPAN|TAIWAN|BRAZIL|CANADA|KOREA|SOUTH AFRICA)\b",
                desc,
            )
        )
    )


def functionally_zero(v: Optional[float]) -> bool:
    return v is None or abs(v) < 0.01


def classify_quote_age(q_age: Optional[float]) -> str:
    if q_age is not None:
        return (
            "REAL_TIME"
            if q_age <= 60.0
            else (
                "RECENT"
                if q_age <= 600.0
                else ("DELAYED" if q_age <= 3600.0 else "STALE")
            )
        )
    return "UNKNOWN"