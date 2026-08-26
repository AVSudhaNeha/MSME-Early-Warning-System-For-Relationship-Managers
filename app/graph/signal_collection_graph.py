"""
Day 10 — LangGraph fan-out/fan-in for the Signal Collectors.

Replaces the plain Python loop in engine.py's run_scoring() with an actual
LangGraph graph: 4 independent collector nodes fan out from START, each
runs in parallel, and all 4 fan into a "merge" node before the graph ends.
This matches the proposal's §8 spec: "Signal collectors (parallel) — one
small agent per data source."

Behavior is intentionally IDENTICAL to the Day 8/9 sequential version —
this is a pure structural change. Each node still calls the exact same
collector + normalizer functions and produces the exact same result for
a signal (success -> 0-100 score, failure -> None). Re-running the golden
evaluator after this change should show no difference in tier/composite
results — if it does, something about the port is wrong, not something
about the graph."""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END

from app.clients.aa_client_base import AAConnectionError
from app.collectors.gst_collector import collect_gst_filing_delay
from app.collectors.cashflow_collector import collect_cashflow_signal
from app.collectors.vendor_collector import collect_vendor_signal
from app.collectors.industry_collector import collect_industry_signal
from app.scoring.normalizers import normalize_from_collector_output


def _merge_subscores(a: dict, b: dict) -> dict:
    """Reducer: each collector node returns a partial {signal: score} dict;
    this merges them as they complete, so 4 nodes writing to the same
    state key don't clobber each other."""
    merged = dict(a)
    merged.update(b)
    return merged


class CollectionState(TypedDict):
    borrower_id: str
    cycle: int
    subscores: Annotated[dict, _merge_subscores]
    # Day 13 — WHY a signal came back None matters, not just that it did:
    # AAConnectionError means the source itself is unreachable this cycle
    # (a transient outage, cache-eligible); ValueError means the collector
    # reached its source fine but there's genuinely no data for this cycle
    # (the insufficient_data archetype's deliberate scenario — must stay
    # unavailable, NOT be papered over by a cache hit, or the Data
    # Availability Check it's designed to test stops meaning anything).
    failure_reasons: Annotated[dict, _merge_subscores]


def _run_collector(signal_name: str, collector_fn, state: CollectionState) -> dict:
    """Shared logic for every collector node — same try/except behavior
    as engine.py's old _collect_and_normalize(), just as a graph node,
    now also recording WHY a failure happened (see CollectionState note)."""
    try:
        raw = collector_fn(state["borrower_id"], state["cycle"])
        score = normalize_from_collector_output(signal_name, raw)
        reason = None
    except AAConnectionError:
        score, reason = None, "connection_outage"
    except ValueError:
        score, reason = None, "insufficient_data"
    return {
        "subscores": {signal_name: score},
        "failure_reasons": {signal_name: reason},
    }


def gst_node(state: CollectionState) -> dict:
    return _run_collector("gst_filing_delay", collect_gst_filing_delay, state)


def cashflow_node(state: CollectionState) -> dict:
    return _run_collector("cash_flow", collect_cashflow_signal, state)


def vendor_node(state: CollectionState) -> dict:
    return _run_collector("vendor_payment", collect_vendor_signal, state)


def industry_node(state: CollectionState) -> dict:
    return _run_collector("industry_index", collect_industry_signal, state)


def merge_node(state: CollectionState) -> dict:
    """Fan-in point — no-op by the time this runs (the reducer already
    merged all 4 collectors' results), but kept as an explicit node so
    Day 11's Case Lifecycle Check has a clear place to hook in right
    after signal collection completes, rather than burying it in a
    collector node."""
    return {}


def build_signal_collection_graph():
    graph = StateGraph(CollectionState)
    graph.add_node("gst", gst_node)
    graph.add_node("cashflow", cashflow_node)
    graph.add_node("vendor", vendor_node)
    graph.add_node("industry", industry_node)
    graph.add_node("merge", merge_node)

    # Fan-out: all 4 collectors start in parallel from START
    graph.add_edge(START, "gst")
    graph.add_edge(START, "cashflow")
    graph.add_edge(START, "vendor")
    graph.add_edge(START, "industry")

    # Fan-in: merge waits for all 4 to complete before running
    graph.add_edge("gst", "merge")
    graph.add_edge("cashflow", "merge")
    graph.add_edge("vendor", "merge")
    graph.add_edge("industry", "merge")

    graph.add_edge("merge", END)

    return graph.compile()


_compiled_graph = build_signal_collection_graph()


def collect_all_signals(borrower_id: str, cycle: int) -> tuple[dict, dict]:
    """Public entry point — engine.py calls this instead of looping over
    collectors itself. Returns (subscores, failure_reasons):
    subscores is the same {signal_name: score_or_None} dict the old
    sequential version produced; failure_reasons is
    {signal_name: None | 'connection_outage' | 'insufficient_data'},
    used by Day 13's apply_cached_fallback() to decide which None's are
    cache-eligible."""
    result = _compiled_graph.invoke({
        "borrower_id": borrower_id,
        "cycle": cycle,
        "subscores": {},
        "failure_reasons": {},
    })
    return result["subscores"], result["failure_reasons"]


if __name__ == "__main__":
    # Smoke test: confirm the graph produces the same shape/values as the
    # old sequential loop for a known cycle.
    result, reasons = collect_all_signals("MSME-1001", 1)
    print("MSME-1001 cycle 1 via graph:", result)
    print("failure reasons:", reasons)
    expected = {"gst_filing_delay": 88, "cash_flow": 87, "vendor_payment": 88, "industry_index": 50}
    print("expected (approx, mock noise aside):", expected)