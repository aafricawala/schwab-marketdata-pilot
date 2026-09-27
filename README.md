# Multi-Asset Risk Pipeline

Raw market-data layer for the multi-stage micro-agent pipeline.

This repository contains the raw-market-data layer of a multi-stage micro-agent
pipeline. It produces institution-grade, audit-tagged grounding payloads for
senior risk and strategy stakeholders at a tier-1 global multi-asset fund.

---

## Requirements

- **Python >= 3.9** (stdlib `zoneinfo` is used directly).
  If targeting 3.8, install `backports.zoneinfo`.
- Vendor SDK providing the duck-typed `client` interface (see `requirements.txt`).
- See `requirements.txt` for the full pinned dependency set.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Project layout

The raw-market-data layer is split into single-responsibility modules. The
original import surface is preserved by a **facade module**, so existing
callers do **not** need to change.

| Module | Responsibility |
|---|---|
| `schwab_raw_marketdata.py` | **Facade** — re-exports the public API. Import from here for backward compatibility. |
| `schwab_utils.py` | Shared helpers: `safe_div`, `safe_float`, `validate_symbol`. |
| `schwab_vendor_resilience.py` | `retry_vendor_call` decorator; `parse_client_response` envelope normalizer. |
| `schwab_market_session.py` | `extract_market_open_status` — vendor-first with local-clock fallback. |
| `schwab_grounding_schema.py` | `build_halted_grounding` — canonical synthetic payload for halted / unquoted instruments. |
| `schwab_instrument_classification.py` | Pure classifiers: warrant / mutual-fund / fund-type / structural-wrapper / ADR / foreign; quote-age bucketing; `functionally_zero`. |
| `schwab_fundamental_resolvers.py` | Pure resolvers: shares outstanding, PE/EPS, dividend, margin-sanity. |
| `schwab_short_locate.py` | `resolve_short_locate` — shortable / HTB / HTB-rate normalization. |
| `schwab_liquidity_book.py` | `resolve_liquidity` — bid/ask depth, volume, averages. |
| `schwab_underlying_grounding.py` | `extract_strict_underlying_data` orchestrator. |
| `schwab_price_history.py` | `extract_in_memory_price_history`. |
| `schwab_option_chain.py` | `extract_in_memory_option_expirations`, `resolve_optimal_expirations`, `extract_in_memory_option_chains`. |

### Import compatibility

Both of the following are equivalent and supported:

```python
# Legacy import surface (facade) — recommended for existing callers
from schwab_raw_marketdata import extract_strict_underlying_data

# Direct module import — recommended for new code
from schwab_underlying_grounding import extract_strict_underlying_data
```

Private helpers are also aliased in the facade for backward compatibility:
`_parse_client_response` and `_build_halted_grounding`.

---

## Usage

```python
from zoneinfo import ZoneInfo
from schwab_raw_marketdata import (
    extract_market_open_status,
    extract_strict_underlying_data,
    extract_in_memory_price_history,
    extract_in_memory_option_expirations,
    resolve_optimal_expirations,
    extract_in_memory_option_chains,
)

tz_et = ZoneInfo("America/New_York")

# 1. Market session state
is_open = extract_market_open_status(client)

# 2. Underlying grounding (phase_0 / step_1 / short_locate / liquidity)
grounding = extract_strict_underlying_data(client, "AAPL", tz_et)

# 3. Price history
candles = extract_in_memory_price_history(client, "AAPL", config={
    "HISTORICAL_PERIOD_TYPE": "year",
    "HISTORICAL_PERIOD": 1,
    "HISTORICAL_FREQUENCY_TYPE": "daily",
    "HISTORICAL_FREQUENCY": 1,
    "HISTORICAL_NEED_EXTENDED_HOURS": False,
})

# 4. Option surface
exps = extract_in_memory_option_expirations(client, "AAPL")
targets = resolve_optimal_expirations(exps)
vol_30d, underlying, contracts, telemetry = extract_in_memory_option_chains(
    client, "AAPL", targets, strike_window=14, strategy="SINGLE"
)
```

---

## Architecture notes

- **Resilience.** Every vendor call is wrapped by `retry_vendor_call` with
  exponential backoff. Non-retryable 4xx responses (and any status not in
  {429, 408} and < 500) short-circuit immediately.
- **Determinism & auditability.** Resolvers are pure functions of the vendor
  envelope. State strings (`*_state`, `*_basis`, `*_classification`,
  `*_warning`) are the audit surface consumed by downstream agents; they are
  emitted even when the underlying value is unavailable, so the payload shape
  is stable across instruments and market states.
- **Fault isolation.** Each module owns one responsibility; a failure in
  option-chain extraction cannot perturb underlying grounding.
- **Backward compatibility.** The facade re-exports the full public surface
  and aliases private helpers, so this refactor is drop-in.

---

## Refactor history

The market-data layer was split out of a single `schwab_raw_marketdata.py`
into the modules listed above. **No behavioral change** was intended: public
functions are byte-compatible. Payload **stability** is validated by
`schwab_refactor_payload_mock_test.py` (see below). That harness pins goldens
captured from the refactored implementation, so it detects drift going
forward; it does not, on its own, assert equivalence to the pre-refactor
monolith unless the goldens were regenerated against it before the refactor
landed.

---

## Testing

`schwab_refactor_payload_mock_test.py` is a stub-driven test (no
`unittest.mock`, no network) that pins payloads across a fixed fixture set
(equity, warrant, ETF, ADR, halted symbol, empty envelope, option expirations)
and asserts facade ↔ direct-module parity plus public-surface completeness. It
detects payload drift; it does not exercise the live vendor.

```bash
pytest -q schwab_refactor_payload_mock_test.py
```

---

## License

<PLACEHOLDER_LICENSE>          # e.g. "Proprietary. Internal use only."
