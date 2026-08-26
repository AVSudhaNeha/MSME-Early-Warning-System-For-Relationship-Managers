"""
Day 29 — Verify the cached-fallback path end-to-end, with the AA sandbox
intentionally disconnected.

Day 13 built and unit-tested apply_cached_fallback() in isolation (see
gates.py's own __main__ block and Day 27's harness). This script proves
the SAME thing at the level the proposal actually asks for: "tested
explicitly by disconnecting the sandbox and confirming graceful
degradation, not a crash" — meaning through the real entry point
(engine.run_scoring()), with the real collectors, not by calling
apply_cached_fallback() directly with hand-built inputs.

Simulates a disconnected sandbox by monkeypatching get_aa_client() (as
imported into cashflow_collector.py / vendor_collector.py) to always
raise AAConnectionError — same exception LiveAAClient raises for a real
Setu failure, so this is a faithful stand-in for an actual outage, not a
different failure mode.
"""

from unittest.mock import patch

from app.clients.aa_client_base import AAConnectionError
from app.scoring.engine import run_scoring
from app.scoring.gates import reset_case_state
from app.case_lifecycle import reset_case_record

FAILURES = []


def _check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


class _DisconnectedAAClient:
    def fetch_aa_data(self, borrower_id, cycle):
        raise AAConnectionError("SIMULATED: AA sandbox intentionally disconnected for this test")


def verify_disconnect_scenario():
    test_borrower = "MSME-DISCONNECT-TEST"
    reset_case_state(test_borrower)
    reset_case_record(test_borrower)

    with patch("app.collectors.cashflow_collector.get_aa_client", return_value=_DisconnectedAAClient()), \
         patch("app.collectors.vendor_collector.get_aa_client", return_value=_DisconnectedAAClient()):

        # Cycle 1: sandbox already down on the very FIRST cycle for this
        # borrower — no cache exists yet, so this MUST show genuinely
        # unavailable, not crash, not fake data.
        result1 = run_scoring(test_borrower, 1)
        _check(
            "Cycle 1 (no cache yet) does not crash on a cold-start outage",
            result1 is not None,
        )
        _check(
            "Cycle 1 correctly reports cash_flow/vendor_payment as unavailable (nothing to cache from)",
            result1["signal_sources"]["cash_flow"] == "unavailable"
            and result1["signal_sources"]["vendor_payment"] == "unavailable",
            detail=str(result1["signal_sources"]),
        )

    # Now simulate the sandbox coming back up briefly to seed a real
    # cache, then going down again — the realistic "outage" scenario.
    # Uses a real archetype borrower (MSME-1001) here, not a made-up ID —
    # the mock AA client only has scripted data for known archetype
    # borrowers, so a made-up borrower_id would fail in mock mode too,
    # which would test the wrong thing (missing test data, not the
    # cached-fallback path). Resets this borrower's state before and
    # after so it doesn't leak into a later golden-eval run.
    seed_borrower = "MSME-1001"
    reset_case_state(seed_borrower)
    reset_case_record(seed_borrower)

    result_seed = run_scoring(seed_borrower, 1)  # real mock client, sandbox "up"
    _check(
        "Seed cycle (sandbox up) produces fresh signals",
        result_seed["signal_sources"]["cash_flow"] == "fresh",
        detail=str(result_seed["signal_sources"]),
    )

    with patch("app.collectors.cashflow_collector.get_aa_client", return_value=_DisconnectedAAClient()), \
         patch("app.collectors.vendor_collector.get_aa_client", return_value=_DisconnectedAAClient()):

        result2 = run_scoring(seed_borrower, 2)  # sandbox down THIS cycle
        _check(
            "Cycle 2 (outage, cache exists) substitutes cached values instead of failing",
            result2["signal_sources"]["cash_flow"] == "cached_fallback",
            detail=str(result2["signal_sources"]),
        )
        _check(
            "Cycle 2 still produces a real tier despite the outage (graceful degradation, not insufficient)",
            result2["tier"] is not None,
            detail=f"tier={result2['tier']}",
        )

    reset_case_state(seed_borrower)
    reset_case_record(seed_borrower)


if __name__ == "__main__":
    verify_disconnect_scenario()
    print(f"\n{5 - len(FAILURES)}/5 disconnect-scenario checks passed.")
    if FAILURES:
        print("FAILED:", FAILURES)
    else:
        print("Sandbox-disconnect verification passed — degrades gracefully, does not crash.")