"""
Day 15 — Case Trace store.

Persists a structured, append-only record of every scoring cycle's
DETERMINISTIC outcome (gate status, composite, tier, signal provenance,
case lifecycle action) per borrower — the ground-truth facts the
Explanation Agent (Days 17-18) will quote when explaining a decision.

Deliberately NOT retrieval/embedding-based by itself — see
app/rag/trace_store.py for the semantic-search layer built ON TOP of
this. This module is the source of truth; trace_store.py is just an
index into it. Keeping the facts in a plain append-only JSON log (not
only inside a similarity-searchable store) matters for the
trace-vs-policy separation guardrail: a fact used in an explanation must
trace back to an exact, byte-for-byte record here, not to a
similarity-retrieved (and therefore possibly wrong-cycle) chunk.

State: data/case_traces/<borrower_id>.json — deliberately separate from
both data/case_state/ (Day 6's gate/tier scoring state) and
data/cases/ (Day 11's workflow/case-lifecycle state), same reasoning as
those two being kept apart from each other: each store can be
reset/rebuilt independently.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

from app.config import DATA_DIR

TRACE_DIR = DATA_DIR / "case_traces"
TRACE_DIR.mkdir(parents=True, exist_ok=True)


def _trace_path(borrower_id: str) -> Path:
    return TRACE_DIR / f"{borrower_id}.json"


def load_trace(borrower_id: str) -> list:
    path = _trace_path(borrower_id)
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def append_trace_entry(borrower_id: str, entry: dict) -> dict:
    """entry is expected to be exactly what run_scoring() returns for
    this cycle (or a subset of it) — this function doesn't reshape it,
    just stamps it with recorded_at and appends it. Returns the stored
    entry (with the timestamp added)."""
    trace = load_trace(borrower_id)
    stored_entry = {**entry, "recorded_at": datetime.now(timezone.utc).isoformat()}
    trace.append(stored_entry)
    with open(_trace_path(borrower_id), "w") as f:
        json.dump(trace, f, indent=2)
    return stored_entry


def get_cycle_entry(borrower_id: str, cycle: int):
    """Exact, non-fuzzy lookup — this is what the Explanation Agent must
    call for 'what happened this cycle', NOT the RAG retriever, so a
    stated fact can never come from the wrong cycle. Returns None if no
    entry exists for that cycle."""
    for entry in load_trace(borrower_id):
        if entry.get("cycle") == cycle:
            return entry
    return None


def reset_trace(borrower_id: str = None) -> None:
    """Wipe one borrower's trace, or ALL borrowers' if None — same
    reproducibility purpose as gates.py's reset_case_state()."""
    if borrower_id is not None:
        path = _trace_path(borrower_id)
        if path.exists():
            path.unlink()
        return
    for f in TRACE_DIR.glob("*.json"):
        f.unlink()


def get_next_cycle(borrower_id: str) -> int:
    """Returns the next cycle number for this borrower, for the
    portfolio monitoring runner (scripts/run_monitoring_cycle.py).

    Deliberately max(existing cycle numbers) + 1, NOT len(trace) + 1 —
    those are only equivalent if cycles are guaranteed gap-free and
    strictly sequential, which isn't actually guaranteed anywhere in
    this codebase (a borrower could in principle have a trace with a
    gap, e.g. from manual state surgery during testing). max()+1 is
    correct regardless; len()+1 would silently reuse or skip a cycle
    number if a gap ever existed. No trace yet -> cycle 1."""
    trace = load_trace(borrower_id)
    if not trace:
        return 1
    return max(entry["cycle"] for entry in trace) + 1


if __name__ == "__main__":
    reset_trace("MSME-TRACE-TEST")
    append_trace_entry("MSME-TRACE-TEST", {"cycle": 1, "tier": "Green", "composite_score": 84.2})
    append_trace_entry("MSME-TRACE-TEST", {"cycle": 2, "tier": "Amber", "composite_score": 61.5})
    print("full trace:", load_trace("MSME-TRACE-TEST"))
    print("cycle 2 exact lookup:", get_cycle_entry("MSME-TRACE-TEST", 2))
    print("cycle 9 (missing):", get_cycle_entry("MSME-TRACE-TEST", 9))
    reset_trace("MSME-TRACE-TEST")

    print("next cycle, no trace yet:", get_next_cycle("MSME-NEXTCYCLE-TEST"))
    assert get_next_cycle("MSME-NEXTCYCLE-TEST") == 1
    append_trace_entry("MSME-NEXTCYCLE-TEST", {"cycle": 1})
    append_trace_entry("MSME-NEXTCYCLE-TEST", {"cycle": 2})
    append_trace_entry("MSME-NEXTCYCLE-TEST", {"cycle": 5})  # deliberate gap
    print("next cycle after 1,2,5 (gap):", get_next_cycle("MSME-NEXTCYCLE-TEST"))
    assert get_next_cycle("MSME-NEXTCYCLE-TEST") == 6  # max()+1, not len()+1 (would've been 4)
    reset_trace("MSME-NEXTCYCLE-TEST")
    print("get_next_cycle smoke test passed.")