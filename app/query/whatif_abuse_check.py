"""
Day 25 — What-If Abuse Check.

Mitigates the risk named explicitly in the proposal's risk register:
"Model extraction of exact scoring thresholds via repeated what-if
probing." Someone could binary-search the CRITICAL_FLOOR/GREEN_MIN/
AMBER_MIN thresholds by running simulate_scenario() repeatedly with
narrowing hypothetical values. This tracks how many what-if calls a
(user, borrower) pair has made in a rolling time window and blocks
further calls once that exceeds WHATIF_LIMIT_PER_WINDOW — "rate-limit/
flag", per the proposal, not a permanent ban.

State is per (user_id, borrower_id) pair, not just per borrower, so one
RM probing aggressively doesn't block a different RM's legitimate access
to the same borrower. Persisted to disk (not just in-memory) so the
limit survives across separate requests/process restarts, same as every
other piece of state in this project.
"""

import json
import time

from app.config import DATA_DIR

WHATIF_LOG_PATH = DATA_DIR / "whatif_call_log.json"
WHATIF_LIMIT_PER_WINDOW = 5
WHATIF_WINDOW_SECONDS = 300  # 5 minutes


def _load_log() -> dict:
    if not WHATIF_LOG_PATH.exists():
        return {}
    with open(WHATIF_LOG_PATH) as f:
        return json.load(f)


def _save_log(log: dict) -> None:
    with open(WHATIF_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


def _key(user_id: str, borrower_id: str) -> str:
    return f"{user_id}::{borrower_id}"


def check_whatif_rate_limit(
    borrower_id: str, user_id: str = "unknown", now: float = None
) -> dict:
    """Records this call attempt and returns {"blocked": bool, "reason":
    str, "calls_in_window": int}. Call this BEFORE running the actual
    simulation (Day 22's Router already does this) — the point is to
    stop the probing call from running at all once the limit is hit, not
    to let it run and then complain."""
    now = now if now is not None else time.time()
    log = _load_log()
    key = _key(user_id, borrower_id)

    timestamps = [t for t in log.get(key, []) if now - t < WHATIF_WINDOW_SECONDS]

    if len(timestamps) >= WHATIF_LIMIT_PER_WINDOW:
        log[key] = timestamps  # prune old entries even on a block
        _save_log(log)
        return {
            "blocked": True,
            "reason": (
                f"more than {WHATIF_LIMIT_PER_WINDOW} what-if requests for "
                f"{borrower_id} in the last {WHATIF_WINDOW_SECONDS // 60} minutes"
            ),
            "calls_in_window": len(timestamps),
        }

    timestamps.append(now)
    log[key] = timestamps
    _save_log(log)
    return {"blocked": False, "reason": "", "calls_in_window": len(timestamps)}


def reset_whatif_log() -> None:
    """Test/reset helper — same pattern as every other reset_* function
    in this project."""
    if WHATIF_LOG_PATH.exists():
        WHATIF_LOG_PATH.unlink()


if __name__ == "__main__":
    reset_whatif_log()
    fixed_now = time.time()

    for i in range(WHATIF_LIMIT_PER_WINDOW):
        r = check_whatif_rate_limit("MSME-1003", user_id="RM001", now=fixed_now + i)
        print(f"call {i + 1}:", r)
        assert r["blocked"] is False

    r_over_limit = check_whatif_rate_limit("MSME-1003", user_id="RM001", now=fixed_now + WHATIF_LIMIT_PER_WINDOW)
    print(f"call {WHATIF_LIMIT_PER_WINDOW + 1} (should block):", r_over_limit)
    assert r_over_limit["blocked"] is True

    # A different user probing the SAME borrower is a separate bucket —
    # must not be blocked by RM001's usage.
    r_other_user = check_whatif_rate_limit("MSME-1003", user_id="RM002", now=fixed_now)
    print("different user, same borrower (should NOT be blocked):", r_other_user)
    assert r_other_user["blocked"] is False

    # Same user, but well past the window — should reset.
    r_after_window = check_whatif_rate_limit(
        "MSME-1003", user_id="RM001", now=fixed_now + WHATIF_WINDOW_SECONDS + 1
    )
    print("same user, after window expires (should NOT be blocked):", r_after_window)
    assert r_after_window["blocked"] is False

    reset_whatif_log()
    print("What-if abuse check smoke test passed.")