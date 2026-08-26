"""
Mock historical GST filing-delay data.

Your real sandbox.co.in integration confirmed working, but it returns
*current* registration status only (Active/Cancelled/etc) — it has no
filing-return history, so it can't tell you "how many days late was cycle
3's GST filing" the way golden evaluation needs. Until a real GST
return-history API is integrated, this mirrors app/clients/aa_client_mock.py:
reverse-engineer a plausible raw "days late" value from the target
gst_filing_delay sub-score.

DATA SOURCE: cycle data comes from app.mocks.monitoring_dataset, NOT
golden_archetypes.json directly (that redirect happened when continuous
monitoring was added — see that module's docstring for why this doesn't
change evaluator.py's results: monitoring_dataset.json bootstraps as an
exact copy of golden_archetypes.json, and evaluator.py only ever asks
for cycles that already existed in that original copy).

Normalization formula assumed (must match app/scoring/normalizers.py
exactly once Day 5 is built — this is the inverse of it):
    score = max(0, 100 * (1 - delay_days / 30))
    =>  delay_days = 30 * (1 - score / 100)
"""

from app.mocks.monitoring_dataset import get_archetype_entry, get_or_generate_cycle


def get_mock_filing_delay(borrower_id: str, cycle: int) -> dict:
    archetype = get_archetype_entry(borrower_id)
    if archetype is None:
        raise ValueError(f"No golden-trace archetype found for {borrower_id}.")

    cycle_data = get_or_generate_cycle(borrower_id, cycle)

    score = cycle_data["subscores"].get("gst_filing_delay")
    if score is None:
        # Mirrors the insufficient_data archetype — a real filing-history
        # source could genuinely come back empty for a cycle too.
        raise ValueError(
            f"gst_filing_delay unavailable for {borrower_id}, cycle {cycle} "
            "(insufficient_data archetype)."
        )

    delay_days = round(30 * (1 - score / 100), 1)
    return {"filing_delay_days": max(0.0, delay_days), "source": "mock_historical"}