"""
Day 18 — Handoff Retry Check.

When a case reaches Red tier, run_scoring()'s case_action already says
"rm_outreach_plus_hardship_handoff" — this module is what actually
ATTEMPTS that handoff to the downstream hardship/restructuring workflow
(the proposal's Red-tier integration point), with retry-then-escalate
behavior: a single failed handoff call shouldn't silently drop a
borrower who needs help.

_call_downstream_handoff() is a stub — swap it for a real HTTP call to
the downstream workflow's intake endpoint once that exists. Keeping it
as an injectable parameter (not hardcoded inside attempt_handoff()) is
what makes this testable without a real downstream service.
"""

import time

MAX_HANDOFF_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2.0


def _call_downstream_handoff(borrower_id: str, cycle: int) -> bool:
    """STUB — replace with a real call to the downstream hardship/
    restructuring workflow's intake endpoint. Should return True on a
    successful handoff, False on a failure worth retrying. Raise only
    for a genuinely unretryable error (e.g. borrower not found
    downstream) — this stub never raises, it just isn't implemented."""
    raise NotImplementedError(
        "No real downstream handoff endpoint wired up yet — pass a "
        "fake call_fn to attempt_handoff() for testing, or implement "
        "this function for real."
    )


def attempt_handoff(
    borrower_id: str,
    cycle: int,
    call_fn=_call_downstream_handoff,
    max_attempts: int = MAX_HANDOFF_ATTEMPTS,
    delay_seconds: float = RETRY_DELAY_SECONDS,
    sleep_fn=time.sleep,
) -> dict:
    """Returns {"status": "handoff_succeeded" | "handoff_failed_escalate",
    "attempts": N}. Retries on a False return from call_fn. Does NOT
    retry on an exception from call_fn — that's treated as unretryable
    and escalated immediately (attempts reflects how many tries actually
    ran, so 1 in that case)."""
    for attempt in range(1, max_attempts + 1):
        try:
            succeeded = call_fn(borrower_id, cycle)
        except Exception:
            return {"status": "handoff_failed_escalate", "attempts": attempt}

        if succeeded:
            return {"status": "handoff_succeeded", "attempts": attempt}

        if attempt < max_attempts:
            sleep_fn(delay_seconds)

    return {"status": "handoff_failed_escalate", "attempts": max_attempts}


if __name__ == "__main__":
    attempts_log = []

    def fake_fails_then_succeeds(borrower_id, cycle):
        attempts_log.append(1)
        return len(attempts_log) >= 2  # fails attempt 1, succeeds attempt 2

    def fake_always_fails(borrower_id, cycle):
        return False

    def fake_raises(borrower_id, cycle):
        raise ConnectionError("downstream unreachable")

    r1 = attempt_handoff("MSME-X", 3, call_fn=fake_fails_then_succeeds, sleep_fn=lambda s: None)
    print("fails then succeeds:", r1)
    assert r1 == {"status": "handoff_succeeded", "attempts": 2}

    r2 = attempt_handoff("MSME-X", 3, call_fn=fake_always_fails, sleep_fn=lambda s: None)
    print("always fails:", r2)
    assert r2 == {"status": "handoff_failed_escalate", "attempts": MAX_HANDOFF_ATTEMPTS}

    r3 = attempt_handoff("MSME-X", 3, call_fn=fake_raises, sleep_fn=lambda s: None)
    print("raises immediately:", r3)
    assert r3 == {"status": "handoff_failed_escalate", "attempts": 1}

    print("Handoff retry smoke test passed.")