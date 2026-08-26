"""
Case Trace Retrieval Store.

Two retrieval modes:

1. get_history()
   Complete chronological history.

2. retrieve_trace()
   Similarity-ranked fuzzy retrieval for questions such as:
   "when did this borrower become Red?"

The TF-IDF result is discovery only. Verified cycle facts must
come from app.case_trace.get_cycle_entry().
"""

from app.case_trace import (
    load_trace,
)

from app.rag.retrieval import (
    TfidfIndex,
)


# ============================================================
# SEARCH TEXT
# ============================================================

def _entry_to_text(
    entry: dict,
) -> str:

    tier = (
        entry.get("tier")
        or "insufficient data"
    )

    return (
        f"cycle {entry.get('cycle')} "
        f"tier {tier} "
        f"composite score "
        f"{entry.get('composite_score')} "
        f"raw tier {entry.get('raw_tier')} "
        f"data availability "
        f"{entry.get('data_availability')} "
        f"case action "
        f"{entry.get('case_action')} "
        f"case lifecycle action "
        f"{entry.get('case_lifecycle_action')} "
        f"signal sources "
        f"{entry.get('signal_sources')} "
        f"gate status "
        f"{entry.get('gate_status')} "
        f"subscores "
        f"{entry.get('subscores')}"
    )


# ============================================================
# INDEX
# ============================================================

def build_borrower_index(
    borrower_id: str,
) -> TfidfIndex:

    index = TfidfIndex()

    trace = load_trace(
        borrower_id
    )

    for entry in trace:

        cycle = entry.get(
            "cycle"
        )

        index.add(
            f"{borrower_id}#cycle{cycle}",
            _entry_to_text(entry),
            metadata={
                "borrower_id": borrower_id,
                "cycle": cycle,
            },
        )

    index.build()

    return index


# ============================================================
# COMPLETE HISTORY
# ============================================================

def get_history(
    borrower_id: str,
) -> list:

    trace = load_trace(
        borrower_id
    )

    return sorted(
        trace,
        key=lambda entry: (
            entry.get(
                "cycle"
            )
            if entry.get(
                "cycle"
            ) is not None
            else -1
        ),
    )


# ============================================================
# FUZZY RETRIEVAL
# ============================================================

def retrieve_trace(
    borrower_id: str,
    query: str,
    k: int = 3,
) -> list:

    index = build_borrower_index(
        borrower_id
    )

    return index.retrieve(
        query,
        k=k,
    )


# ============================================================
# FORMATTING
# ============================================================

def format_history(
    borrower_id: str,
) -> str:

    history = get_history(
        borrower_id
    )

    if not history:

        return (
            f"No monitoring history found "
            f"for {borrower_id}."
        )

    lines = [
        f"Historical monitoring cycles "
        f"for {borrower_id}:"
    ]

    for entry in history:

        cycle = entry.get(
            "cycle"
        )

        tier = (
            entry.get(
                "tier"
            )
            or "insufficient data"
        )

        score = entry.get(
            "composite_score"
        )

        lifecycle = entry.get(
            "case_lifecycle_action"
        )

        line = (
            f"- Cycle {cycle}: "
            f"tier={tier}"
        )

        if score is not None:

            line += (
                f", composite={score}"
            )

        if lifecycle:

            line += (
                f", case_action={lifecycle}"
            )

        lines.append(
            line
        )

    return "\n".join(
        lines
    )


# ============================================================
# SMOKE TEST
# ============================================================

if __name__ == "__main__":

    from app.case_trace import (
        reset_trace,
        append_trace_entry,
    )

    test_id = (
        "MSME-TRACESTORE-TEST"
    )

    reset_trace(
        test_id
    )

    for cycle, tier, score in [
        (1, "Green", 84.2),
        (2, "Amber", 61.5),
        (3, "Red", 38.0),
    ]:

        append_trace_entry(
            test_id,
            {
                "cycle": cycle,
                "tier": tier,
                "composite_score": score,
                "case_lifecycle_action": (
                    "case_updated"
                ),
                "gate_status": {},
            },
        )

    history = get_history(
        test_id
    )

    assert [
        x["cycle"]
        for x in history
    ] == [1, 2, 3]

    print(
        format_history(
            test_id
        )
    )

    reset_trace(
        test_id
    )

    print(
        "Trace store smoke test passed."
    )