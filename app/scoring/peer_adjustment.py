"""
Day 9 — Peer-Relative Adjustment + peer-size fallback.

Compares a borrower's period-over-period composite move to their sector
peers' average move, to attribute the cause as peer_driven vs
borrower_specific. This module only ever ADDS an attribution label — it
never changes the tier itself. The critical floor (from Days 4-8) always
wins: once composite < CRITICAL_FLOOR, attribution is always
critical_floor_override, regardless of what peers did.

Simplifying assumption: "cycle N" is treated as the same monitoring
period across every borrower in a sector (cycle numbers are
calendar-aligned across the portfolio) — matching how records.json /
golden_archetypes.json are already structured. A real system would key
this off cycle_period / a calendar date instead of a raw integer index;
worth revisiting once cases carry real dates.

KNOWN DATASET LIMITATION: only the auto_ancillary sector has 3 members
(so 2 peers per borrower). Every other sector (food_processing, textiles,
logistics) has exactly 2 members — 1 peer each — which can never reach
MIN_PEER_GROUP_SIZE=2. That means MSME-1007 (peer_wide_shock), whose
whole archetype is designed to test peer_driven attribution, will always
hit the peer-size fallback in this 9-borrower dataset. This isn't a bug —
it's an honest consequence of a small synthetic portfolio. Revisit if you
want that archetype's peer_driven case to actually be exercisable (e.g.
add 1-2 more logistics borrowers, or lower MIN_PEER_GROUP_SIZE to 1 with
a documented caveat about statistical meaningfulness).

Peer composite scores are computed via a STATELESS peek (collectors ->
normalize -> calculate_composite only) — deliberately bypassing the gate/
tier pipeline, so scoring one borrower never mutates a PEER borrower's own
gate streak or tier-smoothing state as a side effect.
"""

import json

from app.config import DATA_DIR
from app.clients.aa_client_base import AAConnectionError
from app.collectors.gst_collector import collect_gst_filing_delay
from app.collectors.cashflow_collector import collect_cashflow_signal
from app.collectors.vendor_collector import collect_vendor_signal
from app.collectors.industry_collector import collect_industry_signal
from app.scoring.normalizers import normalize_from_collector_output
from app.scoring.composite import calculate_composite
from app.scoring.constants import CRITICAL_FLOOR

RECORDS_PATH = DATA_DIR / "records.json"
MIN_PEER_GROUP_SIZE = 2  # fewer valid peer deltas than this -> skip peer adjustment
ATTRIBUTION_TOLERANCE = 5.0  # matches golden_archetypes.py's attribute()

_COLLECTORS = {
    "gst_filing_delay": collect_gst_filing_delay,
    "cash_flow": collect_cashflow_signal,
    "vendor_payment": collect_vendor_signal,
    "industry_index": collect_industry_signal,
}


def _load_records() -> list:
    with open(RECORDS_PATH) as f:
        return json.load(f)


def _peers_in_sector(borrower_id: str) -> list:
    records = _load_records()
    me = next((r for r in records if r["id"] == borrower_id), None)
    if me is None:
        raise ValueError(f"No record found for {borrower_id}")
    return [r["id"] for r in records if r["sector"] == me["sector"] and r["id"] != borrower_id]


def _peek_composite(borrower_id: str, cycle: int):
    """Stateless: collectors -> normalize -> composite. Does NOT touch
    gate/tier state — safe to call for peer borrowers without side
    effects on their own scoring history."""
    if cycle < 1:
        return None
    subscores = {}
    for signal_name, collector in _COLLECTORS.items():
        try:
            raw = collector(borrower_id, cycle)
            subscores[signal_name] = normalize_from_collector_output(signal_name, raw)
        except (AAConnectionError, ValueError):
            subscores[signal_name] = None
    return calculate_composite(subscores)


def compute_peer_avg_delta(borrower_id: str, cycle: int):
    """Returns (peer_avg_delta, peer_group_size). peer_avg_delta is None
    if too few peers have a valid delta this cycle (peer-size fallback)."""
    peers = _peers_in_sector(borrower_id)
    deltas = []
    for peer_id in peers:
        curr = _peek_composite(peer_id, cycle)
        prev = _peek_composite(peer_id, cycle - 1)
        if curr is not None and prev is not None:
            deltas.append(curr - prev)

    if len(deltas) < MIN_PEER_GROUP_SIZE:
        return None, len(deltas)

    return round(sum(deltas) / len(deltas), 1), len(deltas)


def attribute_change(borrower_id: str, cycle: int, composite, prior_composite) -> dict:
    """Returns {attribution, peer_avg_delta, peer_group_size}."""
    if composite is None or prior_composite is None:
        return {"attribution": None, "peer_avg_delta": None, "peer_group_size": 0}

    peer_avg_delta, peer_group_size = compute_peer_avg_delta(borrower_id, cycle)

    if composite < CRITICAL_FLOOR:
        # Critical floor always wins. Peer context is still computed and
        # reported for the record, but it can never soften a Red.
        return {
            "attribution": "critical_floor_override",
            "peer_avg_delta": peer_avg_delta,
            "peer_group_size": peer_group_size,
        }

    if peer_avg_delta is None:
        # Peer-size fallback — too few peers with valid data this cycle.
        return {
            "attribution": "borrower_specific",
            "peer_avg_delta": None,
            "peer_group_size": peer_group_size,
        }

    delta = round(composite - prior_composite, 1)
    attribution = (
        "peer_driven" if abs(delta - peer_avg_delta) <= ATTRIBUTION_TOLERANCE else "borrower_specific"
    )
    return {"attribution": attribution, "peer_avg_delta": peer_avg_delta, "peer_group_size": peer_group_size}


if __name__ == "__main__":
    # Smoke test across a few borrowers/cycles.
    cases = [
        ("MSME-1004", 3, "auto_ancillary, 2 peers available — sharp_decline critical floor"),
        ("MSME-1003", 5, "textiles, only 1 peer — expect peer-size fallback"),
        ("MSME-1007", 3, "logistics, only 1 peer — expect peer-size fallback (known limitation)"),
    ]
    for borrower_id, cycle, note in cases:
        peers = _peers_in_sector(borrower_id)
        curr = _peek_composite(borrower_id, cycle)
        prev = _peek_composite(borrower_id, cycle - 1)
        result = attribute_change(borrower_id, cycle, curr, prev)
        print(f"{borrower_id} cycle {cycle} ({note})")
        print(f"  peers={peers}  composite={curr}  prior={prev}")
        print(f"  -> {result}")