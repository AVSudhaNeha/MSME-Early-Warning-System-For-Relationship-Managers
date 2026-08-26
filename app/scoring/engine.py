"""
Day 8 — Orchestration. Day 9 — Peer-Relative Adjustment wired in.
Day 10 — Signal collection now runs through a LangGraph fan-out/fan-in
graph (app/graph/signal_collection_graph.py) instead of a plain loop.
Day 11 — Case Lifecycle Check wired in.

run_scoring(borrower_id, cycle) chains: collectors (parallel, via graph)
-> cached-fallback resolution -> gate -> composite -> tier -> peer
attribution -> case lifecycle. This is the full Days 4-13 pipeline wired
together.

Day 13 — cached-fallback recovery for a signal-source outage. Where a
collector raises (AAConnectionError / ValueError for insufficient upstream
data), apply_cached_fallback() substitutes that signal's last-known-good
score (if one exists and hasn't been reused past MAX_FALLBACK_STREAK
cycles) BEFORE the gate/composite see it, so a cache hit counts as
available data rather than a gap. See app/scoring/gates.py's docstring for
the full reasoning, and the updated note below (previously in evaluator.py)
about what this changes for the sandbox_outage archetype specifically.
"""

from app.graph.signal_collection_graph import collect_all_signals
from app.scoring.gates import update_gate, load_case_state, apply_cached_fallback
from app.scoring.composite import calculate_composite
from app.scoring.tiering import smoothed_tier
from app.scoring.peer_adjustment import attribute_change
from app.case_lifecycle import get_or_create_case
from app.case_trace import append_trace_entry


def _case_action(tier, insufficient):
    """Simplified vs. the golden script's case_action() — no sla_timeout /
    handoff_failed branches here, since those depend on downstream
    workflow state (Days 9-13+) that doesn't exist yet in this engine."""
    if insufficient:
        return "manual_review_insufficient_data"
    if tier == "Green":
        return "log_only"
    if tier == "Amber":
        return "rm_outreach"
    if tier == "Red":
        return "rm_outreach_plus_hardship_handoff"
    return "n/a"


def run_scoring(borrower_id: str, cycle: int) -> dict:
    subscores, failure_reasons = collect_all_signals(borrower_id, cycle)
    subscores, signal_sources = apply_cached_fallback(
        borrower_id, subscores, failure_reasons
    )

    gate_status = update_gate(borrower_id, subscores)
    composite = calculate_composite(subscores)
    insufficient = composite is None

    if insufficient:
        tier, raw_tier, smoothing_note = None, None, "insufficient_data_no_tier"
        peer_info = {"attribution": None, "peer_avg_delta": None, "peer_group_size": 0}
    else:
        prior_composite = load_case_state(borrower_id).get("tier", {}).get("prior_composite")
        tier, raw_tier, smoothing_note = smoothed_tier(borrower_id, composite)
        peer_info = attribute_change(borrower_id, cycle, composite, prior_composite)

    case_info = get_or_create_case(borrower_id, cycle, tier)

    result = {
        "borrower_id": borrower_id,
        "cycle": cycle,
        "subscores": subscores,
        "signal_sources": signal_sources,
        "gate_status": gate_status,
        "data_availability": "insufficient" if insufficient else "full_or_partial_ok",
        "composite_score": composite,
        "raw_tier": raw_tier,
        "tier": tier,
        "smoothing_note": smoothing_note,
        "attribution": peer_info["attribution"],
        "peer_avg_delta": peer_info["peer_avg_delta"],
        "peer_group_size": peer_info["peer_group_size"],
        "case_id": case_info["case_id"],
        "case_status": case_info["case_status"],
        "case_lifecycle_action": case_info["action"],
        "rm_id": case_info["rm_id"],
        "rm_name": case_info["rm_name"],
        "case_action": _case_action(tier, insufficient),
    }
    # Day 15 — record the exact, deterministic outcome of this cycle. Must
    # happen AFTER every field above is final, since the Explanation
    # Agent will later quote this entry as ground truth for this cycle.
    append_trace_entry(borrower_id, result)
    return result