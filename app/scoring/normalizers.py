"""
Normalizers — convert each collector's raw reading into a 0-100 health
score (0 = worst, 100 = healthiest), matching the convention already used
throughout golden_archetypes.json.

Each formula's inverse is what the corresponding mock (aa_client_mock.py /
gst_mock_historical.py) was built to approximate — so round-tripping a
mock reading through its normalizer should land close to (not
necessarily exact — small realistic noise is intentional) the original
golden-trace subscore. This is what Day 8's evaluator will check at scale.
"""


def _clamp(x: float) -> int:
    return max(0, min(100, round(x)))


def normalize_gst_filing_delay(filing_delay_days: float) -> int:
    """0 days late -> 100. 30+ days late -> 0. Linear in between.
    Inverse of the formula used in gst_mock_historical.py."""
    score = 100 * (1 - filing_delay_days / 30)
    return _clamp(score)


def normalize_vendor_payment(late_payment_ratio: float) -> int:
    """0% late -> 100. 100% late -> 0."""
    score = 100 * (1 - late_payment_ratio)
    return _clamp(score)


def normalize_cash_flow(current_balance: float, avg_monthly_balance: float) -> int:
    """current_balance as a % of the borrower's own slow-moving average
    balance — NOT normalized against an absolute rupee figure, since
    ₹50,000 means something different for different MSMEs. Requires
    avg_monthly_balance to be a stable baseline, not derived from the
    current cycle (see the fix in aa_client_mock.py's build_archetype)."""
    if avg_monthly_balance <= 0:
        return 0
    score = (current_balance / avg_monthly_balance) * 100
    return _clamp(score)


def normalize_industry(industry_growth_pct: float) -> int:
    """KNOWN GAP: no real industry/sector data source is integrated yet
    (industry_collector.py is a flat placeholder — see its docstring).
    Formula assumed: 0% growth -> 50 (neutral baseline), scaled +/-1.5
    points of score per 1% growth, clamped to 0-100. This is a guess, not
    derived from anything — revisit the moment a real industry-index
    source is picked, and expect this signal to show up as a mismatch in
    Day 8's evaluator report until then (that's expected, not a bug)."""
    score = 50 + (industry_growth_pct * 1.5)
    return _clamp(score)


# ---------------------------------------------------------------------------
# Dispatcher — takes a collector's raw output dict straight through to a
# 0-100 score, so callers don't need to know each formula's exact inputs.
# ---------------------------------------------------------------------------

def normalize_from_collector_output(signal_name: str, raw: dict) -> int:
    if signal_name == "gst_filing_delay":
        return normalize_gst_filing_delay(raw["filing_delay_days"])
    if signal_name == "vendor_payment":
        return normalize_vendor_payment(raw["late_payment_ratio"])
    if signal_name == "cash_flow":
        return normalize_cash_flow(raw["current_balance"], raw["avg_monthly_balance"])
    if signal_name == "industry_index":
        return normalize_industry(raw["industry_growth"])
    raise ValueError(f"Unknown signal: {signal_name}")


if __name__ == "__main__":
    # Round-trip smoke test against a few golden-trace cycles.
    from app.collectors.gst_collector import collect_gst_filing_delay
    from app.collectors.cashflow_collector import collect_cashflow_signal
    from app.collectors.vendor_collector import collect_vendor_signal

    cases = [
        ("MSME-1001", 1, {"gst_filing_delay": 88, "cash_flow": 85, "vendor_payment": 90}),
        ("MSME-1003", 4, {"gst_filing_delay": 50, "cash_flow": 42, "vendor_payment": 55}),
        ("MSME-1004", 3, {"gst_filing_delay": 25, "cash_flow": 8, "vendor_payment": 12}),
    ]
    for borrower_id, cycle, expected in cases:
        gst_raw = collect_gst_filing_delay(borrower_id, cycle)
        cf_raw = collect_cashflow_signal(borrower_id, cycle)
        vp_raw = collect_vendor_signal(borrower_id, cycle)
        print(f"--- {borrower_id} cycle {cycle} ---")
        print(f"  gst_filing_delay: got {normalize_from_collector_output('gst_filing_delay', gst_raw)}, expected {expected['gst_filing_delay']}")
        print(f"  cash_flow:        got {normalize_from_collector_output('cash_flow', cf_raw)}, expected {expected['cash_flow']}")
        print(f"  vendor_payment:   got {normalize_from_collector_output('vendor_payment', vp_raw)}, expected {expected['vendor_payment']}")