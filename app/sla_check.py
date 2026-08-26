"""
Day 18 — SLA Timeout Check.

An open case (Amber/Red, per app.case_lifecycle) that sits untouched for
too many cycles is a process failure, not just a risk signal — someone
was supposed to act on it. check_sla() counts how many cycles a case has
been continuously open and flags it once that exceeds SLA_CYCLES_LIMIT,
so the workflow layer can escalate instead of silently re-logging the
same open case forever.

Deliberately reads app.case_lifecycle's own persisted history rather than
keeping separate state — same reasoning as gates.py reusing hist["last"]
for Day 13's cache: don't build a second store for data that's already
tracked.
"""

from app.case_lifecycle import load_case_record

SLA_CYCLES_LIMIT = 3  # placeholder — cycles a case may stay open before escalation


def check_sla(borrower_id: str, current_cycle: int) -> dict:
    """Returns {"case_id", "cycles_open", "sla_breached"}."""
    record = load_case_record(borrower_id)

    if record["case_status"] != "open":
        return {"case_id": record["open_case_id"], "cycles_open": 0, "sla_breached": False}

    open_case_id = record["open_case_id"]
    opened_cycle = None
    # Walk history backwards to find when the CURRENTLY open case_id was
    # opened — not just the first "case_opened" ever, in case an earlier
    # case for this borrower was already resolved.
    for h in reversed(record["history"]):
        if h.get("case_id") == open_case_id and h.get("action") == "case_opened":
            opened_cycle = h["cycle"]
            break

    if opened_cycle is None:
        # Defensive fallback — shouldn't happen given case_lifecycle.py's
        # own invariants, but don't crash the workflow over it.
        return {"case_id": open_case_id, "cycles_open": None, "sla_breached": False}

    cycles_open = current_cycle - opened_cycle + 1
    return {
        "case_id": open_case_id,
        "cycles_open": cycles_open,
        "sla_breached": cycles_open > SLA_CYCLES_LIMIT,
    }


if __name__ == "__main__":
    from app.case_lifecycle import reset_case_record, get_or_create_case

    reset_case_record("MSME-SLA-TEST")
    get_or_create_case("MSME-SLA-TEST", 1, "Amber")  # opens
    get_or_create_case("MSME-SLA-TEST", 2, "Amber")  # still open
    get_or_create_case("MSME-SLA-TEST", 3, "Amber")  # still open
    r3 = check_sla("MSME-SLA-TEST", 3)
    print("cycle 3 (3 cycles open, limit 3):", r3)
    assert r3["sla_breached"] is False

    get_or_create_case("MSME-SLA-TEST", 4, "Amber")  # still open
    r4 = check_sla("MSME-SLA-TEST", 4)
    print("cycle 4 (4 cycles open, limit 3):", r4)
    assert r4["sla_breached"] is True

    reset_case_record("MSME-SLA-TEST")
    print("SLA check smoke test passed.")