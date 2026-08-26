"""
Day 24 — simulate_scenario.

Runs a hypothetical "what if signal X were Y" scenario for a borrower
WITHOUT touching any persisted state — no gate streaks, no tier
smoothing state, no case lifecycle record. That's the entire point of a
what-if: it must be pure, or repeated simulations would corrupt the
borrower's real scoring history.

Concretely, this means it does NOT call app.scoring.gates.update_gate()
or app.scoring.tiering.smoothed_tier() — both of those WRITE to
data/case_state/<borrower_id>.json as a side effect. Composite
calculation (app.scoring.composite.calculate_composite) is safe to
reuse directly, since it's already pure (no persistence). Tier banding
here uses tiering.raw_band() only — the pure threshold function, not the
persisting smoothed_tier() — which means a simulated tier is the RAW
band, deliberately NOT reflecting cycle-over-cycle smoothing/decline-
streak logic. That's a real, documented simplification: modeling
"what would smoothing say" would require pretending a hypothetical cycle
actually happened and was persisted, which is exactly what this function
must not do.
"""

from app.case_trace import load_trace
from app.scoring.composite import calculate_composite
from app.scoring.tiering import raw_band


def run_simulation(borrower_id: str, hypothetical_overrides: dict) -> dict:
    """hypothetical_overrides: {signal_name: hypothetical_score}. Any
    signal not overridden uses the borrower's latest FRESH subscore from
    case_trace (not a cached-fallback value — simulating on top of a
    known-stale reading would compound one assumption on another).

    Returns {"borrower_id", "based_on_cycle", "simulated_subscores",
    "simulated_composite", "simulated_tier", "note"}."""
    trace = load_trace(borrower_id)
    if not trace:
        return {
            "borrower_id": borrower_id,
            "based_on_cycle": None,
            "simulated_subscores": None,
            "simulated_composite": None,
            "simulated_tier": None,
            "note": "no trace history — nothing to simulate from",
        }

    latest = trace[-1]
    base_subscores = dict(latest.get("subscores", {}))
    sources = latest.get("signal_sources", {})

    # Warn (don't block) if we're basing the simulation on a stale
    # cached-fallback value for a signal that wasn't explicitly
    # overridden — the caller should know that assumption is baked in.
    stale_signals_used = [
        sig for sig, src in sources.items()
        if src == "cached_fallback" and sig not in hypothetical_overrides
    ]

    simulated_subscores = {**base_subscores, **hypothetical_overrides}
    simulated_composite = calculate_composite(simulated_subscores)
    simulated_tier = raw_band(simulated_composite) if simulated_composite is not None else None

    note = "raw threshold band only — does not include cycle-over-cycle tier smoothing"
    if stale_signals_used:
        note += f"; based partly on stale cached values for: {stale_signals_used}"

    return {
        "borrower_id": borrower_id,
        "based_on_cycle": latest["cycle"],
        "simulated_subscores": simulated_subscores,
        "simulated_composite": simulated_composite,
        "simulated_tier": simulated_tier,
        "note": note,
    }


if __name__ == "__main__":
    from app.case_trace import reset_trace, append_trace_entry

    reset_trace("MSME-SIM-TEST")
    append_trace_entry("MSME-SIM-TEST", {
        "cycle": 1,
        "subscores": {"gst_filing_delay": 80, "cash_flow": 78, "vendor_payment": 82, "industry_index": 50},
        "signal_sources": {"gst_filing_delay": "fresh", "cash_flow": "fresh",
                            "vendor_payment": "fresh", "industry_index": "fresh"},
    })

    r1 = run_simulation("MSME-SIM-TEST", {})  # no overrides — should mirror latest cycle
    print("no override:", r1)
    assert r1["simulated_composite"] is not None

    r2 = run_simulation("MSME-SIM-TEST", {"cash_flow": 20})  # force a big drop
    print("cash_flow crashed:", r2)
    assert r2["simulated_composite"] < r1["simulated_composite"]

    r3 = run_simulation("MSME-NEVER-SCORED", {})
    print("no history at all:", r3)
    assert r3["simulated_tier"] is None

    reset_trace("MSME-SIM-TEST")
    print("simulate_scenario smoke test passed.")