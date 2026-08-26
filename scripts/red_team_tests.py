"""
Day 27 — Red-team tests.

Two adversarial scenarios named explicitly in the proposal's risk
register, tested as actual attack attempts rather than trusted to "just
work" because the defensive code exists:

  1. Model-extraction via repeated what-if probing — attacker rapidly
     calls simulate_scenario with narrowing hypothetical values, trying
     to binary-search the exact CRITICAL_FLOOR/AMBER_MIN/GREEN_MIN
     thresholds. Should get rate-limited by whatif_abuse_check.py well
     before enough probes succeed to narrow anything down.

  2. Duplicate-case race via concurrent-looking scheduler triggers —
     attacker (or just a retry-happy client) fires the same cycle twice
     in quick succession, trying to get two cases opened or two
     scoring runs to interleave. Should be rejected by the cycle_lock,
     not silently double-processed.
"""

from app.scoring.gates import reset_case_state
from app.case_lifecycle import reset_case_record
from app.query.whatif_abuse_check import check_whatif_rate_limit, reset_whatif_log, WHATIF_LIMIT_PER_WINDOW
from app.scheduler import trigger_cycle

FAILURES = []


def _check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def red_team_whatif_boundary_probing():
    """Simulates an attacker firing WHATIF_LIMIT_PER_WINDOW + several
    more probes in a tight loop, trying to binary-search a threshold.
    Success for the DEFENSE means the attacker gets blocked partway
    through, not that every probe silently succeeds."""
    reset_whatif_log()
    attacker_user = "ATTACKER"
    target_borrower = "MSME-1003"

    probe_count = WHATIF_LIMIT_PER_WINDOW + 10
    blocked_at = None
    for i in range(probe_count):
        result = check_whatif_rate_limit(target_borrower, user_id=attacker_user, now=1_700_000_000 + i)
        if result["blocked"]:
            blocked_at = i + 1
            break

    _check(
        f"Boundary-probing attacker is rate-limited before exhausting {probe_count} probes",
        blocked_at is not None and blocked_at <= WHATIF_LIMIT_PER_WINDOW + 1,
        detail=f"blocked_at={blocked_at}",
    )
    reset_whatif_log()


def red_team_duplicate_case_race():
    """Simulates two near-simultaneous trigger_cycle() calls for the SAME
    borrower+cycle — the closest thing to a race condition testable
    without actual threading. The second call must be rejected by the
    lock, not run a second scoring pass."""
    test_borrower = "MSME-REDTEAM-RACE"
    reset_case_state(test_borrower)
    reset_case_record(test_borrower)

    from app.scoring.gates import acquire_lock

    # Manually hold the lock to simulate "cycle 1 is already mid-run"
    # (the real race scheduler.py's own __main__ test already covers via
    # acquire_lock directly — this test additionally confirms
    # trigger_cycle() itself, the actual public entry point, respects it).
    acquire_lock(test_borrower, 1)
    result = trigger_cycle(test_borrower, 1)
    _check(
        "Second trigger for a locked cycle is rejected, not double-run",
        result["status"] == "skipped_already_running",
        detail=str(result),
    )

    from app.scoring.gates import release_lock

    release_lock(test_borrower)
    reset_case_state(test_borrower)
    reset_case_record(test_borrower)


def run_red_team_suite():
    print("=== Red-team: what-if boundary probing ===")
    red_team_whatif_boundary_probing()
    print("\n=== Red-team: duplicate-case race ===")
    red_team_duplicate_case_race()

    print(f"\n{2 - len(FAILURES)}/2 red-team tests passed.")
    if FAILURES:
        print("FAILED:", FAILURES)
    else:
        print("All red-team tests passed.")


if __name__ == "__main__":
    run_red_team_suite()