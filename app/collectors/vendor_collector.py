"""
Vendor Payment Collector — derives raw facts (payment counts, late ratio)
from the same AA transaction data the Cash Flow collector uses. Returns
facts, not a score — normalization is Day 5's responsibility.
"""

from app.clients.aa_client import get_aa_client


def collect_vendor_signal(borrower_id: str, cycle: int) -> dict:
    data = get_aa_client().fetch_aa_data(borrower_id, cycle)
    txns = data["recent_transactions"]

    if txns is None:
        # Genuinely unavailable this cycle (not "zero transactions happened")
        raise ValueError(
            f"[mock] vendor_payment signal unavailable for {borrower_id}, cycle {cycle} "
            "(insufficient_data archetype)."
        )

    total = len(txns)
    late = sum(1 for t in txns if not t["on_time"])
    on_time = total - late
    late_ratio = round(late / total, 3) if total else 0.0

    return {
        "total_vendor_payments": total,
        "late_vendor_payments": late,
        "on_time_vendor_payments": on_time,
        "late_payment_ratio": late_ratio,
        "source": data["source"],
    }