"""
schwab_refactor_payload_mock_test.py

Payload-stability harness for the schwab_* refactor.

What this is
------------
A stub-driven test (NOT unittest.mock). The vendor `client` is a hand-rolled
duck-typed double (`FakeClient` / `FakeResponse`), so this file exercises no
network path and no real vendor. It asserts that the current implementation
produces payloads byte-identical to previously captured golden payloads.

What this proves
----------------
  - Payload stability across a fixed fixture set (equity, warrant, ETF, ADR,
    halted, empty envelope, option expirations).
  - Facade <-> direct-module parity (re-exports are the same object).
  - Public surface completeness, including the two legacy `_` aliases.

What this does NOT prove
------------------------
  - That the goldens equal true PRE-REFACTOR output. The goldens were captured
    from the current (refactored) implementation on first run. This harness
    proves STABILITY, not historical EQUIVALENCE, unless you regenerated the
    goldens against the pre-refactor monolith before overwriting it.

If you change vendor-envelope semantics intentionally, regenerate the goldens:
    REGENERATE=1 pytest -q schwab_refactor_payload_mock_test.py
Do NOT regenerate to "make tests pass" after an unintended change -- that
defeats the purpose of the harness.

Run
---
    pytest -q schwab_refactor_payload_mock_test.py
    REGENERATE=1 pytest -q schwab_refactor_payload_mock_test.py   # refresh goldens
"""