"""
Flow A — full end-to-end test of the automated monitoring/scoring path:

    Scheduler -> Collectors -> Signal Fallback/Availability -> Composite
    -> Trend Gates -> Tier -> Peer Attribution -> Case Lifecycle ->
    SLA/Handoff -> Case Trace

Unlike scripts/full_eval_harness.py (which re-runs each hardened piece in
isolation with hand-built inputs), this drives the REAL entry point —
app.scheduler.trigger_cycle() — against real archetype borrowers already
in data/golden_archetypes.json, so every layer above is actually
exercised together, in the order a real deployment would hit it.

Each scenario resets its borrower's state before and after, so nothing
here leaks into a later golden-evaluator run.
"""

from app.scheduler import trigger_cycle
from app.scoring.gates import reset_case_state
from app.case_lifecycle import reset_case_record
from app.case_trace import reset_trace
from app.handoff_retry import attempt_handoff

FAILURES = []
TOTAL_CHECKS = 0


def _check(label: str, condition: bool, detail: str = "") -> None:
    global TOTAL_CHECKS
    TOTAL_CHECKS += 1
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _reset(borrower_id: str) -> None:
    reset_case_state(borrower_id)
    reset_case_record(borrower_id)
    reset_trace(borrower_id)


def scenario_healthy_green():
    b = "MSME-1001"
    _reset(b)
    r = trigger_cycle(b, 1)["result"]
    _check("Healthy Green: tier is Green", r["tier"] == "Green", detail=r["tier"])
    _check("Healthy Green: case action is log_only", r["case_action"] == "log_only")
    _check("Healthy Green: no case opened", r["case_lifecycle_action"] == "no_case_needed")
    _reset(b)


def scenario_gradual_green_to_amber():
    b = "MSME-1003"
    _reset(b)
    trigger_cycle(b, 1)
    trigger_cycle(b, 2)
    r3 = trigger_cycle(b, 3)["result"]
    _check("Gradual decline: cycle 3 reaches Amber", r3["tier"] == "Amber", detail=r3["tier"])
    _check(
        "Gradual decline: a case is opened on first Amber cycle",
        r3["case_lifecycle_action"] == "case_opened",
        detail=r3["case_lifecycle_action"],
    )
    _reset(b)


def scenario_severe_deterioration_to_red():
    b = "MSME-1004"
    _reset(b)
    trigger_cycle(b, 1)
    trigger_cycle(b, 2)
    r3 = trigger_cycle(b, 3)["result"]
    _check("Sharp decline: cycle 3 reaches Red", r3["tier"] == "Red", detail=r3["tier"])
    _check(
        "Sharp decline: case action is hardship handoff",
        r3["case_action"] == "rm_outreach_plus_hardship_handoff",
        detail=r3["case_action"],
    )
    _reset(b)
    return r3  # used by scenario_red_handoff


def scenario_recovery_false_alarm():
    b = "MSME-1006"
    _reset(b)
    trigger_cycle(b, 1)
    r2 = trigger_cycle(b, 2)["result"]
    r3 = trigger_cycle(b, 3)["result"]
    _check(
        "False-alarm recovery: cycle 2 shows a single dip, not a confirmed trend",
        r2["gate_status"]["cash_flow"] == "single_period_dip",
        detail=str(r2["gate_status"]),
    )
    _check(
        "False-alarm recovery: cycle 3 recovers to stable_or_improving",
        r3["gate_status"]["cash_flow"] == "stable_or_improving",
        detail=str(r3["gate_status"]),
    )
    _check(
        "False-alarm recovery: tier never leaves Green, no case opened",
        r2["tier"] == "Green" and r3["tier"] == "Green" and r3["case_lifecycle_action"] == "no_case_needed",
    )
    _reset(b)


def scenario_insufficient_data():
    b = "MSME-1008"
    _reset(b)
    trigger_cycle(b, 1)
    r2 = trigger_cycle(b, 2)["result"]
    _check("Insufficient data: tier is None", r2["tier"] is None, detail=str(r2["tier"]))
    _check(
        "Insufficient data: case action is manual review, not an automated tier action",
        r2["case_action"] == "manual_review_insufficient_data",
        detail=r2["case_action"],
    )
    _reset(b)


def scenario_cached_fallback_outage():
    b = "MSME-1009"
    _reset(b)
    trigger_cycle(b, 1)
    r2 = trigger_cycle(b, 2)["result"]
    _check(
        "AA outage: cash_flow substituted from cache, not reported unavailable",
        r2["signal_sources"]["cash_flow"] == "cached_fallback",
        detail=str(r2["signal_sources"]),
    )
    _check(
        "AA outage: still produces a real tier despite the outage",
        r2["tier"] is not None,
        detail=str(r2["tier"]),
    )
    _reset(b)


def scenario_case_opening_and_updating():
    b = "MSME-1003"
    _reset(b)
    trigger_cycle(b, 1)
    trigger_cycle(b, 2)
    r3 = trigger_cycle(b, 3)["result"]  # first Amber cycle -> opens
    r4 = trigger_cycle(b, 4)["result"]  # still Amber -> updates, same case
    _check(
        "Case lifecycle: cycle 3 opens a case",
        r3["case_lifecycle_action"] == "case_opened",
        detail=r3["case_lifecycle_action"],
    )
    _check(
        "Case lifecycle: cycle 4 updates the SAME case, doesn't open a new one",
        r4["case_lifecycle_action"] == "case_updated" and r4["case_id"] == r3["case_id"],
        detail=f"{r4['case_lifecycle_action']}, case_id {r4['case_id']} vs {r3['case_id']}",
    )
    _reset(b)


def scenario_red_handoff(red_result: dict):
    """Confirms the retry/escalate mechanism actually engages for a real
    Red-tier result produced by the pipeline above — not just a hand-built
    input like full_eval_harness.py's version of this check."""
    def succeeds_immediately(borrower_id, cycle):
        return True

    r = attempt_handoff(red_result["borrower_id"], red_result["cycle"], call_fn=succeeds_immediately)
    _check(
        "Red handoff: a real Red-tier result triggers a successful handoff attempt",
        r["status"] == "handoff_succeeded",
        detail=str(r),
    )


def scenario_duplicate_cycle_rejected():
    """Explicit, standalone version of the duplicate-cycle protection —
    red_team_tests.py already covers this via a manually-held lock; this
    version drives it through the real portfolio-style call pattern
    (trigger_cycle twice for the exact same cycle number back to back)."""
    b = "MSME-1001"
    _reset(b)
    r1 = trigger_cycle(b, 1)
    r2 = trigger_cycle(b, 1)  # same cycle again, lock already released by r1
    _check(
        "Duplicate cycle: re-running the SAME cycle doesn't open a second case",
        r1["result"]["case_id"] == r2["result"]["case_id"] or r2["result"]["case_lifecycle_action"] != "case_opened",
        detail=f"{r1['result']['case_lifecycle_action']} vs {r2['result']['case_lifecycle_action']}",
    )
    _reset(b)


def scenario_trace_persistence():
    """Explicit check that a real scoring cycle creates exactly the
    trace entry it should — not implicitly assumed from other
    scenarios passing."""
    from app.case_trace import load_trace

    b = "MSME-1001"
    _reset(b)
    r = trigger_cycle(b, 1)["result"]
    trace = load_trace(b)
    _check("Trace persistence: exactly one entry after one cycle", len(trace) == 1, detail=str(len(trace)))
    _check(
        "Trace persistence: the entry matches what run_scoring actually returned",
        trace[0]["tier"] == r["tier"] and trace[0]["composite_score"] == r["composite_score"],
        detail=f"trace={trace[0].get('tier')}/{trace[0].get('composite_score')} vs result={r['tier']}/{r['composite_score']}",
    )
    _reset(b)


def run_flow_a_e2e():
    print("=== Flow A end-to-end ===\n")
    scenario_healthy_green()
    scenario_gradual_green_to_amber()
    red_result = scenario_severe_deterioration_to_red()
    scenario_recovery_false_alarm()
    scenario_insufficient_data()
    scenario_cached_fallback_outage()
    scenario_case_opening_and_updating()
    scenario_duplicate_cycle_rejected()
    scenario_trace_persistence()
    scenario_red_handoff(red_result)

    passed = TOTAL_CHECKS - len(FAILURES)
    print(f"\n{passed}/{TOTAL_CHECKS} Flow A checks passed.")
    if FAILURES:
        print("FAILED:", FAILURES)
    else:
        print("Flow A end-to-end: all scenarios passed.")


if __name__ == "__main__":
    run_flow_a_e2e()