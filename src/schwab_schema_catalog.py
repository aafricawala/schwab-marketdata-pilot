"""
schwab_schema_catalog.py
-----------------------------------------------------------------------------
Institutional Data Dictionary & Schema Catalog for Schwab Market Data REST APIs.

Scope:
  Catalogs the full OpenAPI specification parameters across all 7 endpoint families:
    1. Quotes (/quotes)
    2. Price History (/pricehistory)
    3. Option Chains (/chains)
    4. Option Expirations (/expirationchain)
    5. Instruments (/instruments)
    6. Movers (/movers/{index_symbol})
    7. Market Hours (/markets)

Features:
  - Zero Network Dependencies: Requires no API keys or live requests.
  - Full Tabular Mapping: Maps JSON keys, parent containers, data types,
    semantic definitions, and institutional quant/risk use cases.
  - Interactive Filtering: Inspect by endpoint or export to pandas DataFrame.
-----------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Optional
import pandas as pd


SCHEMA_REGISTRY: List[Dict[str, str]] = [
    # =========================================================================
    # 1. QUOTES ENDPOINT (/quotes)
    # =========================================================================
    # --- quote sub-dictionary (Pricing & Real-Time Liquidity) ---
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "bidPrice",
        "data_type": "float",
        "description": "Current highest buying price",
        "risk_quant_application": "Bid-ask spread modeling, execution slippage calculation",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "askPrice",
        "data_type": "float",
        "description": "Current lowest selling price",
        "risk_quant_application": "Liquidity cost assessment, arrival price benchmarking",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "lastPrice",
        "data_type": "float",
        "description": "Price at which the most recent trade cleared",
        "risk_quant_application": "Mark-to-market portfolio valuation, intraday PnL",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "mark",
        "data_type": "float",
        "description": "Midpoint between bid and ask (or last price within spread)",
        "risk_quant_application": "Illiquid security fair-value pricing, margin monitoring",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "bidSize",
        "data_type": "int",
        "description": "Number of shares available at bid (in 100-share lots)",
        "risk_quant_application": "Market depth analysis, order book imbalance metrics",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "askSize",
        "data_type": "int",
        "description": "Number of shares available at ask (in 100-share lots)",
        "risk_quant_application": "Immediate liquidity exhaustion modeling",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "totalVolume",
        "data_type": "int",
        "description": "Aggregated share volume across regular and extended sessions",
        "risk_quant_application": "Participation rate algorithms (VWAP/TWAP), liquidity screens",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "openPrice",
        "data_type": "float",
        "description": "Regular session opening print",
        "risk_quant_application": "Overnight gap risk calculation, intraday range expansion",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "highPrice",
        "data_type": "float",
        "description": "Highest traded price in current regular session",
        "risk_quant_application": "Intraday volatility modeling, Garman-Klass volatility",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "lowPrice",
        "data_type": "float",
        "description": "Lowest traded price in current regular session",
        "risk_quant_application": "Support breach detection, range-based variance estimators",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "closePrice",
        "data_type": "float",
        "description": "Previous trading day official closing price",
        "risk_quant_application": "Base price for daily return computation, VaR calculation",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "netChange",
        "data_type": "float",
        "description": "Absolute price change from previous close",
        "risk_quant_application": "Daily PnL attribution, momentum factor rankings",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "netPercentChange",
        "data_type": "float",
        "description": "Percentage price change from previous close",
        "risk_quant_application": "Relative cross-asset momentum ranking, breakout triggers",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "52WeekHigh",
        "data_type": "float",
        "description": "Highest price achieved over rolling 52-week window",
        "risk_quant_application": "52-week high momentum factor (George & Hwang model)",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "52WeekLow",
        "data_type": "float",
        "description": "Lowest price achieved over rolling 52-week window",
        "risk_quant_application": "Downside tail risk, mean-reversion screening",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "securityStatus",
        "data_type": "str",
        "description": "Trading state ('Normal', 'Halted', 'Closed')",
        "risk_quant_application": "Circuit-breaker handling, operational kill-switch logic",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "bidMICId",
        "data_type": "str",
        "description": "Market Identifier Code (ISO 10383) for best bid venue",
        "risk_quant_application": "Smart order routing (SOR) analysis, routing fragmentation",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "askMICId",
        "data_type": "str",
        "description": "Market Identifier Code (ISO 10383) for best ask venue",
        "risk_quant_application": "Exchange fee optimization, maker-taker rebate capture",
    },
    {
        "endpoint": "Quotes",
        "container": "quote",
        "field": "quoteTime",
        "data_type": "int",
        "description": "Epoch timestamp in milliseconds of latest quote update",
        "risk_quant_application": "Quote staleness checks, data latency SLA monitoring",
    },
    # --- fundamental sub-dictionary (Accounting, Valuation & Risk Factors) ---
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "peRatio",
        "data_type": "float",
        "description": "Trailing Price-to-Earnings ratio",
        "risk_quant_application": "Value factor equity screening, style-box allocation",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "pegRatio",
        "data_type": "float",
        "description": "Price/Earnings-to-Growth ratio",
        "risk_quant_application": "GARP (Growth At Reasonable Price) quantitative strategy",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "pbRatio",
        "data_type": "float",
        "description": "Price-to-Book value ratio",
        "risk_quant_application": "Fama-French HML (High Minus Low) factor modeling",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "prRatio",
        "data_type": "float",
        "description": "Price-to-Revenue (Sales) ratio",
        "risk_quant_application": "Unprofitable growth company relative valuation",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "pcfRatio",
        "data_type": "float",
        "description": "Price-to-Cash-Flow ratio",
        "risk_quant_application": "Cash earnings quality screen, insolvency defense",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "beta",
        "data_type": "float",
        "description": "Systematic market risk coefficient against S&P 500",
        "risk_quant_application": "CAPM market sensitivity, portfolio beta-hedging weights",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "eps",
        "data_type": "float",
        "description": "Diluted earnings per share (TTM)",
        "risk_quant_application": "Earnings surprises, fundamental factor indexing",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "divYield",
        "data_type": "float",
        "description": "Annualized dividend yield percentage",
        "risk_quant_application": "Carry trade strategies, dividend discount modeling",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "divAmount",
        "data_type": "float",
        "description": "Dividend payout amount per share",
        "risk_quant_application": "Cash flow matching, ex-dividend price drop adjustments",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "divFreq",
        "data_type": "int",
        "description": "Dividend distribution frequency (1=Ann, 2=Semi, 4=Qtr, 12=Mth)",
        "risk_quant_application": "Cash flow scheduling, early option assignment risk",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "divDate",
        "data_type": "str",
        "description": "Ex-dividend date (YYYY-MM-DD)",
        "risk_quant_application": "American call option early assignment arbitrage modeling",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "grossMarginTTM",
        "data_type": "float",
        "description": "Gross profit margin percentage over trailing twelve months",
        "risk_quant_application": "Quality factor scoring (Novy-Marx gross profitability)",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "netProfitMarginTTM",
        "data_type": "float",
        "description": "Net profit margin percentage (TTM)",
        "risk_quant_application": "Operating leverage analysis, margin compression detection",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "returnOnEquity",
        "data_type": "float",
        "description": "Return on common equity (ROE)",
        "risk_quant_application": "DuPont framework decomposition, management efficiency",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "returnOnAssets",
        "data_type": "float",
        "description": "Return on total assets (ROA)",
        "risk_quant_application": "Capital allocation efficiency, asset-heavy sector screens",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "quickRatio",
        "data_type": "float",
        "description": "Acid-test liquidity ratio ((Cash + Receivables) / Current Liab)",
        "risk_quant_application": "Short-term credit risk, debt-distress screens",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "currentRatio",
        "data_type": "float",
        "description": "Current Assets divided by Current Liabilities",
        "risk_quant_application": "Working capital buffer, working capital stress testing",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "totalDebtToEquity",
        "data_type": "float",
        "description": "Total debt liabilities divided by total shareholders equity",
        "risk_quant_application": "Financial leverage risk, interest rate vulnerability",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "marketCap",
        "data_type": "float",
        "description": "Total market capitalization in millions",
        "risk_quant_application": "Size factor (SMB), institutional liquidity tier weighting",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "sharesOutstanding",
        "data_type": "float",
        "description": "Total shares issued and outstanding",
        "risk_quant_application": "Index weight rebalancing, dilution / buyback yield tracking",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "vol10DayAvg",
        "data_type": "float",
        "description": "10-day rolling average trading volume",
        "risk_quant_application": "Short-term volume spike anomaly detection",
    },
    {
        "endpoint": "Quotes",
        "container": "fundamental",
        "field": "vol3MonthAvg",
        "data_type": "float",
        "description": "90-day baseline average trading volume",
        "risk_quant_application": "Baseline institutional capacity / position size limits",
    },
    # --- reference sub-dictionary (Asset Master & Borrow Risk) ---
    {
        "endpoint": "Quotes",
        "container": "reference",
        "field": "cusip",
        "data_type": "str",
        "description": "9-digit Committee on Uniform Securities Identification Procedures",
        "risk_quant_application": "Security master deduplication, corporate action linking",
    },
    {
        "endpoint": "Quotes",
        "container": "reference",
        "field": "exchangeName",
        "data_type": "str",
        "description": "Primary listing exchange name (e.g., 'NASDAQ', 'NYSE')",
        "risk_quant_application": "Opening/closing auction routing, regulatory halt source",
    },
    {
        "endpoint": "Quotes",
        "container": "reference",
        "field": "isShortable",
        "data_type": "bool",
        "description": "Brokerage flag indicating if security can be shorted",
        "risk_quant_application": "Long/short equity execution feasibility gate",
    },
    {
        "endpoint": "Quotes",
        "container": "reference",
        "field": "isHardToBorrow",
        "data_type": "bool",
        "description": "Flag indicating elevated borrow friction or locate deficits",
        "risk_quant_application": "Short-squeeze risk indicator, special-rate locate tracking",
    },
    {
        "endpoint": "Quotes",
        "container": "reference",
        "field": "htbRate",
        "data_type": "float",
        "description": "Hard-to-borrow annualized borrow fee rate percentage",
        "risk_quant_application": "Negative carry cost in short portfolios, conversion arbitrage",
    },
    {
        "endpoint": "Quotes",
        "container": "reference",
        "field": "htbQuantity",
        "data_type": "int",
        "description": "Available locate shares currently open in inventory",
        "risk_quant_application": "Short capacity constraint checking, borrow depth sizing",
    },
    # --- regular & extended sub-dictionaries (Session Isolation) ---
    {
        "endpoint": "Quotes",
        "container": "regular",
        "field": "regularMarketLastPrice",
        "data_type": "float",
        "description": "Last print recorded exclusively during standard session",
        "risk_quant_application": "Official cash market benchmark, eliminating off-hour prints",
    },
    {
        "endpoint": "Quotes",
        "container": "regular",
        "field": "regularMarketPercentChange",
        "data_type": "float",
        "description": "Regular session percentage change",
        "risk_quant_application": "Index tracking variance calculation",
    },
    {
        "endpoint": "Quotes",
        "container": "extended",
        "field": "extendedMarketLastPrice",
        "data_type": "float",
        "description": "Latest trade print in pre-market or after-hours session",
        "risk_quant_application": "Earnings release gap estimation, overnight risk exposure",
    },
    # =========================================================================
    # 2. PRICE HISTORY ENDPOINT (/pricehistory)
    # =========================================================================
    {
        "endpoint": "PriceHistory",
        "container": "root",
        "field": "symbol",
        "data_type": "str",
        "description": "Queried instrument ticker symbol",
        "risk_quant_application": "Timeseries join validation, universe indexing",
    },
    {
        "endpoint": "PriceHistory",
        "container": "root",
        "field": "empty",
        "data_type": "bool",
        "description": "Flag indicating whether no historical bars were returned",
        "risk_quant_application": "Defensive exception branching, halts/new listing detection",
    },
    {
        "endpoint": "PriceHistory",
        "container": "root",
        "field": "previousClose",
        "data_type": "float",
        "description": "Reference previous trading session close",
        "risk_quant_application": "First-candle return chaining, baseline shift calibration",
    },
    {
        "endpoint": "PriceHistory",
        "container": "candles",
        "field": "datetime",
        "data_type": "int (epoch ms)",
        "description": "Candle open timestamp in milliseconds since Epoch UTC",
        "risk_quant_application": "Temporal alignment, resampling, cross-sectional panel builds",
    },
    {
        "endpoint": "PriceHistory",
        "container": "candles",
        "field": "open",
        "data_type": "float",
        "description": "First executed trade price within the bar window",
        "risk_quant_application": "Bar-by-bar return calculation, opening range breakout strategies",
    },
    {
        "endpoint": "PriceHistory",
        "container": "candles",
        "field": "high",
        "data_type": "float",
        "description": "Peak trade print executed within the bar window",
        "risk_quant_application": "Parkinson volatility, ATR (Average True Range), stop-loss checks",
    },
    {
        "endpoint": "PriceHistory",
        "container": "candles",
        "field": "low",
        "data_type": "float",
        "description": "Trough trade print executed within the bar window",
        "risk_quant_application": "Maximum drawdown, intraday price variance bounds",
    },
    {
        "endpoint": "PriceHistory",
        "container": "candles",
        "field": "close",
        "data_type": "float",
        "description": "Final trade print executed within the bar window",
        "risk_quant_application": "Continuous returns series, covariance matrix calibration",
    },
    {
        "endpoint": "PriceHistory",
        "container": "candles",
        "field": "volume",
        "data_type": "int",
        "description": "Total share units transacted during candle interval",
        "risk_quant_application": "Volume profile, institutional accumulation/distribution",
    },
    # =========================================================================
    # 3. OPTION CHAINS ENDPOINT (/chains)
    # =========================================================================
    {
        "endpoint": "OptionChains",
        "container": "root",
        "field": "underlyingPrice",
        "data_type": "float",
        "description": "Live spot price of the underlying equity/ETF",
        "risk_quant_application": "Moneyness benchmark (S/K), Black-Scholes spot input",
    },
    {
        "endpoint": "OptionChains",
        "container": "root",
        "field": "volatility",
        "data_type": "float",
        "description": "Aggregated 30-day implied volatility across option chain",
        "risk_quant_application": "VIX-style index replication, macro market fear indicator",
    },
    {
        "endpoint": "OptionChains",
        "container": "root",
        "field": "interestRate",
        "data_type": "float",
        "description": "Risk-free rate assumed in pricing models",
        "risk_quant_application": "Drift parameter in option pricing, cost-of-carry calibration",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "putCallIndicator",
        "data_type": "str",
        "description": "Contract derivative right ('CALL' or 'PUT')",
        "risk_quant_application": "Put/Call ratio calculation, skew decomposition",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "strikePrice",
        "data_type": "float",
        "description": "Exercise strike price",
        "risk_quant_application": "Strike axis on volatility smile/surface, delta pinning",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "daysToExpiration",
        "data_type": "int",
        "description": "Calendar days remaining until contract expiration (DTE)",
        "risk_quant_application": "Term-structure time-decay axis (tau), calendar spread pricing",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "bid / ask / mark",
        "data_type": "float",
        "description": "Derivative contract market bid, ask, and synthetic midpoint",
        "risk_quant_application": "Derivative execution cost, structured product valuations",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "totalVolume",
        "data_type": "int",
        "description": "Aggregated contracts traded during current session",
        "risk_quant_application": "Unusual options activity detection, institutional sweep alerts",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "openInterest",
        "data_type": "int",
        "description": "Total outstanding unsettled contracts",
        "risk_quant_application": "Gamma exposure (GEX) market maker positioning models",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "volatility",
        "data_type": "float",
        "description": "Black-Scholes Implied Volatility (IV) percentage",
        "risk_quant_application": "IV rank, IV percentile, SABR / SVI volatility surface fitting",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "delta",
        "data_type": "float",
        "description": "First-order price sensitivity (dV / dS)",
        "risk_quant_application": "Hedge ratio calculation, delta-neutral rebalancing, probability ITM",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "gamma",
        "data_type": "float",
        "description": "Second-order price sensitivity (d^2V / dS^2)",
        "risk_quant_application": "Gamma squeeze modeling, market maker hedging acceleration",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "theta",
        "data_type": "float",
        "description": "Time decay sensitivity (dV / dt) in points per day",
        "risk_quant_application": "Net portfolio theta harvesting, premium decay optimization",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "vega",
        "data_type": "float",
        "description": "Implied volatility sensitivity (dV / dsigma)",
        "risk_quant_application": "Vol-spike risk hedging, vega-weighted risk management",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "rho",
        "data_type": "float",
        "description": "Interest rate sensitivity (dV / dr)",
        "risk_quant_application": "Long-dated LEAPS interest rate duration management",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "inTheMoney",
        "data_type": "bool",
        "description": "Flag indicating if strike has intrinsic value",
        "risk_quant_application": "Assignment risk tracking, physical deliverable exposure",
    },
    {
        "endpoint": "OptionChains",
        "container": "OptionContract",
        "field": "theoreticalOptionValue",
        "data_type": "float",
        "description": "Pricing model output fair value",
        "risk_quant_application": "Relative mispricing discovery, statistical arbitrage",
    },
    # =========================================================================
    # 4. OPTION EXPIRATIONS ENDPOINT (/expirationchain)
    # =========================================================================
    {
        "endpoint": "OptionExpirations",
        "container": "expirationList",
        "field": "expirationDate",
        "data_type": "str (YYYY-MM-DD)",
        "description": "Active contract settlement expiration date",
        "risk_quant_application": "Expiration calendar scheduling, roll-schedule management",
    },
    {
        "endpoint": "OptionExpirations",
        "container": "expirationList",
        "field": "daysToExpiration",
        "data_type": "int",
        "description": "Calendar days remaining until expiration",
        "risk_quant_application": "Filtering target DTE tenors (e.g. 0-DTE, 30-DTE, 45-DTE)",
    },
    {
        "endpoint": "OptionExpirations",
        "container": "expirationList",
        "field": "expirationType",
        "data_type": "str",
        "description": "Cycle frequency ('S'=Standard, 'W'=Weekly, 'Q'=Quarterly)",
        "risk_quant_application": "Liquidity concentration analysis (monthly vs. weekly cycles)",
    },
    {
        "endpoint": "OptionExpirations",
        "container": "expirationList",
        "field": "settlementType",
        "data_type": "str",
        "description": "Settlement timing ('A'=AM settled, 'P'=PM settled)",
        "risk_quant_application": "Overnight cash settlement risk vs. end-of-day market print",
    },
    # =========================================================================
    # 5. INSTRUMENTS ENDPOINT (/instruments)
    # =========================================================================
    {
        "endpoint": "Instruments",
        "container": "instruments",
        "field": "cusip",
        "data_type": "str",
        "description": "Official 9-character CUSIP identifier",
        "risk_quant_application": "Cross-platform reconciliation, symbology cross-walks",
    },
    {
        "endpoint": "Instruments",
        "container": "instruments",
        "field": "assetType",
        "data_type": "str",
        "description": "Asset class ('EQUITY', 'ETF', 'BOND', 'MUTUAL_FUND')",
        "risk_quant_application": "Asset-allocation constraint verification, mandate compliance",
    },
    {
        "endpoint": "Instruments",
        "container": "instruments",
        "field": "description",
        "data_type": "str",
        "description": "Official legal name of the entity or fund",
        "risk_quant_application": "Security master entity resolution, textual categorization",
    },
    {
        "endpoint": "Instruments",
        "container": "fundamental",
        "field": "sharesFloat",
        "data_type": "float",
        "description": "Total shares floating freely in public market",
        "risk_quant_application": "Short interest % of float, illiquidity risk scoring",
    },
    {
        "endpoint": "Instruments",
        "container": "fundamental",
        "field": "revChangeYear",
        "data_type": "float",
        "description": "Year-over-year revenue growth percentage",
        "risk_quant_application": "Top-line revenue expansion factor screening",
    },
    {
        "endpoint": "Instruments",
        "container": "fundamental",
        "field": "operatingMarginTTM",
        "data_type": "float",
        "description": "Operating income divided by revenue (TTM)",
        "risk_quant_application": "Core operational profitability factor indexing",
    },
    # =========================================================================
    # 6. MOVERS ENDPOINT (/movers/{index_symbol})
    # =========================================================================
    {
        "endpoint": "Movers",
        "container": "screeners",
        "field": "symbol",
        "data_type": "str",
        "description": "Ticker symbol of the mover security",
        "risk_quant_application": "Tail-event universe selection, intraday breakout scanning",
    },
    {
        "endpoint": "Movers",
        "container": "screeners",
        "field": "lastPrice",
        "data_type": "float",
        "description": "Most recent execution print",
        "risk_quant_application": "Penny-stock filtering, minimum price constraint filters",
    },
    {
        "endpoint": "Movers",
        "container": "screeners",
        "field": "netChange",
        "data_type": "float",
        "description": "Absolute price change from baseline",
        "risk_quant_application": "Index point contribution attribution",
    },
    {
        "endpoint": "Movers",
        "container": "screeners",
        "field": "netPercentChange",
        "data_type": "float",
        "description": "Percentage price variation from baseline",
        "risk_quant_application": "Outlier detection, short-term cross-sectional reversal",
    },
    {
        "endpoint": "Movers",
        "container": "screeners",
        "field": "totalVolume",
        "data_type": "int",
        "description": "Cumulative shares traded in session",
        "risk_quant_application": "Volume-weighted momentum ranking, institutional liquidity",
    },
    {
        "endpoint": "Movers",
        "container": "screeners",
        "field": "marketShare",
        "data_type": "float",
        "description": "Share volume as percentage of total index or market volume",
        "risk_quant_application": "Market concentration risk, liquidity crowding analysis",
    },
    # =========================================================================
    # 7. MARKET HOURS ENDPOINT (/markets)
    # =========================================================================
    {
        "endpoint": "MarketHours",
        "container": "root",
        "field": "isOpen",
        "data_type": "bool",
        "description": "Live flag indicating if the specific market is trading",
        "risk_quant_application": "Algorithmic execution gate, trading pipeline activation",
    },
    {
        "endpoint": "MarketHours",
        "container": "sessionHours",
        "field": "preMarket",
        "data_type": "list [start, end]",
        "description": "ISO-8601 timestamps for pre-market trading window",
        "risk_quant_application": "Off-hours order routing, extended volatility ingestion",
    },
    {
        "endpoint": "MarketHours",
        "container": "sessionHours",
        "field": "regularMarket",
        "data_type": "list [start, end]",
        "description": "ISO-8601 timestamps for primary open auction and cash session",
        "risk_quant_application": "Active trading execution window, continuous trading bounds",
    },
    {
        "endpoint": "MarketHours",
        "container": "sessionHours",
        "field": "postMarket",
        "data_type": "list [start, end]",
        "description": "ISO-8601 timestamps for after-hours trading window",
        "risk_quant_application": "Post-market settlement, end-of-day batch reconciliation",
    },
]


class SchwabSchemaCatalog:
    """Institutional data dictionary manager for Schwab Market Data REST API schemas."""

    def __init__(self) -> None:
        self._df = pd.DataFrame(SCHEMA_REGISTRY)

    @property
    def catalog_df(self) -> pd.DataFrame:
        """Returns the complete schema catalog as a structured pandas DataFrame."""
        return self._df.copy()

    def list_endpoints(self) -> List[str]:
        """Returns a list of all distinct endpoint names documented in the catalog."""
        return sorted(self._df["endpoint"].unique().tolist())

    def get_endpoint_schema(self, endpoint_name: str) -> pd.DataFrame:
        """
        Retrieves the parameter dictionary for a specific endpoint family.
        Matching is case-insensitive.
        """
        clean_name = endpoint_name.strip().lower()
        mask = self._df["endpoint"].str.lower() == clean_name
        matched = self._df[mask]

        if matched.empty:
            valid = self.list_endpoints()
            raise ValueError(f"Endpoint '{endpoint_name}' not found. Valid choices: {valid}")

        return matched.copy().reset_index(drop=True)

    def search_parameters(self, query: str) -> pd.DataFrame:
        """
        Searches across field names, definitions, and quant applications for matching terms.
        """
        q = query.strip().lower()
        mask = (
            self._df["field"].str.lower().str.contains(q)
            | self._df["description"].str.lower().str.contains(q)
            | self._df["risk_quant_application"].str.lower().str.contains(q)
        )
        return self._df[mask].copy().reset_index(drop=True)

    def display(
        self,
        endpoint_name: Optional[str] = None,
        max_colwidth: int = 50,
    ) -> None:
        """
        Prints the catalog in a formatted tabular layout.
        If endpoint_name is omitted, prints all 7 endpoint schemas sequentially.
        """
        pd.set_option("display.max_rows", None)
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 1000)
        pd.set_option("display.max_colwidth", max_colwidth)

        endpoints = [endpoint_name] if endpoint_name else self.list_endpoints()

        for ep in endpoints:
            sub_df = self.get_endpoint_schema(ep)
            print("\n" + "=" * 115)
            print(f"SCHWAB REST API SCHEMA: {ep.upper()} ({len(sub_df)} Parameters Documented)")
            print("=" * 115)

            display_cols = ["container", "field", "data_type", "description", "risk_quant_application"]
            table_str = sub_df[display_cols].to_string(
                index=False,
                justify="left",
                header=["Container", "Field Name", "Type", "Semantic Meaning", "Institutional Quant / Risk Use"],
            )
            print(table_str)
            print("-" * 115)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Schwab Market Data API Full Schema Catalog & Reference Dictionary",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        choices=["Quotes", "PriceHistory", "OptionChains", "OptionExpirations", "Instruments", "Movers", "MarketHours"],
        help="Filter schema to a single endpoint family",
    )
    parser.add_argument(
        "--search",
        type=str,
        default=None,
        help="Search for a parameter or financial concept across all schemas",
    )
    parser.add_argument(
        "--export-csv",
        type=str,
        default=None,
        help="Export the entire schema data dictionary to a CSV file",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    catalog = SchwabSchemaCatalog()

    if args.export_csv:
        catalog.catalog_df.to_csv(args.export_csv, index=False)
        print(f"[OK] Full schema catalog ({len(catalog.catalog_df)} fields) exported to {args.export_csv}")
        return 0

    if args.search:
        results = catalog.search_parameters(args.search)
        print(f"\nSearch results for '{args.search}' ({len(results)} matches):")
        print(results[["endpoint", "container", "field", "data_type", "description"]].to_string(index=False))
        return 0

    catalog.display(endpoint_name=args.endpoint)
    return 0


if __name__ == "__main__":
    sys.exit(main())