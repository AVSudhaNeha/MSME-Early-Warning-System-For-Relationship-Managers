"""
Golden-trace archetype generator — Day 1-3 deliverable.

Scripts 9 canonical borrower trajectories as labeled, cycle-by-cycle test
data: the 6 core archetypes from proposal §13.1 (steady, seasonal, gradual
decline, sharp decline, false-alarm/recovery, peer-wide shock) plus the 3
hardening archetypes called out explicitly in the Day 1-3 roadmap item
(cold-start, insufficient-data, sandbox-outage).

For each cycle we hand-author the sub-score for every signal (0 = worst,
100 = healthiest) — that's the "script" — then run the same deterministic
rules the real Composite Scoring Engine will use (§6, §8) to derive the
gate status, composite score, tier, and peer attribution. This keeps every
label internally consistent, the way a golden trace has to be, without
needing the real engine built yet (that's Days 4-8).

Tier smoothing (Step 1 decision): a downgrade only takes effect after 2+
consecutive declining cycles. A single-period dip is flagged
(`single_period_dip_smoothed_tier_held`) but the *displayed* tier holds at
last cycle's tier until the decline is confirmed. The one exception is the
critical floor — if the composite falls below CRITICAL_FLOOR, Red fires
immediately regardless of streak state, since a catastrophic collapse
should never be hidden by smoothing. Recoveries/improvements are never
smoothed. Each cycle now reports both `raw_tier` (pure threshold banding,
no smoothing) and `tier` (what actually gets displayed/acted on), so a
smoothed cycle is visible rather than silent.

Output: data/golden_archetypes.json
That file is the input to Session 10 Step 3 (curate a golden_dataset.json)
and what Session 11's automated scorer will eventually load.

WEIGHTS/thresholds now come from app/scoring/constants.py — the single
source of truth shared with the real scoring engine (Days 4-8), so this
script and the engine can never silently drift apart.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "golden_archetypes.json"

sys.path.insert(0, str(ROOT))  # so `app.scoring.constants` resolves when run as a script
from app.scoring.constants import (  # noqa: E402
    WEIGHTS, GREEN_MIN, AMBER_MIN, CRITICAL_FLOOR,
    MIN_SIGNALS_REQUIRED, DECLINE_STREAK_FOR_CONFIRM,
)


def raw_band(composite):
    """Pure threshold banding, no smoothing — this is what the composite
    would say on its own, before we decide whether to act on it yet."""
    if composite < CRITICAL_FLOOR:
        return "Red"
    if composite >= GREEN_MIN:
        return "Green"
    if composite >= AMBER_MIN:
        return "Amber"
    return "Red"


def composite_only(subscores: dict):
    """Weighted, re-normalized composite score (§6, §8)."""
    available = {k: v for k, v in subscores.items() if v is not None}
    if not available:
        return None
    total_w = sum(WEIGHTS[k] for k in available)
    return round(sum(subscores[k] * WEIGHTS[k] for k in available) / total_w, 1)


def smoothed_tier(composite, tier_state):
    """Step 1 decision: a downgrade only takes effect after 2+ consecutive
    declining cycles. A single-period dip is flagged but the displayed tier
    holds at last cycle's tier. The critical floor is the one exception —
    below it, Red fires immediately, no smoothing, no exceptions.
    Improvements/recoveries are never smoothed — no reason to delay good news."""
    raw = raw_band(composite)

    if composite < CRITICAL_FLOOR:
        tier_state["prior_composite"] = composite
        tier_state["prior_tier"] = "Red"
        tier_state["decline_streak"] = 0
        return "Red", raw, "critical_floor_override_immediate"

    if tier_state["prior_composite"] is None:
        # cycle 1 — no prior cycle to smooth against, display the raw band
        tier_state["prior_composite"] = composite
        tier_state["prior_tier"] = raw
        tier_state["decline_streak"] = 0
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
    return displayed, raw, smoothing_note


def update_gate_state(signal_history: dict, subscores: dict, cycle_idx: int):
    """Per-signal gate: 2+ consecutive declines -> confirmed_deteriorating.
    Skipped (baseline_coldstart) on cycle 1 for every borrower (§6, §8)."""
    gate_status = {}
    for sig, score in subscores.items():
        hist = signal_history.setdefault(sig, {"streak": 0, "last": None})
        if score is None:
            gate_status[sig] = "unavailable_this_cycle"
            continue
        if cycle_idx == 1:
            gate_status[sig] = "baseline_coldstart"
        elif hist["last"] is not None and score < hist["last"]:
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
    return gate_status


def attribute(composite, prior_composite, peer_avg_delta, tier):
    """Peer-relative attribution — never overrides Red past the critical floor (§6, §8)."""
    if composite is None or prior_composite is None:
        return None
    delta = round(composite - prior_composite, 1)
    if composite < CRITICAL_FLOOR:
        return "critical_floor_override"
    if peer_avg_delta is None:
        return "borrower_specific"  # no peer context this cycle -> absolute tier only
    return "peer_driven" if abs(delta - peer_avg_delta) <= 5 else "borrower_specific"


def case_action(tier, insufficient=False, sla_timeout=False, handoff_failed=False):
    if insufficient:
        return "manual_review_insufficient_data"
    if tier == "Green":
        return "log_only"
    if tier == "Amber":
        return "rm_outreach_escalated_sla_timeout" if sla_timeout else "rm_outreach"
    if tier == "Red":
        return "hardship_handoff_failed_manual_review" if handoff_failed else "rm_outreach_plus_hardship_handoff"
    return "n/a"


def build_archetype(borrower_id, label, cycles, notes=""):
    """cycles: list of dicts, each with subscores + optional peer_avg_delta /
    insufficient / sandbox_outage flags. Returns the fully labeled trace."""
    signal_history = {}
    tier_state = {"prior_composite": None, "prior_tier": None, "decline_streak": 0}
    prior_composite_for_attribution = None
    trace = []
    for i, c in enumerate(cycles, start=1):
        subscores = c["subscores"]
        insufficient = sum(v is not None for v in subscores.values()) < MIN_SIGNALS_REQUIRED

        gate_status = update_gate_state(signal_history, subscores, i)

        if insufficient:
            composite, tier, raw_tier, smoothing_note = None, None, None, "insufficient_data_no_tier"
        else:
            composite = composite_only(subscores)
            tier, raw_tier, smoothing_note = smoothed_tier(composite, tier_state)

        peer_avg_delta = c.get("peer_avg_delta")
        attribution = None if insufficient else attribute(
            composite, prior_composite_for_attribution, peer_avg_delta, tier
        )
        action = case_action(
            tier,
            insufficient=insufficient,
            sla_timeout=c.get("sla_timeout", False),
            handoff_failed=c.get("handoff_failed", False),
        )

        trace.append({
            "cycle": i,
            "subscores": subscores,
            "gate_status": gate_status,
            "sandbox_status": c.get("sandbox_status", "ok"),
            "data_availability": "insufficient" if insufficient else "full_or_partial_ok",
            "composite_score": composite,
            "raw_tier": raw_tier,
            "tier": tier,
            "smoothing_note": smoothing_note,
            "peer_avg_delta": peer_avg_delta,
            "expected_attribution": attribution,
            "expected_case_action": action,
            "cycle_notes": c.get("note", ""),
        })
        if composite is not None:
            prior_composite_for_attribution = composite

    return {
        "borrower_id": borrower_id,
        "archetype": label,
        "archetype_notes": notes,
        "cycles": trace,
    }


# ---------------------------------------------------------------------------
# 6 core archetypes (§13.1)
# ---------------------------------------------------------------------------
ARCHETYPES = []

# 1. Steady — stays healthy, minor noise, never leaves Green.
ARCHETYPES.append(build_archetype(
    "MSME-1001", "steady",
    [
        {"subscores": {"gst_filing_delay": 88, "cash_flow": 85, "vendor_payment": 90, "industry_index": 80}},
        {"subscores": {"gst_filing_delay": 86, "cash_flow": 87, "vendor_payment": 88, "industry_index": 81}},
        {"subscores": {"gst_filing_delay": 89, "cash_flow": 84, "vendor_payment": 91, "industry_index": 79}},
        {"subscores": {"gst_filing_delay": 87, "cash_flow": 86, "vendor_payment": 89, "industry_index": 82}},
    ],
    notes="Control case — every cycle should classify Green, gate never confirms deterioration.",
))

# 2. Seasonal — cash flow dips every export off-season but recovers next
#    cycle; the 2-consecutive-decline gate must NOT confirm on a single dip.
ARCHETYPES.append(build_archetype(
    "MSME-1002", "seasonal",
    [
        {"subscores": {"gst_filing_delay": 82, "cash_flow": 78, "vendor_payment": 80, "industry_index": 75}},
        {"subscores": {"gst_filing_delay": 81, "cash_flow": 55, "vendor_payment": 76, "industry_index": 74},
         "note": "off-season dip — single period, gate should read single_period_dip not confirmed"},
        {"subscores": {"gst_filing_delay": 83, "cash_flow": 79, "vendor_payment": 81, "industry_index": 76},
         "note": "recovers next cycle as expected for a seasonal pattern"},
        {"subscores": {"gst_filing_delay": 80, "cash_flow": 54, "vendor_payment": 77, "industry_index": 75},
         "note": "second season's dip — still a single-period event relative to its own recovery, not a trend"},
    ],
    notes="Tests smoothing: a real seasonal pattern must never get misread as sustained decline.",
))

# 3. Gradual decline — sustained multi-cycle worsening, no peer movement,
#    should progress Green -> Amber -> confirmed Red, borrower-specific.
ARCHETYPES.append(build_archetype(
    "MSME-1003", "gradual_decline",
    [
        {"subscores": {"gst_filing_delay": 80, "cash_flow": 78, "vendor_payment": 82, "industry_index": 70}, "peer_avg_delta": 0},
        {"subscores": {"gst_filing_delay": 72, "cash_flow": 68, "vendor_payment": 74, "industry_index": 71}, "peer_avg_delta": 0.5},
        {"subscores": {"gst_filing_delay": 63, "cash_flow": 58, "vendor_payment": 65, "industry_index": 69},
         "peer_avg_delta": 0.2, "note": "2nd consecutive decline — gate should now read confirmed_deteriorating"},
        {"subscores": {"gst_filing_delay": 50, "cash_flow": 42, "vendor_payment": 55, "industry_index": 70},
         "peer_avg_delta": -0.3, "note": "composite should cross into Amber here"},
        {"subscores": {"gst_filing_delay": 38, "cash_flow": 28, "vendor_payment": 40, "industry_index": 68},
         "peer_avg_delta": 0.1, "note": "peers flat while borrower keeps falling -> borrower_specific, not peer_driven"},
    ],
    notes="Peer index stays flat throughout — isolates borrower-specific decline from sector-wide movement.",
))

# 4. Sharp decline — 1-2 cycle collapse straight through the critical floor.
ARCHETYPES.append(build_archetype(
    "MSME-1004", "sharp_decline",
    [
        {"subscores": {"gst_filing_delay": 84, "cash_flow": 80, "vendor_payment": 83, "industry_index": 76}, "peer_avg_delta": 0},
        {"subscores": {"gst_filing_delay": 60, "cash_flow": 35, "vendor_payment": 48, "industry_index": 74},
         "peer_avg_delta": 1, "note": "sharp single-cycle collapse"},
        {"subscores": {"gst_filing_delay": 25, "cash_flow": 8, "vendor_payment": 12, "industry_index": 70},
         "peer_avg_delta": 0.5, "note": "crosses the critical floor -> Red must fire regardless of peer context"},
    ],
    notes="Tests the critical-floor override: Red must not be softened even though peers barely moved.",
))

# 5. False-alarm / recovery — one bad cycle, fully recovers; gate must not
#    confirm a trend, tier should not be dragged to Amber on one dip.
ARCHETYPES.append(build_archetype(
    "MSME-1006", "false_alarm_recovery",
    [
        {"subscores": {"gst_filing_delay": 85, "cash_flow": 83, "vendor_payment": 86, "industry_index": 77}},
        {"subscores": {"gst_filing_delay": 84, "cash_flow": 60, "vendor_payment": 84, "industry_index": 76},
         "note": "one bad cash-flow cycle — single_period_dip only"},
        {"subscores": {"gst_filing_delay": 86, "cash_flow": 82, "vendor_payment": 85, "industry_index": 78},
         "note": "fully recovered — composite should read back near baseline, Green"},
    ],
    notes="A single bad reading must not be treated as a real trend (§8, 'A single bad reading vs. a real trend').",
))

# 6. Peer-wide shock — a sector-wide event drags industry_index and cash
#    flow down for everyone; attribution should read peer_driven UNLESS a
#    borrower individually crosses the critical floor.
ARCHETYPES.append(build_archetype(
    "MSME-1007", "peer_wide_shock",
    [
        {"subscores": {"gst_filing_delay": 80, "cash_flow": 76, "vendor_payment": 79, "industry_index": 78}, "peer_avg_delta": 0},
        {"subscores": {"gst_filing_delay": 78, "cash_flow": 55, "vendor_payment": 60, "industry_index": 45},
         "peer_avg_delta": -18, "note": "sector-wide shock cycle — borrower's own delta tracks the peer group's delta closely"},
        {"subscores": {"gst_filing_delay": 72, "cash_flow": 40, "vendor_payment": 48, "industry_index": 45},
         "peer_avg_delta": 0, "note": "borrower keeps sliding after the shock while peers stabilize -> should flip to borrower_specific"},
    ],
    notes="Opens a parallel portfolio-level review per §8 in the real system; here we assert per-borrower attribution only.",
))

# ---------------------------------------------------------------------------
# 3 hardening archetypes named explicitly in the Day 1-3 roadmap line
# ---------------------------------------------------------------------------

# 7. Cold-start — borrower's first monitoring cycle; the pattern gate must
#    be skipped entirely (baseline_coldstart), not read as a false trend.
ARCHETYPES.append(build_archetype(
    "MSME-1005", "cold_start",
    [
        {"subscores": {"gst_filing_delay": 66, "cash_flow": 58, "vendor_payment": 70, "industry_index": 72},
         "note": "first cycle ever for this borrower (onboarded_cycle=6 in records.json) — no prior period exists"},
        {"subscores": {"gst_filing_delay": 65, "cash_flow": 60, "vendor_payment": 69, "industry_index": 71},
         "note": "second cycle — trend logic now applies normally"},
    ],
    notes="Cycle 1 gate_status must read baseline_coldstart for every signal, never confirmed/dipped.",
))

# 8. Insufficient data — too few signals return this cycle; must escalate
#    to manual review, never silently default to Green.
ARCHETYPES.append(build_archetype(
    "MSME-1008", "insufficient_data",
    [
        {"subscores": {"gst_filing_delay": 84, "cash_flow": 81, "vendor_payment": 85, "industry_index": 79}},
        {"subscores": {"gst_filing_delay": None, "cash_flow": 80, "vendor_payment": None, "industry_index": None},
         "note": "only 1 of 4 signals returned this cycle (< MIN_SIGNALS_REQUIRED=2) -> flag Insufficient Data, no tier"},
        {"subscores": {"gst_filing_delay": 83, "cash_flow": 79, "vendor_payment": 84, "industry_index": 78},
         "note": "signals recover next cycle — scoring resumes normally"},
    ],
    notes="Cycle 2 must produce tier=null, composite_score=null, expected_case_action=manual_review_insufficient_data.",
))

# 9. Sandbox outage — the real AA sandbox / GSTIN call fails mid-cycle;
#    cached fallback should read as a normal reading, not a data gap.
ARCHETYPES.append(build_archetype(
    "MSME-1009", "sandbox_outage",
    [
        {"subscores": {"gst_filing_delay": 82, "cash_flow": 80, "vendor_payment": 83, "industry_index": 77}},
        {"subscores": {"gst_filing_delay": 81, "cash_flow": 80, "vendor_payment": 82, "industry_index": 76},
         "sandbox_status": "outage_cached_fallback",
         "note": "AA sandbox call failed this cycle — cached last-known-good cash_flow reading used, "
                 "counted as available, NOT as a missing-signal gap"},
        {"subscores": {"gst_filing_delay": 83, "cash_flow": 79, "vendor_payment": 81, "industry_index": 78},
         "note": "sandbox back online next cycle"},
    ],
    notes="Cycle 2's cash_flow must still count toward MIN_SIGNALS_REQUIRED and the composite — a cache hit is not a data gap.",
))

if __name__ == "__main__":
    OUT_PATH.write_text(json.dumps(ARCHETYPES, indent=2))
    print(f"Wrote {len(ARCHETYPES)} archetypes ({sum(len(a['cycles']) for a in ARCHETYPES)} total cycles) -> {OUT_PATH}")
    for a in ARCHETYPES:
        tiers = [c["tier"] or "—" for c in a["cycles"]]
        raw = [c["raw_tier"] or "—" for c in a["cycles"]]
        print(f"  {a['archetype']:<22} {a['borrower_id']:<10} tier: {tiers}   raw: {raw}")