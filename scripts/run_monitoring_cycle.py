"""
scripts/run_monitoring_cycle.py — one full portfolio monitoring run.

    Load active borrowers (data/records.json)
        -> for each: determine its OWN next cycle (case_trace.get_next_cycle)
        -> trigger_cycle(borrower_id, next_cycle)  [the real Flow A pipeline]
        -> report result
        -> continue, even if this borrower failed

This is a thin orchestration layer, not a reimplementation — every
actual pipeline step (collectors, cached fallback, gates, composite,
tiering, peer attribution, case lifecycle, SLA, trace) already lives
inside app.scheduler.trigger_cycle(), confirmed as the real Flow A entry
point by direct inspection. This script only decides WHO to run and
WHICH cycle, then calls that existing entry point — it never touches
scoring internals directly, so it can't accidentally bypass the
scheduler's own idempotency lock.

CONTINUOUS MONITORING — cycles no longer stop at golden_archetypes.json's
scripted range. Signal data now comes from app.mocks.monitoring_dataset,
which bootstraps as an exact copy of golden_archetypes.json on first use
and then GROWS on its own — any cycle beyond a borrower's latest existing
one gets a freshly generated set of input observations (small,
momentum-biased changes from the previous cycle, not random noise), which
then flows through the exact same existing scoring pipeline as any other
cycle. golden_archetypes.json itself is never modified — see that
module's docstring for the full read-only/grows-separately split.

A genuinely unrecognized borrower_id (no archetype in the monitoring
dataset at all — different from "ran out of scripted cycles", which no
longer happens) is still a real failure, reported and isolated per
borrower, same as any other unexpected error — this script never lets
one borrower's problem stop the rest of the portfolio.
REALISTIC PORTFOLIO HISTORY — a borrower's first-ever run doesn't start
at cycle 1 for its own sake; records.json now carries an onboarded_on
date per borrower (see app.monitoring_history), and the very first time
a borrower is encountered (no trace exists yet), this script silently
BACKFILLS every cycle between 1 and "the cycle that should be current
right now given that onboarding date" — through the exact same
trigger_cycle() pipeline as any other cycle, not a shortcut — before
reporting this run's actual current cycle. A borrower that already has
trace history just advances by one cycle as before; the backfill only
ever happens once, on first contact.
"""

import json

from app.config import DATA_DIR
from app.case_trace import get_next_cycle
from app.scheduler import trigger_cycle
from app.monitoring_history import compute_target_cycle

RECORDS_PATH = DATA_DIR / "records.json"


def load_active_borrowers() -> list:
    """Loads borrower IDs from data/records.json — the project's
    existing borrower source of truth, not a separate hardcoded list.
    records.json currently has no active/inactive field (verified by
    inspection), so every record is treated as active; if that field is
    added later, filter on it here."""
    records = json.loads(RECORDS_PATH.read_text())
    return [r["id"] for r in records]


def _onboarded_on(borrower_id: str):
    records = json.loads(RECORDS_PATH.read_text())
    record = next((r for r in records if r["id"] == borrower_id), None)
    return record.get("onboarded_on") if record else None


def _seed_history_if_needed(borrower_id: str) -> int:
    """Called once per borrower, only when get_next_cycle() is 1 (no
    trace exists at all yet). Backfills cycles 1..(target-1) through the
    real pipeline, silently, then returns target — the cycle THIS run
    should actually process and report. Returns 1 (no backfill) if the
    borrower has no onboarded_on date, or if today's date puts them at
    cycle 1 anyway (freshly onboarded)."""
    onboarded_on = _onboarded_on(borrower_id)
    if not onboarded_on:
        return 1

    target = compute_target_cycle(onboarded_on)
    if target <= 1:
        return 1

    print(f"  (seeding {target - 1} cycle(s) of history from onboarding date {onboarded_on}...)")
    for c in range(1, target):
        trigger_cycle(borrower_id, c)
    return target


def run_portfolio_monitoring_cycle() -> dict:
    """Runs one monitoring cycle for every active borrower. Returns a
    summary dict; also prints a demo-friendly report as it goes. One
    borrower's failure never stops the rest of the portfolio — caught
    and reported per-borrower, not raised."""
    borrowers = load_active_borrowers()

    print("=" * 50)
    print("MSME PORTFOLIO MONITORING")
    print("=" * 50)

    completed = 0
    failed = 0
    results = []

    for borrower_id in borrowers:
        previous_cycle = get_next_cycle(borrower_id) - 1

        if previous_cycle == 0:
            # No trace at all yet — this is a first encounter. Seed
            # history up to "today"'s due cycle (see module docstring),
            # then treat that as this run's actual current cycle.
            seeded_cycle = _seed_history_if_needed(borrower_id)
            next_cycle = seeded_cycle
            previous_cycle = seeded_cycle - 1
        else:
            next_cycle = get_next_cycle(borrower_id)

        print(f"\n{borrower_id}")
        print(f"Previous cycle: {previous_cycle if previous_cycle > 0 else '(none yet)'}")
        print(f"Running cycle: {next_cycle}")

        try:
            outcome = trigger_cycle(borrower_id, next_cycle)
        except Exception as exc:
            failed += 1
            print(f"Status: failed")
            print(f"  ({type(exc).__name__}: {exc})")
            results.append({"borrower_id": borrower_id, "status": "failed", "error": str(exc)})
            continue

        if outcome["status"] == "skipped_already_running":
            # Shouldn't normally happen in a single sequential portfolio
            # run, but handled rather than assumed away — the lock is
            # the source of truth, not this script's own bookkeeping.
            print("Status: skipped_already_running")
            results.append({"borrower_id": borrower_id, "status": "skipped_already_running"})
            continue

        result = outcome["result"]
        completed += 1
        print(f"Status: completed")
        print(f"Tier: {result['tier']}")
        print(f"Composite: {result['composite_score']}")
        if result.get("case_action") and result["case_action"] != "log_only":
            print(f"Case action: {result['case_action']}")
        results.append({"borrower_id": borrower_id, "status": "completed", "result": result})

    print("\n" + "=" * 50)
    print("MONITORING SUMMARY")
    print("=" * 50)
    print(f"Borrowers processed: {len(borrowers)}")
    print(f"Completed: {completed}")
    print(f"Failed: {failed}")

    return {
        "borrowers_processed": len(borrowers),
        "completed": completed,
        "failed": failed,
        "results": results,
    }


if __name__ == "__main__":
    run_portfolio_monitoring_cycle()