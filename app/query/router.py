"""
Day 22 — Router.

Pipeline:

    Query Understanding
          ↓
    Entity Resolution
          ↓
    Authorization
          ↓
    Handler Dispatch

Authorization ALWAYS occurs before borrower-specific retrieval.

Supported intents:

    explain_tier
    get_status
    get_history
    simulate_scenario
    ownership
    rm_portfolio
    hardship_guidance
    approval_confirmation

cycle_override is used by the evaluation harness to test a
specific historical cycle deterministically.
"""

import re

from app.query.query_understanding import (
    classify_query,
    needs_clarification,
)

from app.query.entity_resolution import (
    resolve_entity_from_text,
)

from app.query.authorization_gate import (
    check_authorization,
    check_rm_portfolio_authorization,
)

from app.rm_lookup import (
    resolve_rm_from_text,
)


# ============================================================
# MAIN ROUTER
# ============================================================

def route_query(
    user_id: str,
    text: str,
    hypothetical_overrides: dict = None,
    cycle_override: int = None,
) -> dict:

    classification = classify_query(
        text
    )

    if needs_clarification(
        classification
    ):
        return {
            "stage": "clarification_needed",
            "reason": "low_confidence_intent",
            "classification": classification,
        }

    intent = classification[
        "intent"
    ]

    # --------------------------------------------------------
    # RM PORTFOLIO
    # --------------------------------------------------------

    if intent == "rm_portfolio":

        return _route_rm_portfolio_query(
            user_id,
            text,
        )

    # --------------------------------------------------------
    # BORROWER RESOLUTION
    # --------------------------------------------------------

    entity_result = resolve_entity_from_text(
        text
    )

    if entity_result["status"] == "ambiguous":

        return {
            "stage": "clarification_needed",
            "reason": "ambiguous_borrower",
            "candidates": entity_result[
                "candidates"
            ],
        }

    if entity_result["status"] == "not_found":

        return {
            "stage": "clarification_needed",
            "reason": "borrower_not_identified",
            "classification": classification,
        }

    borrower_id = entity_result[
        "borrower_id"
    ]

    # --------------------------------------------------------
    # AUTHORIZATION
    # --------------------------------------------------------

    auth_result = check_authorization(
        user_id,
        borrower_id,
    )

    if not auth_result["authorized"]:

        return {
            "stage": "authorization_denied",
            "borrower_id": borrower_id,
            "reason": auth_result["reason"],
        }

    # --------------------------------------------------------
    # DISPATCH
    # --------------------------------------------------------

    return _dispatch(
        intent=intent,
        borrower_id=borrower_id,
        text=text,
        hypothetical_overrides=hypothetical_overrides,
        cycle_override=cycle_override,
    )


# ============================================================
# RM PORTFOLIO
# ============================================================

def _route_rm_portfolio_query(
    user_id: str,
    text: str,
) -> dict:

    rm_result = resolve_rm_from_text(
        text
    )

    if rm_result["status"] == "ambiguous":

        return {
            "stage": "clarification_needed",
            "reason": "ambiguous_rm",
            "candidates": rm_result[
                "candidates"
            ],
        }

    if rm_result["status"] == "not_found":

        return {
            "stage": "clarification_needed",
            "reason": "rm_not_identified",
        }

    rm_id = rm_result[
        "rm_id"
    ]

    auth_result = check_rm_portfolio_authorization(
        user_id,
        rm_id,
    )

    if not auth_result["authorized"]:

        return {
            "stage": "authorization_denied",
            "rm_id": rm_id,
            "reason": auth_result["reason"],
        }

    from app.rm_lookup import (
        get_rm_portfolio_status,
    )

    portfolio = get_rm_portfolio_status(
        rm_id
    )

    text_lower = text.lower()

    tier_filter = next(
        (
            tier
            for tier in (
                "green",
                "amber",
                "red",
            )
            if re.search(
                rf"\b{tier}\b",
                text_lower,
            )
        ),
        None,
    )

    return {
        "stage": "handled",
        "intent": "rm_portfolio",
        "rm_id": rm_id,
        "handler_result": {
            "portfolio": portfolio,
            "tier_filter": tier_filter,
        },
    }


# ============================================================
# DISPATCH
# ============================================================

def _dispatch(
    intent: str,
    borrower_id: str,
    text: str,
    hypothetical_overrides: dict,
    cycle_override: int = None,
) -> dict:

    from app.case_trace import load_trace

    trace = load_trace(
        borrower_id
    )

    if not trace:

        return {
            "stage": "handler_error",
            "reason": (
                f"no trace history for "
                f"{borrower_id}"
            ),
        }

    selected_entry = _select_entry(
        trace,
        cycle_override,
    )

    if selected_entry is None:

        return {
            "stage": "handler_error",
            "reason": (
                f"cycle {cycle_override} "
                f"not found for {borrower_id}"
            ),
        }

    # ========================================================
    # EXPLAIN TIER
    # ========================================================

    if intent == "explain_tier":

        from app.agents.explanation_agent import (
            generate_explanation,
        )

        cycle = selected_entry[
            "cycle"
        ]

        result = generate_explanation(
            borrower_id,
            cycle,
            question=text,
        )

        return {
            "stage": "handled",
            "intent": intent,
            "borrower_id": borrower_id,
            "handler_result": result,
        }

    # ========================================================
    # STATUS
    # ========================================================

    if intent == "get_status":

        result = dict(
            selected_entry
        )

        result["insufficient_data"] = (
            result.get(
                "data_availability"
            ) == "insufficient"
            or (
                result.get("tier") is None
                and result.get(
                    "composite_score"
                ) is None
            )
        )

        return {
            "stage": "handled",
            "intent": "get_status",
            "borrower_id": borrower_id,
            "handler_result": result,
        }

    # ========================================================
    # HISTORY
    # ========================================================

    if intent == "get_history":

        return _handle_history(
            borrower_id,
            text,
            trace,
        )

    # ========================================================
    # SIMULATION
    # ========================================================

    if intent == "simulate_scenario":

        from app.query.simulate_scenario import (
            run_simulation,
        )

        from app.query.whatif_abuse_check import (
            check_whatif_rate_limit,
        )

        overrides = (
            hypothetical_overrides
            or _extract_hypothetical_overrides(
                text
            )
        )

        limit_result = check_whatif_rate_limit(
            borrower_id
        )

        if limit_result["blocked"]:

            return {
                "stage": "rate_limited",
                "borrower_id": borrower_id,
                "reason": limit_result[
                    "reason"
                ],
            }

        result = run_simulation(
            borrower_id,
            overrides,
        )

        result["requested_overrides"] = (
            overrides
        )

        return {
            "stage": "handled",
            "intent": "simulate_scenario",
            "borrower_id": borrower_id,
            "handler_result": result,
        }

    # ========================================================
    # OWNERSHIP
    # ========================================================

    if intent == "ownership":

        from app.rm_lookup import (
            get_rm_for_borrower,
        )

        owner = get_rm_for_borrower(
            borrower_id
        )

        if owner is None:

            return {
                "stage": "handler_error",
                "reason": (
                    f"no RM ownership recorded "
                    f"for {borrower_id}"
                ),
            }

        return {
            "stage": "handled",
            "intent": "ownership",
            "borrower_id": borrower_id,
            "handler_result": owner,
        }

    # ========================================================
    # HARDSHIP / RESTRUCTURING
    # ========================================================

    if intent == "hardship_guidance":

        tier = (
            selected_entry.get(
                "tier"
            )
            or ""
        ).lower()

        # ----------------------------------------------------
        # Green borrower:
        # Do NOT invent hardship recommendations.
        # ----------------------------------------------------

        if tier == "green":

            return {
                "stage": "handled",
                "intent": "hardship_guidance",
                "borrower_id": borrower_id,
                "handler_result": {
                    "mode": "not_recommended",
                    "tier": selected_entry.get(
                        "tier"
                    ),
                    "composite_score": selected_entry.get(
                        "composite_score"
                    ),
                    "cycle": selected_entry.get(
                        "cycle"
                    ),
                    "reason": (
                        "Borrower is currently Green; "
                        "no hardship program is recommended "
                        "by the current risk policy."
                    ),
                },
            }

        # ----------------------------------------------------
        # Amber / Red:
        # Retrieve actual policy.
        # ----------------------------------------------------

        from app.agents.explanation_agent import (
            generate_policy_guidance,
        )

        result = generate_policy_guidance(
            borrower_id=borrower_id,
            cycle=selected_entry[
                "cycle"
            ],
            question=text,
        )

        return {
            "stage": "handled",
            "intent": "hardship_guidance",
            "borrower_id": borrower_id,
            "handler_result": result,
        }

    # ========================================================
    # APPROVAL CONFIRMATION
    # ========================================================

    if intent == "approval_confirmation":

        approval_fields = (
            "approval_status",
            "loan_approval_status",
            "restructuring_approval_status",
            "approved",
        )

        approval_found = False
        approval_value = None
        approval_field = None

        for field in approval_fields:

            if field in selected_entry:

                approval_found = True
                approval_value = selected_entry.get(
                    field
                )
                approval_field = field
                break

        return {
            "stage": "handled",
            "intent": "approval_confirmation",
            "borrower_id": borrower_id,
            "handler_result": {
                "trace_entry": selected_entry,
                "approval_found": approval_found,
                "approval_value": approval_value,
                "approval_field": approval_field,
            },
        }

    return {
        "stage": "handler_error",
        "reason": (
            f"no handler wired for intent "
            f"'{intent}'"
        ),
    }


# ============================================================
# HISTORY
# ============================================================

_COMPLETE_HISTORY_KEYWORDS = (
    "complete",
    "full",
    "entire",
    "every cycle",
    "all cycles",
)


def _handle_history(
    borrower_id: str,
    text: str,
    trace: list,
) -> dict:
    """
    Two retrieval modes, kept deliberately separate:

    - "complete": the user explicitly asked for the complete /
      full / entire history -> deterministic, exhaustive
      app.rag.trace_store.get_history().

    - "candidates" (default): a general/ambiguous history
      request ("show me X's history") -> similarity-ranked
      app.rag.trace_store.retrieve_trace() identifies candidate
      cycles only; each candidate is then re-fetched via the
      exact app.case_trace.get_cycle_entry() lookup before any
      fact about it is presented, and the result is always
      labeled as a candidate match, never as a guaranteed
      answer to what the user meant.
    """

    from app.rag.trace_store import (
        get_history,
        retrieve_trace,
    )

    from app.case_trace import (
        get_cycle_entry,
    )

    text_lower = text.lower()

    wants_complete = any(
        keyword in text_lower
        for keyword in _COMPLETE_HISTORY_KEYWORDS
    )

    if wants_complete:

        history = get_history(
            borrower_id
        )

        return {
            "stage": "handled",
            "intent": "get_history",
            "borrower_id": borrower_id,
            "handler_result": {
                "mode": "complete",
                "history": history,
            },
        }

    # --------------------------------------------------------
    # Candidate / fuzzy mode.
    # --------------------------------------------------------

    raw_candidates = retrieve_trace(
        borrower_id,
        text,
        k=8,
    )

    verified_candidates = []
    seen_cycles = set()

    for candidate in raw_candidates:

        cycle = (
            candidate.get(
                "metadata",
                {},
            )
            or {}
        ).get("cycle")

        if cycle is None or cycle in seen_cycles:
            continue

        seen_cycles.add(cycle)

        # Never trust the similarity-ranked result's own text —
        # re-fetch the exact record before presenting any fact.
        entry = get_cycle_entry(
            borrower_id,
            cycle,
        )

        if entry is not None:

            verified_candidates.append({
                "cycle": cycle,
                "score": candidate.get(
                    "score",
                    0.0,
                ),
                "entry": entry,
            })

    verified_candidates.sort(
        key=lambda item: item["cycle"]
    )

    return {
        "stage": "handled",
        "intent": "get_history",
        "borrower_id": borrower_id,
        "handler_result": {
            "mode": "candidates",
            "candidates": verified_candidates,
            "total_cycles_on_record": len(trace),
        },
    }


# ============================================================
# CYCLE HELPERS
# ============================================================

def _select_entry(
    trace: list,
    cycle_override: int = None,
):

    if cycle_override is not None:

        for entry in trace:

            if entry.get(
                "cycle"
            ) == cycle_override:

                return entry

        return None

    if not trace:
        return None

    return max(
        trace,
        key=lambda e: (
            e.get("cycle")
            or -1
        ),
    )


# ============================================================
# WHAT-IF PARSER
# ============================================================

def _extract_hypothetical_overrides(
    text: str,
) -> dict:
    """
    Extract common signal/value patterns from natural-language
    what-if queries.

    Example:

        What if cash flow for MSME-1003 improved to 90?

    becomes:

        {"cash_flow": 90}
    """

    text_lower = text.lower()

    signal_patterns = {
        "cash_flow": [
            r"\bcash\s*flow\b",
            r"\bcashflow\b",
        ],
        "gst_filing_delay": [
            r"\bgst\b",
            r"\bgst filing\b",
            r"\bfilings?\b",
        ],
        "vendor_payment": [
            r"\bvendor payment\b",
            r"\bvendor payments\b",
            r"\bvendor\b",
        ],
        "industry_index": [
            r"\bindustry index\b",
            r"\bindustry\b",
        ],
    }

    value_match = re.search(
        r"\b(?:to|at|of|=)\s*(-?\d+(?:\.\d+)?)\b",
        text_lower,
    )

    if not value_match:
        return {}

    value = float(
        value_match.group(1)
    )

    if value.is_integer():
        value = int(value)

    for signal, patterns in signal_patterns.items():

        if any(
            re.search(
                pattern,
                text_lower,
            )
            for pattern in patterns
        ):
            return {
                signal: value
            }

    return {}


# ============================================================
# SMOKE TEST
# ============================================================

if __name__ == "__main__":

    r1 = route_query(
        "RM001",
        "asdkjfh gibberish",
    )

    assert (
        r1["stage"]
        == "clarification_needed"
    )

    r2 = route_query(
        "RM001",
        "what is the status of MSME-1009?",
    )

    assert (
        r2["stage"]
        == "authorization_denied"
    )

    r3 = route_query(
        "RM001",
        "who owns MSME-1001?",
    )

    assert (
        r3["stage"]
        == "handled"
    )

    r4 = route_query(
        "RM001",
        "What if cash flow for MSME-1003 improved to 90?",
    )

    assert (
        r4["stage"]
        == "handled"
    )

    assert (
        r4["handler_result"][
            "requested_overrides"
        ]
        == {
            "cash_flow": 90
        }
    )

    r5 = route_query(
        "RM002",
        "Suggest hardship programs for MSME-1004",
    )

    assert (
        r5["stage"]
        == "handled"
    )

    print(
        "Router smoke tests passed."
    )