"""
Day 6 — Gate logic with persistent, per-borrower state.

Ports update_gate_state() from scripts/golden_archetypes.py, with one
deliberate change: baseline_coldstart now fires on a signal's FIRST-EVER
observation for that borrower (no prior reading in state), not on a
hardcoded "cycle == 1". golden_archetypes.py could hardcode cycle 1 because
every archetype's own cycle list starts at 1 — but real borrowers don't:
MSME-1005 (cold_start archetype) onboards at cycle 6 in records.json, so
"cycle == 1" would never fire baseline for it in a real system.
First-ever-observation is the correct real-world condition.

State is persisted to data/case_state/<borrower_id>.json so gate decisions
survive across scoring runs, matching how a real deployed system works.
reset_case_state() exists specifically so Day 8's golden evaluator can
guarantee a clean slate on every run — without it, running the evaluator
twice in a row would silently give a different (wrong) result the second
time, since the gate would think it already saw cycle 1.

Day 13 — Cached-fallback recovery for a signal-source outage.

apply_cached_fallback() reuses the SAME per-signal state this module
already persists (hist["last"]) as a last-known-good cache — no separate
cache store. It must run BEFORE update_gate() for a given cycle's
subscores, so a substituted reading flows through gate/composite logic as
a normal reading rather than as unavailable_this_cycle (per the proposal's
§12 schema: source: 'real' | 'synthetic' | 'cached_fallback'). A stale
reading substituted for this cycle naturally makes update_gate()'s
`score < hist["last"]` comparison false (X < X), landing on
stable_or_improving with streak reset — the honest read of "no new
evidence either way," not a bug.

fallback_streak (persisted alongside "last"/"streak") caps how long a
fallback can be reused: MAX_FALLBACK_STREAK consecutive cycles, after
which the signal reverts to genuinely unavailable rather than silently
re-using ancient data forever. A signal with no hist["last"] yet
(cold-start borrower hitting an outage on its very first cycle) has
nothing to fall back to and correctly stays unavailable.
"""

import json
from pathlib import Path

from app.config import DATA_DIR

CASE_STATE_DIR = DATA_DIR / "case_state"
CASE_STATE_DIR.mkdir(parents=True, exist_ok=True)

DECLINE_STREAK_FOR_CONFIRM = 2  # must match scripts/golden_archetypes.py
MAX_FALLBACK_STREAK = 2  # placeholder — cap on consecutive cached-fallback cycles per signal


def _state_path(borrower_id: str) -> Path:
    return CASE_STATE_DIR / f"{borrower_id}.json"


def load_case_state(borrower_id: str) -> dict:
    path = _state_path(borrower_id)
    if not path.exists():
        return {"borrower_id": borrower_id, "signals": {}}
    with open(path) as f:
        return json.load(f)


def save_case_state(borrower_id: str, state: dict) -> None:
    with open(_state_path(borrower_id), "w") as f:
        json.dump(state, f, indent=2)


def reset_case_state(borrower_id: str | None = None) -> None:
    """Wipe one borrower's state, or ALL borrowers' state if borrower_id
    is None. Call this before any golden-evaluation run (Day 8) so results
    are reproducible run-to-run — otherwise a second run starts from
    whatever state the first run left behind."""
    if borrower_id is not None:
        path = _state_path(borrower_id)
        if path.exists():
            path.unlink()
        return
    for f in CASE_STATE_DIR.glob("*.json"):
        f.unlink()


# ---------------------------------------------------------------------------
# Day 12 — Scheduler idempotency (cycle_lock, per §12 state schema).
#
# The scheduled trigger checks whether a cycle is already running for a
# given borrower before starting another — prevents double-processing if
# a trigger fires twice (e.g. a retry, an overlapping cron tick) while a
# slow prior cycle for that SAME borrower hasn't finished yet. Stored
# alongside the rest of a borrower's state (same file gates.py already
# manages) since it's part of the same per-borrower record, not a
# separate concern.
# ---------------------------------------------------------------------------

def is_locked(borrower_id: str) -> bool:
    state = load_case_state(borrower_id)
    return state.get("cycle_lock", {}).get("locked", False)


def acquire_lock(borrower_id: str, cycle: int) -> bool:
    """Returns True if the lock was acquired, False if it was already
    held (meaning a cycle for this borrower is already running)."""
    state = load_case_state(borrower_id)
    if state.get("cycle_lock", {}).get("locked", False):
        return False
    state["cycle_lock"] = {"locked": True, "locked_cycle": cycle}
    save_case_state(borrower_id, state)
    return True


def release_lock(borrower_id: str) -> None:
    """Always safe to call, even if no lock was held — a failed cycle
    (exception mid-scoring) must still release the lock, or that
    borrower would be stuck locked out forever."""
    state = load_case_state(borrower_id)
    state["cycle_lock"] = {"locked": False, "locked_cycle": None}
    save_case_state(borrower_id, state)


def get_last_known_good(borrower_id: str, signal_name: str):
    """Returns the last successfully-seen score for this borrower/signal,
    or None if it has never succeeded even once (cold-start)."""
    state = load_case_state(borrower_id)
    return state.get("signals", {}).get(signal_name, {}).get("last")


def apply_cached_fallback(
    borrower_id: str, subscores: dict, failure_reasons: dict | None = None
) -> tuple[dict, dict]:
    """Given this cycle's raw subscores (collector failures are None),
    substitute a last-known-good score for any signal that's missing
    *because its source was unreachable* this cycle (failure_reasons[sig]
    == 'connection_outage'), provided a cached value exists and hasn't
    been reused past MAX_FALLBACK_STREAK consecutive cycles. Must be
    called BEFORE update_gate() — see module docstring.

    A None caused by 'insufficient_data' (the collector reached its
    source fine, but there's genuinely nothing for this cycle — e.g. the
    insufficient_data archetype) is deliberately NOT cache-eligible: that
    scenario exists specifically to test the Data Availability Check, and
    silently filling it from a stale cache would defeat the point. If
    failure_reasons isn't provided (e.g. a caller not yet updated), every
    None is treated as 'connection_outage' for backward compatibility.

    Returns (resolved_subscores, signal_sources), where signal_sources
    labels each signal 'fresh' | 'cached_fallback' | 'unavailable', per
    the proposal's §12 provenance schema.
    """
    failure_reasons = failure_reasons or {}
    state = load_case_state(borrower_id)
    signals = state.setdefault("signals", {})
    resolved = dict(subscores)
    signal_sources = {}

    for sig, score in subscores.items():
        hist = signals.setdefault(
            sig, {"streak": 0, "last": None, "fallback_streak": 0}
        )
        hist.setdefault("fallback_streak", 0)  # tolerate pre-Day-13 state files

        if score is not None:
            signal_sources[sig] = "fresh"
            hist["fallback_streak"] = 0
            continue

        reason = failure_reasons.get(sig, "connection_outage")
        if reason != "connection_outage":
            # Genuinely no data this cycle, not a transient outage —
            # must NOT be masked by a cache hit.
            signal_sources[sig] = "unavailable"
            continue

        if hist["last"] is None:
            # Nothing to fall back to yet (e.g. cold-start borrower's very
            # first cycle hitting an outage) — genuinely unavailable.
            signal_sources[sig] = "unavailable"
            continue

        if hist["fallback_streak"] >= MAX_FALLBACK_STREAK:
            # Source has been down too long — stop quietly re-using
            # ancient data and surface it as unavailable instead.
            signal_sources[sig] = "unavailable"
            continue

        resolved[sig] = hist["last"]
        hist["fallback_streak"] += 1
        signal_sources[sig] = "cached_fallback"

    save_case_state(borrower_id, state)
    return resolved, signal_sources


def update_gate(borrower_id: str, subscores: dict) -> dict:
    """Given this cycle's subscores, update and persist this borrower's
    gate state, returning gate_status per signal — same labels used
    throughout golden_archetypes.json: baseline_coldstart |
    unavailable_this_cycle | stable_or_improving | single_period_dip |
    confirmed_deteriorating."""
    state = load_case_state(borrower_id)
    signals = state.setdefault("signals", {})
    gate_status = {}

    for sig, score in subscores.items():
        hist = signals.setdefault(sig, {"streak": 0, "last": None})

        if score is None:
            gate_status[sig] = "unavailable_this_cycle"
            continue

        if hist["last"] is None:
            gate_status[sig] = "baseline_coldstart"
        elif score < hist["last"]:
            hist["streak"] += 1
            gate_status[sig] = (
                "confirmed_deteriorating"
                if hist["streak"] >= DECLINE_STREAK_FOR_CONFIRM
                else "single_period_dip"
            )
        else:
            hist["streak"] = 0
            gate_status[sig] = "stable_or_improving"

        hist["last"] = score

    save_case_state(borrower_id, state)
    return gate_status


if __name__ == "__main__":
    # Smoke test: replay MSME-1003's gradual_decline cash_flow sequence
    # (78, 68, 58, 42, 28) and confirm gate transitions match
    # golden_archetypes.json: baseline -> single_period_dip ->
    # confirmed_deteriorating -> confirmed_deteriorating -> confirmed_deteriorating
    test_borrower = "MSME-1003-GATE-TEST"
    reset_case_state(test_borrower)

    sequence = [78, 68, 58, 42, 28]
    expected = [
        "baseline_coldstart",
        "single_period_dip",
        "confirmed_deteriorating",
        "confirmed_deteriorating",
        "confirmed_deteriorating",
    ]
    for i, (score, exp) in enumerate(zip(sequence, expected), start=1):
        status = update_gate(test_borrower, {"cash_flow": score})
        got = status["cash_flow"]
        mark = "OK" if got == exp else "MISMATCH"
        print(f"cycle {i}: cash_flow={score:3d}  got={got:<25} expected={exp:<25} [{mark}]")

    reset_case_state(test_borrower)  # clean up test state, don't leave it lying around
    print(f"\nstate file exists after cleanup: {_state_path(test_borrower).exists()}")