"""
Day 12 — Scheduler idempotency.

Simulates the scheduled trigger described in §8: "fires per borrower on a
fixed cadence; checks a running-flag first so a slow prior cycle can't be
double-triggered." trigger_cycle() is what a real cron/scheduler would
call — it wraps run_scoring() with the cycle_lock acquire/release added
to gates.py.

The lock is released in a `finally` block specifically so a cycle that
raises partway through (a real bug, a collector outage that somehow isn't
caught, etc.) can never leave a borrower permanently locked out of future
triggers — that would be worse than the duplicate-run problem this is
meant to prevent.
"""

from app.scoring.gates import acquire_lock, release_lock
from app.scoring.engine import run_scoring


def trigger_cycle(borrower_id: str, cycle: int) -> dict:
    if not acquire_lock(borrower_id, cycle):
        return {
            "status": "skipped_already_running",
            "borrower_id": borrower_id,
            "cycle": cycle,
            "result": None,
        }

    try:
        result = run_scoring(borrower_id, cycle)
        return {"status": "completed", "borrower_id": borrower_id, "cycle": cycle, "result": result}
    finally:
        release_lock(borrower_id)


if __name__ == "__main__":
    from app.scoring.gates import reset_case_state

    test_borrower = "MSME-1001-LOCK-TEST"
    reset_case_state(test_borrower)

    # 1. Normal case — trigger completes cleanly, lock released after.
    r1 = trigger_cycle(test_borrower, 1)
    print("Trigger 1 (normal):              ", r1["status"])

    # 2. Simulate a slow-running prior cycle: manually acquire the lock,
    #    then try to trigger again before it's released -> should skip.
    acquire_lock(test_borrower, 2)
    r2 = trigger_cycle(test_borrower, 2)
    print("Trigger 2 (lock already held):   ", r2["status"])

    # 3. Release manually (simulating the slow cycle finally finishing),
    #    then retry -> should now complete.
    release_lock(test_borrower)
    r3 = trigger_cycle(test_borrower, 2)
    print("Trigger 3 (after release):       ", r3["status"])

    # 4. Confirm a failure mid-cycle still releases the lock (finally
    #    block). A nonexistent borrower_id does NOT actually raise here —
    #    the collectors catch that gracefully and just return insufficient
    #    data (confirmed by testing) — so force a REAL exception instead,
    #    via mock.patch, to prove the finally block actually works.
    from unittest.mock import patch

    reset_case_state("MSME-1001")
    try:
        with patch("app.scheduler.run_scoring", side_effect=RuntimeError("simulated crash mid-cycle")):
            trigger_cycle("MSME-1001", 1)
    except RuntimeError:
        pass
    still_locked_after_crash = not acquire_lock("MSME-1001", 1)
    print("Trigger 4 (lock still held after a real crash?):", still_locked_after_crash, "(should be False)")
    reset_case_state("MSME-1001")

    reset_case_state(test_borrower)