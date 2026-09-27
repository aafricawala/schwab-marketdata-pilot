#!/usr/bin/env python3
"""
scaffold_docs.py

Create (or, with --force, overwrite) README.md and requirements.txt for the
schwab_* refactored project.

Design principles
-----------------
- NO GUESSING. Every fact the code cannot know (vendor SDK, Python floor,
  pandas usage, project name, license) is an explicit CLI argument. If an
  argument is omitted, the literal string <PLACEHOLDER> is written instead,
  and the script prints a checklist of what remains to be filled in.
- NO SILENT CLOBBER. Refuses to overwrite a non-empty file unless --force.
- IDEMPOTENT BY REFUSAL, NOT BY REWRITE. It will not try to "merge" into an
  existing file; that is how docs rot. Run it once, then edit by hand.

Usage
-----
    python scaffold_docs.py \
        --project-name "Multi-Asset Risk Pipeline" \
        --description "Raw market-data layer for the micro-agent pipeline." \
        --python-floor 3.9 \
        --vendor-sdk "schwab-py==1.4.0" \
        --pandas "keep" \
        --pandas-pin "pandas>=2.0,<3.0" \
        --license "Proprietary. Internal use only." \
        --test-framework "pytest>=7.4"

Any flag you omit is written as <PLACEHOLDER> and listed at the end.

Flags:
  --target-dir DIR       Where to write (default: cwd)
  --force                Overwrite non-empty files
  --pandas {keep,drop}   Whether pandas is a real project dependency
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PLACEHOLDER = "<PLACEHOLDER>"

REQUIREMENTS_TEMPLATE = """\
# ─────────────────────────────────────────────────────────────────────────────
# Runtime dependencies
# ─────────────────────────────────────────────────────────────────────────────

# Python runtime
# Required: >= {python_floor}  (stdlib `zoneinfo` is used by schwab_market_session,
#                              schwab_grounding_schema, schwab_underlying_grounding)
# If the project must target 3.8, uncomment the backport below.
# backports.zoneinfo; python_version < "3.9"

# Vendor SDK — duck-typed in code as `client` (never imported by name).
# The refactored schwab_* modules call, on `client`:
#   get_market_hours, get_quote, get_price_history,
#   get_option_chain, get_option_expirations | get_option_expiration_chain
{vendor_block}

{data_block}

# ─────────────────────────────────────────────────────────────────────────────
# Development / test dependencies  (consider moving to requirements-dev.txt)
# ─────────────────────────────────────────────────────────────────────────────

{test_block}
"""

README_TEMPLATE = """\
# {project_name}

{description}

This repository contains the raw-market-data layer of a multi-stage micro-agent
pipeline. It produces institution-grade, audit-tagged grounding payloads for
senior risk and strategy stakeholders at a tier-1 global multi-asset fund.

---

## Requirements

- **Python >= {python_floor}** (stdlib `zoneinfo` is used directly).
  If targeting 3.8, install `backports.zoneinfo`.
- Vendor SDK providing the duck-typed `client` interface (see `requirements.txt`).
- See `requirements.txt` for the full pinned dependency set.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt