"""
Day 27 — Full eval harness.

Runs TWO layers of verification:

1. Existing golden-trace evaluator
   - 9 archetypes
   - 30 cycles
   - tier/composite/gate comparison

2. Operational-hardening checks added across Days 9-25.

Seven hardening FEATURE AREAS are covered, with eight explicit
assertions because peer adjustment has two separate checks:

    1. Data Availability Check
    2. Critical-floor override
    3. Peer-size fallback
    4. Duplicate-case prevention
    5. Scheduler idempotency
    6. Cached-fallback recovery
    7. SLA Timeout Check
    8. Handoff Retry Check

IMPORTANT:
The golden evaluator reports comparison/drift information separately.
The hardening assertions below determine whether the operational
hardening layer passes or fails.

This script exits with a non-zero status if any hardening assertion
fails. That allows Day 28's full regression runner to detect failures
reliably using subprocess.returncode instead of parsing printed text.
"""

from app.scoring.evaluator import run_golden_evaluation

from app.scoring.gates import (
    reset_case_state,
    apply_cached_fallback,
)

from app.case_lifecycle import (
    reset_case_record,
    get_or_create_case,
)

from app.scoring.peer_adjustment import (
    attribute_change,
    _peek_composite,
)

from app.sla_check import check_sla
from app.handoff_retry import attempt_handoff
from app.scoring.composite import calculate_composite


# ============================================================
# GLOBAL TEST STATE
# ============================================================

FAILURES = []

TOTAL_HARDENING_ASSERTIONS = 8


# ============================================================
# GENERIC CHECK HELPER
# ============================================================

def _check(label: str, condition: bool, detail: str = "") -> None:
    """
    Record and print one hardening assertion.

    Failed assertions are collected in FAILURES so the complete suite
    can continue running instead of stopping after the first failure.
    """

    status = "PASS" if condition else "FAIL"

    print(
        f"[{status}] {label}"
        + (f" — {detail}" if detail and not condition else "")
    )

    if not condition:
        FAILURES.append(label)


# ============================================================
# CHECK 1 — DATA AVAILABILITY
# ============================================================

def check_data_availability():
    """
    Fewer than MIN_SIGNALS_REQUIRED real signals must result in an
    insufficient-data composite (None).

    Industry is currently a placeholder while
    INDUSTRY_INDEX_MOCK_MODE=true, so it does not count as real
    availability evidence.
    """

    composite = calculate_composite(
        {
            "gst_filing_delay": None,
            "cash_flow": 80,
            "vendor_payment": None,
            "industry_index": None,
        }
    )

    _check(
        "Data Availability Check "
        "(1 real signal < MIN_SIGNALS_REQUIRED)",
        composite is None,
        detail=f"composite={composite}",
    )


# ============================================================
# CHECKS 2 + 3 — PEER ADJUSTMENT
# ============================================================

def check_peer_fallback_and_critical_floor():
    """
    Verify both important peer-adjustment safeguards:

    A. Critical-floor override:
       Extremely poor borrower performance cannot be rescued by
       peer-relative attribution.

    B. Peer-size fallback:
       When there are not enough valid peers, the system falls back to
       borrower-specific attribution rather than pretending a reliable
       peer comparison exists.
    """

    # --------------------------------------------------------
    # Critical-floor override
    # --------------------------------------------------------

    curr = _peek_composite("MSME-1004", 3)
    prev = _peek_composite("MSME-1004", 2)

    result = attribute_change(
        "MSME-1004",
        3,
        curr,
        prev,
    )

    _check(
        "Critical floor override always wins over peer attribution",
        result["attribution"] == "critical_floor_override",
        detail=str(result),
    )

    # --------------------------------------------------------
    # Peer-size fallback
    # --------------------------------------------------------

    curr2 = _peek_composite("MSME-1003", 5)
    prev2 = _peek_composite("MSME-1003", 4)

    result2 = attribute_change(
        "MSME-1003",
        5,
        curr2,
        prev2,
    )

    _check(
        "Peer-size fallback engages when too few peers have valid data",
        (
            result2["peer_avg_delta"] is None
            and result2["attribution"] == "borrower_specific"
        ),
        detail=str(result2),
    )


# ============================================================
# CHECK 4 — DUPLICATE CASE PREVENTION
# ============================================================

def check_duplicate_case_prevention():
    """
    Re-running case creation for the same borrower/cycle must not create
    a second case.
    """

    test_borrower = "MSME-HARNESS-DUPTEST"

    reset_case_record(test_borrower)

    try:
        c1 = get_or_create_case(
            test_borrower,
            1,
            "Amber",
        )

        c2 = get_or_create_case(
            test_borrower,
            1,
            "Amber",
        )

        _check(
            "Duplicate-case prevention "
            "(same cycle re-call doesn't open a 2nd case)",
            c1["case_id"] == c2["case_id"],
            detail=f"{c1['case_id']} vs {c2['case_id']}",
        )

    finally:
        reset_case_record(test_borrower)


# ============================================================
# CHECK 5 — SCHEDULER IDEMPOTENCY
# ============================================================

def check_scheduler_idempotency():
    """
    A borrower/cycle lock that is already held must reject a second
    acquire attempt.
    """

    from app.scoring.gates import (
        acquire_lock,
        release_lock,
    )

    test_borrower = "MSME-HARNESS-LOCKTEST"

    reset_case_state(test_borrower)

    try:
        first_acquire = acquire_lock(
            test_borrower,
            1,
        )

        second_acquire = acquire_lock(
            test_borrower,
            1,
        )

        _check(
            "Scheduler idempotency "
            "(second acquire while held is rejected)",
            first_acquire is True and second_acquire is False,
            detail=(
                f"first_acquire={first_acquire}, "
                f"second_acquire={second_acquire}"
            ),
        )

    finally:
        release_lock(test_borrower)
        reset_case_state(test_borrower)


# ============================================================
# CHECK 6 — CACHED FALLBACK
# ============================================================

def check_cached_fallback():
    """
    Verify that a temporary source outage uses the last-known-good
    cached signal instead of immediately treating the signal as missing.

    update_gate() must run after cycle 1 because that is what persists
    the last-known-good value used by the fallback mechanism.
    """

    from app.scoring.gates import update_gate

    test_borrower = "MSME-HARNESS-CACHETEST"

    reset_case_state(test_borrower)

    try:

        # ----------------------------------------------------
        # Cycle 1 — all fresh
        # ----------------------------------------------------

        resolved1, sources1 = apply_cached_fallback(
            test_borrower,
            {
                "gst_filing_delay": 80,
                "cash_flow": 78,
                "vendor_payment": 82,
                "industry_index": 50,
            },
            {
                "gst_filing_delay": None,
                "cash_flow": None,
                "vendor_payment": None,
                "industry_index": None,
            },
        )

        # Persist last-known-good signal values.
        update_gate(
            test_borrower,
            resolved1,
        )

        # ----------------------------------------------------
        # Cycle 2 — cash-flow source outage
        # ----------------------------------------------------

        resolved2, sources2 = apply_cached_fallback(
            test_borrower,
            {
                "gst_filing_delay": 81,
                "cash_flow": None,
                "vendor_payment": 83,
                "industry_index": 50,
            },
            {
                "gst_filing_delay": None,
                "cash_flow": "connection_outage",
                "vendor_payment": None,
                "industry_index": None,
            },
        )

        _check(
            "Cached-fallback substitutes a stale reading during an outage",
            (
                sources2["cash_flow"] == "cached_fallback"
                and resolved2["cash_flow"] == 78
            ),
            detail=(
                f"sources={sources2}, "
                f"resolved_cash_flow={resolved2['cash_flow']}"
            ),
        )

    finally:
        reset_case_state(test_borrower)


# ============================================================
# CHECK 7 — SLA TIMEOUT
# ============================================================

def check_sla_timeout():
    """
    A continuously open case must breach the SLA after exceeding
    SLA_CYCLES_LIMIT.
    """

    test_borrower = "MSME-HARNESS-SLATEST"

    reset_case_record(test_borrower)

    try:

        get_or_create_case(
            test_borrower,
            1,
            "Amber",
        )

        get_or_create_case(
            test_borrower,
            2,
            "Amber",
        )

        get_or_create_case(
            test_borrower,
            3,
            "Amber",
        )

        get_or_create_case(
            test_borrower,
            4,
            "Amber",
        )

        result = check_sla(
            test_borrower,
            4,
        )

        _check(
            "SLA Timeout Check breaches after "
            "SLA_CYCLES_LIMIT cycles open",
            result["sla_breached"] is True,
            detail=str(result),
        )

    finally:
        reset_case_record(test_borrower)


# ============================================================
# CHECK 8 — HANDOFF RETRY
# ============================================================

def check_handoff_retry():
    """
    If every downstream hardship-handoff attempt fails, the retry
    mechanism must eventually return handoff_failed_escalate.
    """

    def always_fails(borrower_id, cycle):
        return False

    result = attempt_handoff(
        "MSME-HARNESS-HANDOFFTEST",
        1,
        call_fn=always_fails,

        # Don't actually sleep during tests.
        sleep_fn=lambda seconds: None,
    )

    _check(
        "Handoff Retry Check escalates after exhausting retries",
        (
            result["status"] == "handoff_failed_escalate"
            and result["attempts"] == 3
        ),
        detail=str(result),
    )


# ============================================================
# FULL HARNESS
# ============================================================

def run_full_harness():
    """
    Run the complete Day 27 evaluation harness.

    Returns True when every operational-hardening assertion passes,
    otherwise False.

    Golden-trace comparison is still printed by
    run_golden_evaluation(). Its tier/composite/gate comparison output
    remains useful diagnostic information.

    Operational hardening uses explicit PASS/FAIL assertions below.
    """

    # Important if this function is invoked multiple times in the same
    # Python interpreter.
    FAILURES.clear()

    # --------------------------------------------------------
    # LAYER 1 — GOLDEN TRACE
    # --------------------------------------------------------

    print("=== Layer 1: golden-trace evaluator ===")

    run_golden_evaluation()

    # --------------------------------------------------------
    # LAYER 2 — HARDENING
    # --------------------------------------------------------

    print("\n=== Layer 2: operational-hardening checks ===")

    check_data_availability()

    check_peer_fallback_and_critical_floor()

    check_duplicate_case_prevention()

    check_scheduler_idempotency()

    check_cached_fallback()

    check_sla_timeout()

    check_handoff_retry()

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    passed = TOTAL_HARDENING_ASSERTIONS - len(FAILURES)

    print(
        f"\n{passed}/{TOTAL_HARDENING_ASSERTIONS} "
        "hardening assertions passed."
    )

    if FAILURES:

        print("FAILED:")

        for failure in FAILURES:
            print(f" - {failure}")

        return False

    print("All hardening assertions passed.")

    return True


# ============================================================
# COMMAND-LINE ENTRY POINT
# ============================================================

if __name__ == "__main__":

    success = run_full_harness()

    # Day 28's subprocess runner can now reliably inspect returncode.
    if not success:
        raise SystemExit(1)

    raise SystemExit(0)