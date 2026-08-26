"""
Day 23 — Response Synthesis.

Converts Router results into deterministic, human-readable responses.

Grounding:

    trace
        Verified borrower/case facts.

    policy
        Retrieved policy guidance.

    simulation
        Hypothetical, non-persisted result.

    none
        Clarification, denial, rate limit, or error.
"""


def synthesize_response(
    route_result: dict,
) -> dict:

    if not isinstance(
        route_result,
        dict,
    ):
        return {
            "reply": (
                "Something went wrong "
                "understanding that request."
            ),
            "grounded_in": "none",
            "raw": route_result,
        }

    stage = route_result.get(
        "stage"
    )

    # ========================================================
    # CLARIFICATION
    # ========================================================

    if stage == "clarification_needed":

        return {
            "reply": _clarification_text(
                route_result
            ),
            "grounded_in": "none",
            "raw": route_result,
        }

    # ========================================================
    # AUTHORIZATION
    # ========================================================

    if stage == "authorization_denied":

        entity = (
            route_result.get(
                "borrower_id"
            )
            or route_result.get(
                "rm_id"
            )
            or "the requested resource"
        )

        return {
            "reply": (
                f"You don't have access to {entity}: "
                f"{route_result.get('reason', 'access is restricted')}."
            ),
            "grounded_in": "none",
            "raw": route_result,
        }

    # ========================================================
    # RATE LIMIT
    # ========================================================

    if stage == "rate_limited":

        return {
            "reply": (
                f"What-if requests for "
                f"{route_result.get('borrower_id')} "
                "are temporarily limited: "
                f"{route_result.get('reason')}."
            ),
            "grounded_in": "none",
            "raw": route_result,
        }

    # ========================================================
    # HANDLER ERROR
    # ========================================================

    if stage == "handler_error":

        return {
            "reply": (
                "Couldn't complete that request: "
                f"{route_result.get('reason')}."
            ),
            "grounded_in": "none",
            "raw": route_result,
        }

    # ========================================================
    # HANDLED
    # ========================================================

    if stage == "handled":

        return _synthesize_handled(
            route_result
        )

    return {
        "reply": (
            "Something went wrong "
            "understanding that request."
        ),
        "grounded_in": "none",
        "raw": route_result,
    }


# ============================================================
# CLARIFICATION
# ============================================================

def _clarification_text(
    result: dict,
) -> str:

    reason = result.get(
        "reason"
    )

    if reason == "ambiguous_borrower":

        candidates = ", ".join(
            result.get(
                "candidates",
                [],
            )
        )

        return (
            "That could mean a few different "
            f"borrowers ({candidates}) — "
            "which one did you mean?"
        )

    if reason == "ambiguous_rm":

        candidates = ", ".join(
            result.get(
                "candidates",
                [],
            )
        )

        return (
            "That could mean a few different "
            f"relationship managers ({candidates}) — "
            "which one did you mean?"
        )

    if reason == "borrower_not_identified":

        return (
            "Which borrower are you asking about? "
            "Please provide the borrower ID or name."
        )

    if reason == "rm_not_identified":

        return (
            "Which relationship manager are you asking "
            "about? Please provide the RM ID or name."
        )

    return (
        "Could you rephrase that? "
        "I wasn't confident what you're asking."
    )


# ============================================================
# STATUS
# ============================================================

# This mapping is a plain-English restatement of a CLOSED,
# 4-value enum defined in app/scoring/engine.py::_case_action() —
# it is not an interpretation or an invented claim, just a gloss
# on a value already recorded in the trace. Any value outside
# this set is shown as-is (see fallback below) rather than guessed.
_CASE_ACTION_GLOSS = {
    "log_only": (
        "routine monitoring only; no RM action is "
        "required this cycle"
    ),
    "rm_outreach": (
        "RM outreach is recommended this cycle"
    ),
    "rm_outreach_plus_hardship_handoff": (
        "RM outreach plus a hardship/restructuring "
        "workflow handoff"
    ),
    "manual_review_insufficient_data": (
        "manual review, since scoring data was "
        "insufficient this cycle"
    ),
}


def _synthesize_status(
    borrower_id: str,
    result: dict,
    route_result: dict,
) -> dict:

    if result.get(
        "insufficient_data"
    ):

        cycle = result.get(
            "cycle"
        )

        reply = (
            f"{borrower_id} has insufficient data "
            "for the monitoring cycle, so no risk "
            "tier or composite score is available."
        )

        if cycle is not None:
            reply += (
                f" This applies to cycle {cycle}."
            )

        case_action = result.get(
            "case_action"
        )

        if case_action:

            gloss = _CASE_ACTION_GLOSS.get(
                case_action
            )

            reply += (
                f" The recorded case action is "
                f"{case_action}"
                + (
                    f" ({gloss})"
                    if gloss
                    else ""
                )
                + "."
            )

        return {
            "reply": reply,
            "grounded_in": "trace",
            "raw": route_result,
        }

    tier = result.get(
        "tier"
    ) or "unavailable"

    composite = result.get(
        "composite_score"
    )

    cycle = result.get(
        "cycle"
    )

    reply = (
        f"{borrower_id} is currently {tier}"
    )

    if composite is not None:
        reply += (
            f" (composite score {composite})"
        )

    if cycle is not None:
        reply += (
            f" as of cycle {cycle}"
        )

    reply += "."

    # --------------------------------------------------------
    # WHY, briefly: reuse the same trace-only driver narrative
    # already used for explain_tier — every phrase here maps
    # 1:1 to a literal gate_status/attribution field already
    # present in `result` (which is the full trace entry dict),
    # so this adds context without inventing anything.
    # --------------------------------------------------------

    from app.agents.explanation_agent import (
        _format_driver_narrative,
    )

    driver_sentences = _format_driver_narrative(
        result
    )

    for sentence in driver_sentences:

        reply += (
            f" {sentence}"
        )

    # --------------------------------------------------------
    # Recorded case action, glossed from the closed enum in
    # app/scoring/engine.py — tells the RM what, if anything,
    # is expected to happen this cycle.
    # --------------------------------------------------------

    case_action = result.get(
        "case_action"
    )

    if case_action:

        gloss = _CASE_ACTION_GLOSS.get(
            case_action
        )

        reply += (
            f" The recorded case action is "
            f"{case_action}"
            + (
                f" ({gloss})"
                if gloss
                else ""
            )
            + "."
        )

    return {
        "reply": reply,
        "grounded_in": "trace",
        "raw": route_result,
    }


# ============================================================
# HISTORY
# ============================================================

def _synthesize_history(
    borrower_id: str,
    result: dict,
    route_result: dict,
) -> dict:

    mode = result.get(
        "mode"
    )

    # ========================================================
    # COMPLETE — deterministic, exact, exhaustive.
    # Only used when the query explicitly asked for the
    # complete/full/entire history.
    # ========================================================

    if mode == "complete":

        history = result.get(
            "history"
        ) or []

        if not history:

            return {
                "reply": (
                    f"No monitoring history found "
                    f"for {borrower_id}."
                ),
                "grounded_in": "trace",
                "raw": route_result,
            }

        lines = [
            f"Complete verified monitoring history for "
            f"{borrower_id} ({len(history)} cycles on record):"
        ]

        for entry in history:

            cycle = entry.get(
                "cycle"
            )

            tier = entry.get(
                "tier"
            ) or "insufficient data"

            score = entry.get(
                "composite_score"
            )

            line = (
                f"- Cycle {cycle}: "
                f"{tier}"
            )

            if score is not None:
                line += (
                    f", composite score {score}"
                )

            lines.append(
                line
            )

        return {
            "reply": "\n".join(
                lines
            ),
            "grounded_in": "trace",
            "raw": route_result,
        }

    # ========================================================
    # CANDIDATES (default) — similarity-ranked retrieval,
    # verified per-cycle via get_cycle_entry(), and explicitly
    # labeled as candidate matches rather than a guaranteed
    # match for what the user meant.
    # ========================================================

    candidates = result.get(
        "candidates"
    ) or []

    total = result.get(
        "total_cycles_on_record",
        len(candidates),
    )

    if not candidates:

        return {
            "reply": (
                f"I couldn't identify specific cycles for that "
                f"request for {borrower_id}. Ask me for the "
                "complete history, or ask about a specific cycle "
                "directly."
            ),
            "grounded_in": "trace",
            "raw": route_result,
        }

    lines = [
        f"Here are the cycles retrieved as candidate matches "
        f"for your request about {borrower_id} — these are "
        f"similarity-ranked, not guaranteed to be exactly the "
        f"cycle(s) you meant ({total} cycles are on record in "
        "total):"
    ]

    for candidate in candidates:

        entry = candidate.get(
            "entry"
        ) or {}

        cycle = entry.get(
            "cycle"
        )

        tier = entry.get(
            "tier"
        ) or "insufficient data"

        score = entry.get(
            "composite_score"
        )

        line = (
            f"- Cycle {cycle}: "
            f"{tier}"
        )

        if score is not None:
            line += (
                f", composite score {score}"
            )

        lines.append(
            line
        )

    tiers_seen = [
        (candidate.get("entry") or {}).get("tier")
        for candidate in candidates
        if (candidate.get("entry") or {}).get("tier")
    ]

    if tiers_seen:

        lines.append(
            "Trend across these cycles (as recorded): "
            + " -> ".join(tiers_seen)
            + "."
        )

    lines.append(
        "For guaranteed, exact facts about one specific cycle, "
        "ask me about that cycle directly. For the full, "
        "exhaustive record, ask for the complete history."
    )

    return {
        "reply": "\n".join(
            lines
        ),
        "grounded_in": "trace",
        "raw": route_result,
    }


# ============================================================
# HANDLED
# ============================================================

def _synthesize_handled(
    route_result: dict,
) -> dict:

    intent = route_result[
        "intent"
    ]

    result = route_result.get(
        "handler_result",
        {},
    )

    borrower_id = route_result.get(
        "borrower_id"
    )

    # ========================================================
    # EXPLANATION
    # ========================================================

    if intent == "explain_tier":

        reply = result.get(
            "explanation",
            "A grounded explanation could not be generated.",
        )

        # NOTE: `ungrounded_numbers_flagged` (in `result`, and
        # therefore still visible via this response's "raw" field)
        # is an internal QA signal — it must never be surfaced in
        # the user-facing reply text. When it's non-empty, `reply`
        # here is already the safe, deterministic fallback text
        # produced by the explanation agent, not the discarded LLM
        # output that contained the unsupported number(s).

        return {
            "reply": reply,
            "grounded_in": "trace",
            "raw": route_result,
        }

    # ========================================================
    # STATUS
    # ========================================================

    if intent == "get_status":

        return _synthesize_status(
            borrower_id,
            result,
            route_result,
        )

    # ========================================================
    # HISTORY
    # ========================================================

    if intent == "get_history":

        return _synthesize_history(
            borrower_id,
            result or {},
            route_result,
        )

    # ========================================================
    # SIMULATION
    # ========================================================

    if intent == "simulate_scenario":

        tier = result.get(
            "simulated_tier"
        )

        score = result.get(
            "simulated_composite"
        )

        overrides = result.get(
            "requested_overrides",
            {},
        )

        reply = (
            f"HYPOTHETICAL for {borrower_id} "
            "(not persisted and not a real case action)."
        )

        if overrides:

            reply += (
                f" Applied hypothetical changes: "
                f"{overrides}."
            )

        if tier is not None:

            reply += (
                f" The simulated tier would be "
                f"{tier}"
            )

        if score is not None:

            reply += (
                f" with a simulated composite "
                f"score of {score}."
            )

        return {
            "reply": reply,
            "grounded_in": "simulation",
            "raw": route_result,
        }

    # ========================================================
    # OWNERSHIP
    # ========================================================

    if intent == "ownership":

        if result.get(
            "rm_id"
        ) is None:

            reply = (
                f"{borrower_id} has no RM assigned."
            )

        else:

            reply = (
                f"{borrower_id} is owned by "
                f"{result.get('rm_name')} "
                f"({result.get('rm_id')})."
            )

        return {
            "reply": reply,
            "grounded_in": "trace",
            "raw": route_result,
        }

    # ========================================================
    # RM PORTFOLIO
    # ========================================================

    if intent == "rm_portfolio":

        portfolio = result.get(
            "portfolio",
            [],
        )

        tier_filter = result.get(
            "tier_filter"
        )

        rm_id = route_result[
            "rm_id"
        ]

        if tier_filter:

            matching = [
                item
                for item in portfolio
                if (
                    item.get(
                        "tier"
                    )
                    or ""
                ).lower()
                == tier_filter
            ]

            reply = (
                f"{rm_id} currently manages "
                f"{len(matching)} "
                f"{tier_filter.capitalize()}-tier "
                "borrower(s)."
            )

            if matching:

                reply += (
                    " ("
                    + ", ".join(
                        item["borrower_id"]
                        for item in matching
                    )
                    + ")"
                )

        else:

            lines = [
                f"- {item['borrower_id']}: "
                f"{item.get('tier') or 'not yet scored'}"
                for item in portfolio
            ]

            reply = (
                f"{rm_id}'s borrowers:\n"
                + "\n".join(lines)
            )

        return {
            "reply": reply,
            "grounded_in": "trace",
            "raw": route_result,
        }

    # ========================================================
    # HARDSHIP
    # ========================================================

    if intent == "hardship_guidance":

        # Green borrower: deterministic trace answer.
        if result.get(
            "mode"
        ) == "not_recommended":

            return {
                "reply": (
                    f"{borrower_id} is currently in the "
                    f"{result.get('tier')} tier. "
                    "No hardship or restructuring program "
                    "is currently recommended based on the "
                    "borrower's present risk status."
                ),
                "grounded_in": "trace",
                "raw": route_result,
            }

        guidance = result.get(
            "policy_guidance"
        )

        if not guidance:

            guidance = (
                "No relevant policy guidance was retrieved. "
                "I cannot recommend a specific hardship or "
                "restructuring program without supporting policy."
            )

        return {
            "reply": guidance,
            "grounded_in": "policy",
            "raw": route_result,
        }

    # ========================================================
    # APPROVAL CONFIRMATION
    # ========================================================

    if intent == "approval_confirmation":

        trace_entry = result.get(
            "trace_entry"
        ) or {}

        approval_found = result.get(
            "approval_found",
            False,
        )

        approval_value = result.get(
            "approval_value"
        )

        if (
            approval_found
            and str(
                approval_value
            ).lower()
            in {
                "true",
                "approved",
                "yes",
                "confirmed",
            }
        ):

            reply = (
                f"The trace records an approval status "
                f"of {approval_value} for {borrower_id}."
            )

        else:

            reply = (
                f"I cannot confirm that loan restructuring "
                f"or hardship relief was approved for "
                f"{borrower_id}. The available trace does not "
                "contain an explicit approval record. "
                "Advisory recommendations or case actions "
                "must not be interpreted as approval."
            )

        return {
            "reply": reply,
            "grounded_in": "trace",
            "raw": route_result,
        }

    return {
        "reply": str(result),
        "grounded_in": "none",
        "raw": route_result,
    }


# ============================================================
# SMOKE TESTS
# ============================================================

if __name__ == "__main__":

    r1 = synthesize_response({
        "stage": "clarification_needed",
        "reason": "ambiguous_borrower",
        "candidates": [
            "MSME-1004",
            "MSME-1009",
        ],
    })

    assert (
        r1["grounded_in"]
        == "none"
    )

    r2 = synthesize_response({
        "stage": "authorization_denied",
        "borrower_id": "MSME-1009",
        "reason": "not in portfolio",
    })

    assert (
        r2["grounded_in"]
        == "none"
    )

    r3 = synthesize_response({
        "stage": "handled",
        "intent": "get_status",
        "borrower_id": "MSME-1009",
        "handler_result": {
            "tier": "Amber",
            "composite_score": 69.2,
            "cycle": 20,
        },
    })

    assert (
        "69.2"
        in r3["reply"]
    )

    r4 = synthesize_response({
        "stage": "handled",
        "intent": "simulate_scenario",
        "borrower_id": "MSME-1003",
        "handler_result": {
            "simulated_tier": "Amber",
            "simulated_composite": 60.0,
            "requested_overrides": {
                "cash_flow": 90
            },
        },
    })

    assert (
        "HYPOTHETICAL"
        in r4["reply"]
    )

    r5 = synthesize_response({
        "stage": "handled",
        "intent": "hardship_guidance",
        "borrower_id": "MSME-1001",
        "handler_result": {
            "mode": "not_recommended",
            "tier": "Green",
        },
    })

    assert (
        r5["grounded_in"]
        == "trace"
    )

    r6 = synthesize_response({
        "stage": "handled",
        "intent": "hardship_guidance",
        "borrower_id": "MSME-1004",
        "handler_result": {
            "policy_guidance": (
                "Per policy, Red-tier cases should "
                "be handed toward hardship/restructuring."
            )
        },
    })

    assert (
        r6["grounded_in"]
        == "policy"
    )

    r7 = synthesize_response({
        "stage": "handled",
        "intent": "approval_confirmation",
        "borrower_id": "MSME-1004",
        "handler_result": {
            "approval_found": False,
            "approval_value": None,
            "trace_entry": {
                "cycle": 19,
                "case_action": (
                    "rm_outreach_plus_hardship_handoff"
                ),
            },
        },
    })

    assert (
        "cannot confirm"
        in r7["reply"].lower()
    )

    print(
        "Response synthesis smoke tests passed."
    )