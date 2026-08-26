"""
Cash Flow Collector — thin wrapper around the AA client. Returns raw
balance facts only; normalization into a 0-100 score happens in Day 5
(app/scoring/normalizers.py), not here.
"""

from app.clients.aa_client import get_aa_client


def collect_cashflow_signal(borrower_id: str, cycle: int) -> dict:
    data = get_aa_client().fetch_aa_data(borrower_id, cycle)
    return {
        "current_balance": data["summary"]["current_balance"],
        "avg_monthly_balance": data["summary"]["avg_monthly_balance"],
        "currency": data["summary"]["currency"],
        "source": data["source"],
    }