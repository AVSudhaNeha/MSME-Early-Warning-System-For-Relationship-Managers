"""
Day 7 — Tier smoothing, with persistent per-borrower tier state.

Ported from scripts/golden_archetypes.py's raw_band() + smoothed_tier().
Reuses the same data/case_state/<borrower_id>.json file Day 6's gates.py
writes to, just under a separate "tier" key — one state file per borrower,
not two, since it's the same borrower's history either way.
"""

from app.scoring.constants import CRITICAL_FLOOR, GREEN_MIN, AMBER_MIN, DECLINE_STREAK_FOR_CONFIRM
from app.scoring.gates import load_case_state, save_case_state


def raw_band(composite: float) -> str:
    """Pure threshold banding, no smoothing — what the composite says on
    its own, before we decide whether to act on it yet."""
    if composite < CRITICAL_FLOOR:
        return "Red"
    if composite >= GREEN_MIN:
        return "Green"
    if composite >= AMBER_MIN:
        return "Amber"
    return "Red"


def _default_tier_state() -> dict:
    return {"prior_composite": None, "prior_tier": None, "decline_streak": 0}


def smoothed_tier(borrower_id: str, composite: float):
    """Returns (tier, raw_tier, smoothing_note). Persists tier state to
    the same per-borrower case_state file gates.py uses.

    Call this ONLY when composite is not None. An insufficient-data cycle
    (composite.py returns None) should leave tier state completely
    untouched, so the next valid cycle still compares against the last
    real composite rather than treating the gap as a data point."""
    state = load_case_state(borrower_id)
    tier_state = state.setdefault("tier", _default_tier_state())

    raw = raw_band(composite)

    if composite < CRITICAL_FLOOR:
        tier_state["prior_composite"] = composite
        tier_state["prior_tier"] = "Red"
        tier_state["decline_streak"] = 0
        save_case_state(borrower_id, state)
        return "Red", raw, "critical_floor_override_immediate"

    if tier_state["prior_composite"] is None:
        tier_state["prior_composite"] = composite
        tier_state["prior_tier"] = raw
        tier_state["decline_streak"] = 0
        save_case_state(borrower_id, state)
        return raw, raw, "baseline_coldstart"

    if composite < tier_state["prior_composite"]:
        tier_state["decline_streak"] += 1
        if tier_state["decline_streak"] >= DECLINE_STREAK_FOR_CONFIRM:
            displayed = raw
            smoothing_note = "confirmed_deteriorating_tier_applied"
        else:
            displayed = tier_state["prior_tier"]
            smoothing_note = "single_period_dip_smoothed_tier_held"
    else:
        tier_state["decline_streak"] = 0
        displayed = raw
        smoothing_note = "stable_or_improving_applied_immediately"

    tier_state["prior_composite"] = composite
    tier_state["prior_tier"] = displayed
    save_case_state(borrower_id, state)
    return displayed, raw, smoothing_note


if __name__ == "__main__":
    from app.scoring.gates import reset_case_state
    from app.scoring.composite import calculate_composite

    # Smoke test: replay MSME-1004's sharp_decline composites and confirm
    # tier transitions match golden_archetypes.json: Green (baseline) ->
    # Green (single-dip smoothed) -> Red (critical floor override).
    test_borrower = "MSME-1004-TIER-TEST"
    reset_case_state(test_borrower)

    cycles = [
        {"gst_filing_delay": 84, "cash_flow": 80, "vendor_payment": 83, "industry_index": 76},
        {"gst_filing_delay": 60, "cash_flow": 35, "vendor_payment": 48, "industry_index": 74},
        {"gst_filing_delay": 25, "cash_flow": 8, "vendor_payment": 12, "industry_index": 70},
    ]
    expected = [
        ("Green", "baseline_coldstart"),
        ("Green", "single_period_dip_smoothed_tier_held"),
        ("Red", "critical_floor_override_immediate"),
    ]
    for i, (subscores, (exp_tier, exp_note)) in enumerate(zip(cycles, expected), start=1):
        composite = calculate_composite(subscores)
        tier, raw, note = smoothed_tier(test_borrower, composite)
        mark = "OK" if (tier, note) == (exp_tier, exp_note) else "MISMATCH"
        print(f"cycle {i}: composite={composite:5.1f}  raw={raw:<6} tier={tier:<6} note={note:<38} [{mark}]")

    reset_case_state(test_borrower)