# Filename.py: schwab_schema_catalog.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

# Filename.py: schwab_schema_catalog.py
# Purpose: This module is part of the schwab integration and provides market data functionality.
# Prerequisites: None.
# What this module does:
# 1. Provide methods to support schwab data processing.
# Configuration knobs: None.
# Outputs: Various schwab datatypes and integration results.
# Notes: None.

"""
# Execute this line of logic to process the data
schwab_schema_catalog.py

"""

# Import specific components from a module
from __future__ import annotations

# Import the required external module
import argparse
# Import the required external module
import sys
# Import specific components from a module
from typing import Dict, List, Optional
# Import the required external module
import pandas as pd


# Assign a value or initialize a variable
SCHEMA_REGISTRY: List[Dict[str, str]] = [
    # =========================================================================
    # 1. QUOTES ENDPOINT (/quotes)
    # =========================================================================
    # --- quote sub-dictionary (Pricing & Real-Time Liquidity) ---
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "bidPrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Current highest buying price",
        # Execute this line of logic to process the data
        "risk_quant_application": "Bid-ask spread modeling, execution slippage calculation",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "askPrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Current lowest selling price",
        # Execute this line of logic to process the data
        "risk_quant_application": "Liquidity cost assessment, arrival price benchmarking",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "lastPrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Price at which the most recent trade cleared",
        # Execute this line of logic to process the data
        "risk_quant_application": "Mark-to-market portfolio valuation, intraday PnL",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "mark",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Midpoint between bid and ask (or last price within spread)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Illiquid security fair-value pricing, margin monitoring",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "bidSize",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Execute this line of logic to process the data
        "description": "Number of shares available at bid (in 100-share lots)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Market depth analysis, order book imbalance metrics",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "askSize",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Execute this line of logic to process the data
        "description": "Number of shares available at ask (in 100-share lots)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Immediate liquidity exhaustion modeling",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "totalVolume",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Execute this line of logic to process the data
        "description": "Aggregated share volume across regular and extended sessions",
        # Execute this line of logic to process the data
        "risk_quant_application": "Participation rate algorithms (VWAP/TWAP), liquidity screens",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "openPrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Regular session opening print",
        # Execute this line of logic to process the data
        "risk_quant_application": "Overnight gap risk calculation, intraday range expansion",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "highPrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Highest traded price in current regular session",
        # Execute this line of logic to process the data
        "risk_quant_application": "Intraday volatility modeling, Garman-Klass volatility",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "lowPrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Lowest traded price in current regular session",
        # Execute this line of logic to process the data
        "risk_quant_application": "Support breach detection, range-based variance estimators",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "closePrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Previous trading day official closing price",
        # Execute this line of logic to process the data
        "risk_quant_application": "Base price for daily return computation, VaR calculation",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "netChange",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Absolute price change from previous close",
        # Execute this line of logic to process the data
        "risk_quant_application": "Daily PnL attribution, momentum factor rankings",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "netPercentChange",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Percentage price change from previous close",
        # Execute this line of logic to process the data
        "risk_quant_application": "Relative cross-asset momentum ranking, breakout triggers",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "52WeekHigh",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Highest price achieved over rolling 52-week window",
        # Execute this line of logic to process the data
        "risk_quant_application": "52-week high momentum factor (George & Hwang model)",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "52WeekLow",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Lowest price achieved over rolling 52-week window",
        # Execute this line of logic to process the data
        "risk_quant_application": "Downside tail risk, mean-reversion screening",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "securityStatus",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "Trading state ('Normal', 'Halted', 'Closed')",
        # Execute this line of logic to process the data
        "risk_quant_application": "Circuit-breaker handling, operational kill-switch logic",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "bidMICId",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "Market Identifier Code (ISO 10383) for best bid venue",
        # Execute this line of logic to process the data
        "risk_quant_application": "Smart order routing (SOR) analysis, routing fragmentation",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "askMICId",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "Market Identifier Code (ISO 10383) for best ask venue",
        # Execute this line of logic to process the data
        "risk_quant_application": "Exchange fee optimization, maker-taker rebate capture",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "quote",
        # Execute this line of logic to process the data
        "field": "quoteTime",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Execute this line of logic to process the data
        "description": "Epoch timestamp in milliseconds of latest quote update",
        # Execute this line of logic to process the data
        "risk_quant_application": "Quote staleness checks, data latency SLA monitoring",
    # Execute this line of logic to process the data
    },
    # --- fundamental sub-dictionary (Accounting, Valuation & Risk Factors) ---
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "peRatio",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Trailing Price-to-Earnings ratio",
        # Execute this line of logic to process the data
        "risk_quant_application": "Value factor equity screening, style-box allocation",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "pegRatio",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Price/Earnings-to-Growth ratio",
        # Execute this line of logic to process the data
        "risk_quant_application": "GARP (Growth At Reasonable Price) quantitative strategy",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "pbRatio",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Price-to-Book value ratio",
        # Execute this line of logic to process the data
        "risk_quant_application": "Fama-French HML (High Minus Low) factor modeling",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "prRatio",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Price-to-Revenue (Sales) ratio",
        # Execute this line of logic to process the data
        "risk_quant_application": "Unprofitable growth company relative valuation",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "pcfRatio",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Price-to-Cash-Flow ratio",
        # Execute this line of logic to process the data
        "risk_quant_application": "Cash earnings quality screen, insolvency defense",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "beta",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Systematic market risk coefficient against S&P 500",
        # Execute this line of logic to process the data
        "risk_quant_application": "CAPM market sensitivity, portfolio beta-hedging weights",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "eps",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Diluted earnings per share (TTM)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Earnings surprises, fundamental factor indexing",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "divYield",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Annualized dividend yield percentage",
        # Execute this line of logic to process the data
        "risk_quant_application": "Carry trade strategies, dividend discount modeling",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "divAmount",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Dividend payout amount per share",
        # Execute this line of logic to process the data
        "risk_quant_application": "Cash flow matching, ex-dividend price drop adjustments",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "divFreq",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Assign a value or initialize a variable
        "description": "Dividend distribution frequency (1=Ann, 2=Semi, 4=Qtr, 12=Mth)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Cash flow scheduling, early option assignment risk",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "divDate",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "Ex-dividend date (YYYY-MM-DD)",
        # Execute this line of logic to process the data
        "risk_quant_application": "American call option early assignment arbitrage modeling",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "grossMarginTTM",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Gross profit margin percentage over trailing twelve months",
        # Execute this line of logic to process the data
        "risk_quant_application": "Quality factor scoring (Novy-Marx gross profitability)",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "netProfitMarginTTM",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Net profit margin percentage (TTM)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Operating leverage analysis, margin compression detection",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "returnOnEquity",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Return on common equity (ROE)",
        # Execute this line of logic to process the data
        "risk_quant_application": "DuPont framework decomposition, management efficiency",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "returnOnAssets",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Return on total assets (ROA)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Capital allocation efficiency, asset-heavy sector screens",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "quickRatio",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Acid-test liquidity ratio ((Cash + Receivables) / Current Liab)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Short-term credit risk, debt-distress screens",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "currentRatio",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Current Assets divided by Current Liabilities",
        # Execute this line of logic to process the data
        "risk_quant_application": "Working capital buffer, working capital stress testing",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "totalDebtToEquity",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Total debt liabilities divided by total shareholders equity",
        # Execute this line of logic to process the data
        "risk_quant_application": "Financial leverage risk, interest rate vulnerability",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "marketCap",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Total market capitalization in millions",
        # Execute this line of logic to process the data
        "risk_quant_application": "Size factor (SMB), institutional liquidity tier weighting",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "sharesOutstanding",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Total shares issued and outstanding",
        # Execute this line of logic to process the data
        "risk_quant_application": "Index weight rebalancing, dilution / buyback yield tracking",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "vol10DayAvg",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "10-day rolling average trading volume",
        # Execute this line of logic to process the data
        "risk_quant_application": "Short-term volume spike anomaly detection",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "vol3MonthAvg",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "90-day baseline average trading volume",
        # Execute this line of logic to process the data
        "risk_quant_application": "Baseline institutional capacity / position size limits",
    # Execute this line of logic to process the data
    },
    # --- reference sub-dictionary (Asset Master & Borrow Risk) ---
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "reference",
        # Execute this line of logic to process the data
        "field": "cusip",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "9-digit Committee on Uniform Securities Identification Procedures",
        # Execute this line of logic to process the data
        "risk_quant_application": "Security master deduplication, corporate action linking",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "reference",
        # Execute this line of logic to process the data
        "field": "exchangeName",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "Primary listing exchange name (e.g., 'NASDAQ', 'NYSE')",
        # Execute this line of logic to process the data
        "risk_quant_application": "Opening/closing auction routing, regulatory halt source",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "reference",
        # Execute this line of logic to process the data
        "field": "isShortable",
        # Execute this line of logic to process the data
        "data_type": "bool",
        # Execute this line of logic to process the data
        "description": "Brokerage flag indicating if security can be shorted",
        # Execute this line of logic to process the data
        "risk_quant_application": "Long/short equity execution feasibility gate",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "reference",
        # Execute this line of logic to process the data
        "field": "isHardToBorrow",
        # Execute this line of logic to process the data
        "data_type": "bool",
        # Execute this line of logic to process the data
        "description": "Flag indicating elevated borrow friction or locate deficits",
        # Execute this line of logic to process the data
        "risk_quant_application": "Short-squeeze risk indicator, special-rate locate tracking",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "reference",
        # Execute this line of logic to process the data
        "field": "htbRate",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Hard-to-borrow annualized borrow fee rate percentage",
        # Execute this line of logic to process the data
        "risk_quant_application": "Negative carry cost in short portfolios, conversion arbitrage",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "reference",
        # Execute this line of logic to process the data
        "field": "htbQuantity",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Execute this line of logic to process the data
        "description": "Available locate shares currently open in inventory",
        # Execute this line of logic to process the data
        "risk_quant_application": "Short capacity constraint checking, borrow depth sizing",
    # Execute this line of logic to process the data
    },
    # --- regular & extended sub-dictionaries (Session Isolation) ---
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "regular",
        # Execute this line of logic to process the data
        "field": "regularMarketLastPrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Last print recorded exclusively during standard session",
        # Execute this line of logic to process the data
        "risk_quant_application": "Official cash market benchmark, eliminating off-hour prints",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "regular",
        # Execute this line of logic to process the data
        "field": "regularMarketPercentChange",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Regular session percentage change",
        # Execute this line of logic to process the data
        "risk_quant_application": "Index tracking variance calculation",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Quotes",
        # Execute this line of logic to process the data
        "container": "extended",
        # Execute this line of logic to process the data
        "field": "extendedMarketLastPrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Latest trade print in pre-market or after-hours session",
        # Execute this line of logic to process the data
        "risk_quant_application": "Earnings release gap estimation, overnight risk exposure",
    # Execute this line of logic to process the data
    },
    # =========================================================================
    # 2. PRICE HISTORY ENDPOINT (/pricehistory)
    # =========================================================================
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "PriceHistory",
        # Execute this line of logic to process the data
        "container": "root",
        # Execute this line of logic to process the data
        "field": "symbol",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "Queried instrument ticker symbol",
        # Execute this line of logic to process the data
        "risk_quant_application": "Timeseries join validation, universe indexing",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "PriceHistory",
        # Execute this line of logic to process the data
        "container": "root",
        # Execute this line of logic to process the data
        "field": "empty",
        # Execute this line of logic to process the data
        "data_type": "bool",
        # Execute this line of logic to process the data
        "description": "Flag indicating whether no historical bars were returned",
        # Execute this line of logic to process the data
        "risk_quant_application": "Defensive exception branching, halts/new listing detection",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "PriceHistory",
        # Execute this line of logic to process the data
        "container": "root",
        # Execute this line of logic to process the data
        "field": "previousClose",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Reference previous trading session close",
        # Execute this line of logic to process the data
        "risk_quant_application": "First-candle return chaining, baseline shift calibration",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "PriceHistory",
        # Execute this line of logic to process the data
        "container": "candles",
        # Execute this line of logic to process the data
        "field": "datetime",
        # Execute this line of logic to process the data
        "data_type": "int (epoch ms)",
        # Execute this line of logic to process the data
        "description": "Candle open timestamp in milliseconds since Epoch UTC",
        # Execute this line of logic to process the data
        "risk_quant_application": "Temporal alignment, resampling, cross-sectional panel builds",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "PriceHistory",
        # Execute this line of logic to process the data
        "container": "candles",
        # Execute this line of logic to process the data
        "field": "open",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "First executed trade price within the bar window",
        # Execute this line of logic to process the data
        "risk_quant_application": "Bar-by-bar return calculation, opening range breakout strategies",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "PriceHistory",
        # Execute this line of logic to process the data
        "container": "candles",
        # Execute this line of logic to process the data
        "field": "high",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Peak trade print executed within the bar window",
        # Execute this line of logic to process the data
        "risk_quant_application": "Parkinson volatility, ATR (Average True Range), stop-loss checks",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "PriceHistory",
        # Execute this line of logic to process the data
        "container": "candles",
        # Execute this line of logic to process the data
        "field": "low",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Trough trade print executed within the bar window",
        # Execute this line of logic to process the data
        "risk_quant_application": "Maximum drawdown, intraday price variance bounds",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "PriceHistory",
        # Execute this line of logic to process the data
        "container": "candles",
        # Execute this line of logic to process the data
        "field": "close",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Final trade print executed within the bar window",
        # Execute this line of logic to process the data
        "risk_quant_application": "Continuous returns series, covariance matrix calibration",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "PriceHistory",
        # Execute this line of logic to process the data
        "container": "candles",
        # Execute this line of logic to process the data
        "field": "volume",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Execute this line of logic to process the data
        "description": "Total share units transacted during candle interval",
        # Execute this line of logic to process the data
        "risk_quant_application": "Volume profile, institutional accumulation/distribution",
    # Execute this line of logic to process the data
    },
    # =========================================================================
    # 3. OPTION CHAINS ENDPOINT (/chains)
    # =========================================================================
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "root",
        # Execute this line of logic to process the data
        "field": "underlyingPrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Live spot price of the underlying equity/ETF",
        # Execute this line of logic to process the data
        "risk_quant_application": "Moneyness benchmark (S/K), Black-Scholes spot input",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "root",
        # Execute this line of logic to process the data
        "field": "volatility",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Aggregated 30-day implied volatility across option chain",
        # Execute this line of logic to process the data
        "risk_quant_application": "VIX-style index replication, macro market fear indicator",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "root",
        # Execute this line of logic to process the data
        "field": "interestRate",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Risk-free rate assumed in pricing models",
        # Execute this line of logic to process the data
        "risk_quant_application": "Drift parameter in option pricing, cost-of-carry calibration",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "putCallIndicator",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "Contract derivative right ('CALL' or 'PUT')",
        # Execute this line of logic to process the data
        "risk_quant_application": "Put/Call ratio calculation, skew decomposition",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "strikePrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Exercise strike price",
        # Execute this line of logic to process the data
        "risk_quant_application": "Strike axis on volatility smile/surface, delta pinning",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "daysToExpiration",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Execute this line of logic to process the data
        "description": "Calendar days remaining until contract expiration (DTE)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Term-structure time-decay axis (tau), calendar spread pricing",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "bid / ask / mark",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Derivative contract market bid, ask, and synthetic midpoint",
        # Execute this line of logic to process the data
        "risk_quant_application": "Derivative execution cost, structured product valuations",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "totalVolume",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Execute this line of logic to process the data
        "description": "Aggregated contracts traded during current session",
        # Execute this line of logic to process the data
        "risk_quant_application": "Unusual options activity detection, institutional sweep alerts",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "openInterest",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Execute this line of logic to process the data
        "description": "Total outstanding unsettled contracts",
        # Execute this line of logic to process the data
        "risk_quant_application": "Gamma exposure (GEX) market maker positioning models",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "volatility",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Black-Scholes Implied Volatility (IV) percentage",
        # Execute this line of logic to process the data
        "risk_quant_application": "IV rank, IV percentile, SABR / SVI volatility surface fitting",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "delta",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "First-order price sensitivity (dV / dS)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Hedge ratio calculation, delta-neutral rebalancing, probability ITM",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "gamma",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Second-order price sensitivity (d^2V / dS^2)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Gamma squeeze modeling, market maker hedging acceleration",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "theta",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Time decay sensitivity (dV / dt) in points per day",
        # Execute this line of logic to process the data
        "risk_quant_application": "Net portfolio theta harvesting, premium decay optimization",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "vega",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Implied volatility sensitivity (dV / dsigma)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Vol-spike risk hedging, vega-weighted risk management",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "rho",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Interest rate sensitivity (dV / dr)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Long-dated LEAPS interest rate duration management",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "inTheMoney",
        # Execute this line of logic to process the data
        "data_type": "bool",
        # Execute this line of logic to process the data
        "description": "Flag indicating if strike has intrinsic value",
        # Execute this line of logic to process the data
        "risk_quant_application": "Assignment risk tracking, physical deliverable exposure",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionChains",
        # Execute this line of logic to process the data
        "container": "OptionContract",
        # Execute this line of logic to process the data
        "field": "theoreticalOptionValue",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Pricing model output fair value",
        # Execute this line of logic to process the data
        "risk_quant_application": "Relative mispricing discovery, statistical arbitrage",
    # Execute this line of logic to process the data
    },
    # =========================================================================
    # 4. OPTION EXPIRATIONS ENDPOINT (/expirationchain)
    # =========================================================================
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionExpirations",
        # Execute this line of logic to process the data
        "container": "expirationList",
        # Execute this line of logic to process the data
        "field": "expirationDate",
        # Execute this line of logic to process the data
        "data_type": "str (YYYY-MM-DD)",
        # Execute this line of logic to process the data
        "description": "Active contract settlement expiration date",
        # Execute this line of logic to process the data
        "risk_quant_application": "Expiration calendar scheduling, roll-schedule management",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionExpirations",
        # Execute this line of logic to process the data
        "container": "expirationList",
        # Execute this line of logic to process the data
        "field": "daysToExpiration",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Execute this line of logic to process the data
        "description": "Calendar days remaining until expiration",
        # Execute this line of logic to process the data
        "risk_quant_application": "Filtering target DTE tenors (e.g. 0-DTE, 30-DTE, 45-DTE)",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionExpirations",
        # Execute this line of logic to process the data
        "container": "expirationList",
        # Execute this line of logic to process the data
        "field": "expirationType",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Assign a value or initialize a variable
        "description": "Cycle frequency ('S'=Standard, 'W'=Weekly, 'Q'=Quarterly)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Liquidity concentration analysis (monthly vs. weekly cycles)",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "OptionExpirations",
        # Execute this line of logic to process the data
        "container": "expirationList",
        # Execute this line of logic to process the data
        "field": "settlementType",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Assign a value or initialize a variable
        "description": "Settlement timing ('A'=AM settled, 'P'=PM settled)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Overnight cash settlement risk vs. end-of-day market print",
    # Execute this line of logic to process the data
    },
    # =========================================================================
    # 5. INSTRUMENTS ENDPOINT (/instruments)
    # =========================================================================
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Instruments",
        # Execute this line of logic to process the data
        "container": "instruments",
        # Execute this line of logic to process the data
        "field": "cusip",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "Official 9-character CUSIP identifier",
        # Execute this line of logic to process the data
        "risk_quant_application": "Cross-platform reconciliation, symbology cross-walks",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Instruments",
        # Execute this line of logic to process the data
        "container": "instruments",
        # Execute this line of logic to process the data
        "field": "assetType",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "Asset class ('EQUITY', 'ETF', 'BOND', 'MUTUAL_FUND')",
        # Execute this line of logic to process the data
        "risk_quant_application": "Asset-allocation constraint verification, mandate compliance",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Instruments",
        # Execute this line of logic to process the data
        "container": "instruments",
        # Execute this line of logic to process the data
        "field": "description",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "Official legal name of the entity or fund",
        # Execute this line of logic to process the data
        "risk_quant_application": "Security master entity resolution, textual categorization",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Instruments",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "sharesFloat",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Total shares floating freely in public market",
        # Execute this line of logic to process the data
        "risk_quant_application": "Short interest % of float, illiquidity risk scoring",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Instruments",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "revChangeYear",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Year-over-year revenue growth percentage",
        # Execute this line of logic to process the data
        "risk_quant_application": "Top-line revenue expansion factor screening",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Instruments",
        # Execute this line of logic to process the data
        "container": "fundamental",
        # Execute this line of logic to process the data
        "field": "operatingMarginTTM",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Operating income divided by revenue (TTM)",
        # Execute this line of logic to process the data
        "risk_quant_application": "Core operational profitability factor indexing",
    # Execute this line of logic to process the data
    },
    # =========================================================================
    # 6. MOVERS ENDPOINT (/movers/{index_symbol})
    # =========================================================================
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Movers",
        # Execute this line of logic to process the data
        "container": "screeners",
        # Execute this line of logic to process the data
        "field": "symbol",
        # Execute this line of logic to process the data
        "data_type": "str",
        # Execute this line of logic to process the data
        "description": "Ticker symbol of the mover security",
        # Execute this line of logic to process the data
        "risk_quant_application": "Tail-event universe selection, intraday breakout scanning",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Movers",
        # Execute this line of logic to process the data
        "container": "screeners",
        # Execute this line of logic to process the data
        "field": "lastPrice",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Most recent execution print",
        # Execute this line of logic to process the data
        "risk_quant_application": "Penny-stock filtering, minimum price constraint filters",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Movers",
        # Execute this line of logic to process the data
        "container": "screeners",
        # Execute this line of logic to process the data
        "field": "netChange",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Absolute price change from baseline",
        # Execute this line of logic to process the data
        "risk_quant_application": "Index point contribution attribution",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Movers",
        # Execute this line of logic to process the data
        "container": "screeners",
        # Execute this line of logic to process the data
        "field": "netPercentChange",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Percentage price variation from baseline",
        # Execute this line of logic to process the data
        "risk_quant_application": "Outlier detection, short-term cross-sectional reversal",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Movers",
        # Execute this line of logic to process the data
        "container": "screeners",
        # Execute this line of logic to process the data
        "field": "totalVolume",
        # Execute this line of logic to process the data
        "data_type": "int",
        # Execute this line of logic to process the data
        "description": "Cumulative shares traded in session",
        # Execute this line of logic to process the data
        "risk_quant_application": "Volume-weighted momentum ranking, institutional liquidity",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "Movers",
        # Execute this line of logic to process the data
        "container": "screeners",
        # Execute this line of logic to process the data
        "field": "marketShare",
        # Execute this line of logic to process the data
        "data_type": "float",
        # Execute this line of logic to process the data
        "description": "Share volume as percentage of total index or market volume",
        # Execute this line of logic to process the data
        "risk_quant_application": "Market concentration risk, liquidity crowding analysis",
    # Execute this line of logic to process the data
    },
    # =========================================================================
    # 7. MARKET HOURS ENDPOINT (/markets)
    # =========================================================================
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "MarketHours",
        # Execute this line of logic to process the data
        "container": "root",
        # Execute this line of logic to process the data
        "field": "isOpen",
        # Execute this line of logic to process the data
        "data_type": "bool",
        # Execute this line of logic to process the data
        "description": "Live flag indicating if the specific market is trading",
        # Execute this line of logic to process the data
        "risk_quant_application": "Algorithmic execution gate, trading pipeline activation",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "MarketHours",
        # Execute this line of logic to process the data
        "container": "sessionHours",
        # Execute this line of logic to process the data
        "field": "preMarket",
        # Execute this line of logic to process the data
        "data_type": "list [start, end]",
        # Execute this line of logic to process the data
        "description": "ISO-8601 timestamps for pre-market trading window",
        # Execute this line of logic to process the data
        "risk_quant_application": "Off-hours order routing, extended volatility ingestion",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "MarketHours",
        # Execute this line of logic to process the data
        "container": "sessionHours",
        # Execute this line of logic to process the data
        "field": "regularMarket",
        # Execute this line of logic to process the data
        "data_type": "list [start, end]",
        # Execute this line of logic to process the data
        "description": "ISO-8601 timestamps for primary open auction and cash session",
        # Execute this line of logic to process the data
        "risk_quant_application": "Active trading execution window, continuous trading bounds",
    # Execute this line of logic to process the data
    },
    # Execute this line of logic to process the data
    {
        # Execute this line of logic to process the data
        "endpoint": "MarketHours",
        # Execute this line of logic to process the data
        "container": "sessionHours",
        # Execute this line of logic to process the data
        "field": "postMarket",
        # Execute this line of logic to process the data
        "data_type": "list [start, end]",
        # Execute this line of logic to process the data
        "description": "ISO-8601 timestamps for after-hours trading window",
        # Execute this line of logic to process the data
        "risk_quant_application": "Post-market settlement, end-of-day batch reconciliation",
    # Execute this line of logic to process the data
    },
# Execute this line of logic to process the data
]


# Define a new data structure or class
class SchwabSchemaCatalog:
    """Institutional data dictionary manager for Schwab Market Data REST API schemas."""

    # Define a new function or method
    def __init__(self) -> None:
        # Assign a value or initialize a variable
        self._df = pd.DataFrame(SCHEMA_REGISTRY)

    # Apply a decorator to modify function behavior
    @property
    # Define a new function or method
    def catalog_df(self) -> pd.DataFrame:
        """Returns the complete schema catalog as a structured pandas DataFrame."""
        # Return the final computed result to the caller
        return self._df.copy()

    # Define a new function or method
    def list_endpoints(self) -> List[str]:
        """Returns a list of all distinct endpoint names documented in the catalog."""
        # Return the final computed result to the caller
        return sorted(self._df["endpoint"].unique().tolist())

    # Define a new function or method
    def get_endpoint_schema(self, endpoint_name: str) -> pd.DataFrame:
        """
        # Execute this line of logic to process the data
        Retrieves the parameter dictionary for a specific endpoint family.
        # Execute this line of logic to process the data
        Matching is case-insensitive.
        """
        # Assign a value or initialize a variable
        clean_name = endpoint_name.strip().lower()
        # Assign a value or initialize a variable
        mask = self._df["endpoint"].str.lower() == clean_name
        # Assign a value or initialize a variable
        matched = self._df[mask]

        # Check a conditional statement
        if matched.empty:
            # Assign a value or initialize a variable
            valid = self.list_endpoints()
            # Raise an error to stop execution
            raise ValueError(f"Endpoint '{endpoint_name}' not found. Valid choices: {valid}")

        # Assign a value or initialize a variable
        return matched.copy().reset_index(drop=True)

    # Define a new function or method
    def search_parameters(self, query: str) -> pd.DataFrame:
        """
        # Execute this line of logic to process the data
        Searches across field names, definitions, and quant applications for matching terms.
        """
        # Assign a value or initialize a variable
        q = query.strip().lower()
        # Assign a value or initialize a variable
        mask = (
            # Execute this line of logic to process the data
            self._df["field"].str.lower().str.contains(q)
            # Execute this line of logic to process the data
            | self._df["description"].str.lower().str.contains(q)
            # Execute this line of logic to process the data
            | self._df["risk_quant_application"].str.lower().str.contains(q)
        # Execute this line of logic to process the data
        )
        # Assign a value or initialize a variable
        return self._df[mask].copy().reset_index(drop=True)

    # Define a new function or method
    def display(
        # Execute this line of logic to process the data
        self,
        # Assign a value or initialize a variable
        endpoint_name: Optional[str] = None,
        # Assign a value or initialize a variable
        max_colwidth: int = 50,
    # Execute this line of logic to process the data
    ) -> None:
        """
        # Execute this line of logic to process the data
        Prints the catalog in a formatted tabular layout.
        # Execute this line of logic to process the data
        If endpoint_name is omitted, prints all 7 endpoint schemas sequentially.
        """
        # Execute this line of logic to process the data
        pd.set_option("display.max_rows", None)
        # Execute this line of logic to process the data
        pd.set_option("display.max_columns", None)
        # Execute this line of logic to process the data
        pd.set_option("display.width", 1000)
        # Execute this line of logic to process the data
        pd.set_option("display.max_colwidth", max_colwidth)

        # Assign a value or initialize a variable
        endpoints = [endpoint_name] if endpoint_name else self.list_endpoints()

        # Start a loop over the given collection
        for ep in endpoints:
            # Assign a value or initialize a variable
            sub_df = self.get_endpoint_schema(ep)
            # Assign a value or initialize a variable
            print("\n" + "=" * 115)
            # Execute this line of logic to process the data
            print(f"SCHWAB REST API SCHEMA: {ep.upper()} ({len(sub_df)} Parameters Documented)")
            # Assign a value or initialize a variable
            print("=" * 115)

            # Assign a value or initialize a variable
            display_cols = ["container", "field", "data_type", "description", "risk_quant_application"]
            # Assign a value or initialize a variable
            table_str = sub_df[display_cols].to_string(
                # Assign a value or initialize a variable
                index=False,
                # Assign a value or initialize a variable
                justify="left",
                # Assign a value or initialize a variable
                header=["Container", "Field Name", "Type", "Semantic Meaning", "Institutional Quant / Risk Use"],
            # Execute this line of logic to process the data
            )
            # Execute this line of logic to process the data
            print(table_str)
            # Execute this line of logic to process the data
            print("-" * 115)


# Define a new function or method
def _build_arg_parser() -> argparse.ArgumentParser:
    # Assign a value or initialize a variable
    parser = argparse.ArgumentParser(
        # Assign a value or initialize a variable
        description="Schwab Market Data API Full Schema Catalog & Reference Dictionary",
        # Assign a value or initialize a variable
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    # Execute this line of logic to process the data
    )
    # Execute this line of logic to process the data
    parser.add_argument(
        # Execute this line of logic to process the data
        "--endpoint",
        # Assign a value or initialize a variable
        type=str,
        # Assign a value or initialize a variable
        default=None,
        # Assign a value or initialize a variable
        choices=["Quotes", "PriceHistory", "OptionChains", "OptionExpirations", "Instruments", "Movers", "MarketHours"],
        # Assign a value or initialize a variable
        help="Filter schema to a single endpoint family",
    # Execute this line of logic to process the data
    )
    # Execute this line of logic to process the data
    parser.add_argument(
        # Execute this line of logic to process the data
        "--search",
        # Assign a value or initialize a variable
        type=str,
        # Assign a value or initialize a variable
        default=None,
        # Assign a value or initialize a variable
        help="Search for a parameter or financial concept across all schemas",
    # Execute this line of logic to process the data
    )
    # Execute this line of logic to process the data
    parser.add_argument(
        # Execute this line of logic to process the data
        "--export-csv",
        # Assign a value or initialize a variable
        type=str,
        # Assign a value or initialize a variable
        default=None,
        # Assign a value or initialize a variable
        help="Export the entire schema data dictionary to a CSV file",
    # Execute this line of logic to process the data
    )
    # Return the final computed result to the caller
    return parser


# Define a new function or method
def main(argv: Optional[List[str]] = None) -> int:
    # Assign a value or initialize a variable
    parser = _build_arg_parser()
    # Assign a value or initialize a variable
    args = parser.parse_args(argv)

    # Assign a value or initialize a variable
    catalog = SchwabSchemaCatalog()

    # Check a conditional statement
    if args.export_csv:
        # Assign a value or initialize a variable
        catalog.catalog_df.to_csv(args.export_csv, index=False)
        # Execute this line of logic to process the data
        print(f"[OK] Full schema catalog ({len(catalog.catalog_df)} fields) exported to {args.export_csv}")
        # Return the final computed result to the caller
        return 0

    # Check a conditional statement
    if args.search:
        # Assign a value or initialize a variable
        results = catalog.search_parameters(args.search)
        # Execute this line of logic to process the data
        print(f"\nSearch results for '{args.search}' ({len(results)} matches):")
        # Assign a value or initialize a variable
        print(results[["endpoint", "container", "field", "data_type", "description"]].to_string(index=False))
        # Return the final computed result to the caller
        return 0

    # Assign a value or initialize a variable
    catalog.display(endpoint_name=args.endpoint)
    # Return the final computed result to the caller
    return 0


# Check a conditional statement
if __name__ == "__main__":
    # Execute this line of logic to process the data
    sys.exit(main())