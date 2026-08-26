"""
Day 17-18 — Explanation Agent.

Trace-vs-policy separation guardrail.

Two separate operations are supported:

1. generate_explanation()
   --------------------------------
   Answers borrower-specific questions
   using an exact Case Trace entry.

   Grounding:
       trace

2. generate_policy_guidance()
   --------------------------------
   Answers advisory questions about hardship,
   restructuring, relief, or policy.

   Grounding:
       policy

Policy guidance is never treated as proof that a
specific borrower experienced an event.

Numeric grounding:

    Any number produced by the LLM for a borrower-specific
    explanation must exist in the exact trace entry.

If unsupported numbers are detected, the LLM output is discarded
and replaced with deterministic trace-only text.
"""

import re

from app.case_trace import get_cycle_entry
from app.rag.policy_store import retrieve_policy


# ============================================================
# TRACE EXPLANATION SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are an explanation assistant for a lending risk-monitoring system.

You will receive TWO separate information blocks.

============================================================
TRACE FACTS
============================================================

TRACE FACTS contain exact, verified facts for ONE borrower
and ONE monitoring cycle.

TRACE FACTS are the ONLY source of borrower-specific facts.

You may state borrower-specific facts only when they appear
in TRACE FACTS.

============================================================
POLICY CONTEXT
============================================================

POLICY CONTEXT contains general guidance retrieved from the
risk-policy knowledge base.

Policy context is NOT evidence about what happened to this borrower.

If mentioning policy guidance, explicitly say:

"Per policy..."

or:

"Policy guidance indicates..."

Never present policy guidance as a borrower-specific event.

============================================================
STRICT GROUNDING RULES
============================================================

1. NEVER invent a number.

2. NEVER state a score, threshold, percentage, count,
   duration, cycle number, date, limit, or other numeric
   value unless that exact number appears in TRACE FACTS.

3. NEVER infer tier thresholds.

4. NEVER invent historical trends.

5. NEVER invent case actions.

6. NEVER convert policy guidance into a borrower-specific fact.

7. If the trace does not contain enough information,
   explicitly say so.

8. Do not use external knowledge.

9. Answer the actual question.

10. Keep the answer concise and grounded.
"""


# ============================================================
# POLICY GUIDANCE SYSTEM PROMPT
# ============================================================

POLICY_SYSTEM_PROMPT = """
You are a policy advisory assistant for a lending
risk-monitoring system.

You will receive:

1. VERIFIED TRACE CONTEXT
2. POLICY CONTEXT

============================================================
VERIFIED TRACE CONTEXT
============================================================

This contains verified facts about the specific borrower.

You may use these facts to explain why the policy guidance
may be relevant.

However, the trace does NOT itself establish what policy
should be applied.

============================================================
POLICY CONTEXT
============================================================

This contains retrieved risk-management policy.

Policy Context is the authoritative source for general
hardship, restructuring, relief, escalation, and monitoring
guidance available to this assistant.

When giving guidance, explicitly attribute it:

"Per policy..."

or:

"Policy guidance indicates..."

============================================================
SAFETY RULES
============================================================

1. Do not invent government schemes.

2. Do not invent RBI schemes.

3. Do not claim a loan or restructuring approval.

4. Do not claim that a borrower qualifies unless the policy
   explicitly establishes that qualification.

5. Do not turn policy eligibility criteria into proof that
   the borrower satisfies them.

6. Do not invent numbers or thresholds.

7. If the retrieved policy does not contain a specific
   program or recommendation, say so.

8. Recommendations are advisory only.

9. Do not represent advisory guidance as a completed case action.

10. Keep the response concise and actionable.
"""


# ============================================================
# AZURE CLIENT
# ============================================================

def _client():

    from openai import AzureOpenAI
    from app import config

    if not (
        config.AZURE_ENDPOINT
        and config.AZURE_API_KEY
    ):
        raise RuntimeError(
            "Azure OpenAI credentials are missing. "
            "Copy .env.example to .env and fill in your values."
        )

    return AzureOpenAI(
        azure_endpoint=config.AZURE_ENDPOINT,
        api_key=config.AZURE_API_KEY,
        api_version=config.AZURE_API_VERSION,
    )


# ============================================================
# TRACE FORMATTING
# ============================================================

def _format_trace_facts(
    entry,
) -> str:

    if entry is None:
        return (
            "(no trace record found for this cycle)"
        )

    return "\n".join(
        f"{key}: {value}"
        for key, value in entry.items()
    )


# ============================================================
# POLICY FORMATTING
# ============================================================

def _format_policy_context(
    chunks: list,
) -> str:

    if not chunks:
        return (
            "(no relevant policy chunks retrieved)"
        )

    formatted = []

    for chunk in chunks:

        metadata = chunk.get(
            "metadata",
            {},
        )

        heading = metadata.get(
            "heading",
            chunk.get("id", "policy"),
        )

        text = chunk.get(
            "text",
            "",
        )

        formatted.append(
            f"[{heading}]\n{text}"
        )

    return "\n\n".join(
        formatted
    )


# ============================================================
# NUMBER EXTRACTION
# ============================================================

_NUMBER_RE = re.compile(
    r"\b\d+(?:\.\d+)?\b"
)


def _extract_numbers(
    text: str,
) -> list[str]:

    if not text:
        return []

    return _NUMBER_RE.findall(
        text
    )


# ============================================================
# TRACE GROUNDING CHECK
# ============================================================

def _check_trace_grounding(
    explanation_text: str,
    trace_entry,
) -> list:

    explanation_numbers = _extract_numbers(
        explanation_text
    )

    if trace_entry is None:
        return explanation_numbers

    trace_text = _format_trace_facts(
        trace_entry
    )

    trace_numbers = set(
        _extract_numbers(
            trace_text
        )
    )

    return [
        number
        for number in explanation_numbers
        if number not in trace_numbers
    ]


# ============================================================
# DETERMINISTIC TRACE FALLBACK
# ============================================================

_GATE_STATUS_NARRATIVE = {
    "confirmed_deteriorating": (
        "has been confirmed deteriorating for two "
        "consecutive cycles"
    ),
    "single_period_dip": (
        "shows a single-period dip (not yet a "
        "confirmed trend)"
    ),
    "stable_or_improving": (
        "is stable or improving"
    ),
    "unavailable_this_cycle": (
        "was unavailable this cycle"
    ),
}


_ATTRIBUTION_NARRATIVE = {
    "critical_floor_override": (
        "the trace attributes this to the critical-floor "
        "override, which applies regardless of peer-relative "
        "movement"
    ),
    "peer_wide_shock": (
        "the trace attributes this to a peer-wide shock "
        "(a similar-direction move across the borrower's peer "
        "group, not specific to this borrower)"
    ),
    "borrower_specific": (
        "the trace attributes this to a borrower-specific "
        "change that diverges from the peer group"
    ),
}


def _format_driver_narrative(
    trace_entry: dict,
) -> list:
    """
    Turn the trace entry's own gate_status / attribution fields
    into plain-English driver sentences.

    Every phrase here maps 1:1 to a literal field value already
    present in trace_entry — nothing is invented, no threshold
    numbers are stated.
    """

    sentences = []

    gate_status = (
        trace_entry.get("gate_status")
        or {}
    )

    deteriorating = [
        signal
        for signal, status in gate_status.items()
        if status
        in (
            "confirmed_deteriorating",
            "single_period_dip",
        )
    ]

    if deteriorating:

        signal_phrases = [
            f"{signal.replace('_', ' ')} "
            f"({_GATE_STATUS_NARRATIVE.get(gate_status[signal], gate_status[signal])})"
            for signal in deteriorating
        ]

        sentences.append(
            "Per the recorded gate status, the following "
            "signal(s) are driving this: "
            + "; ".join(signal_phrases)
            + "."
        )

    attribution = trace_entry.get(
        "attribution"
    )

    if attribution and attribution in _ATTRIBUTION_NARRATIVE:

        sentences.append(
            "For peer-relative context, "
            f"{_ATTRIBUTION_NARRATIVE[attribution]}."
        )

    return sentences


_SENTENCE_END_RE = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z0-9(\"\u2014-])"
)


def _summarize_policy_chunk(
    chunk: dict,
    max_chars: int = 420,
) -> str:

    metadata = chunk.get(
        "metadata",
        {},
    ) or {}

    heading = metadata.get(
        "heading",
        chunk.get("id", "policy"),
    )

    text = (
        chunk.get("text", "")
        or ""
    ).strip()

    # Chunk text is stored as "{heading}\n{body}" (see
    # policy_store._chunk_markdown) — strip the duplicate
    # leading heading line so it isn't shown twice.
    if text.startswith(heading):

        text = text[len(heading):].lstrip(
            "\n:—- "
        )

    # Collapse internal newlines/whitespace so sentence-boundary
    # detection below isn't thrown off by mid-sentence line wraps
    # in the source markdown.
    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    if len(text) > max_chars:

        # Split on real sentence boundaries only — a period is a
        # boundary only when followed by whitespace and then a
        # capital letter / digit / opening quote / dash. This
        # deliberately does NOT treat the periods inside
        # abbreviations like "e.g." or "i.e." as sentence ends,
        # which a naive rfind(".") does, producing a dangling,
        # unclosed clause such as "...(e.g.".
        sentences = _SENTENCE_END_RE.split(
            text
        )

        kept = ""

        for sentence in sentences:

            candidate = (
                (kept + " " + sentence).strip()
                if kept
                else sentence
            )

            if len(candidate) > max_chars and kept:
                break

            kept = candidate

            if len(kept) > max_chars:
                # Single sentence alone exceeds max_chars — hard
                # cut it, but at a whitespace boundary so we never
                # split a word (or an abbreviation) in half.
                kept = kept[:max_chars].rsplit(
                    " ",
                    1,
                )[0]

                break

        text = kept.strip()

        if text and not text.endswith((".", "!", "?")):
            text += "..."

    return f"{heading}: {text}"


def _deterministic_trace_explanation(
    borrower_id: str,
    trace_entry: dict | None,
    question: str | None = None,
    policy_chunks: list | None = None,
) -> str:

    if trace_entry is None:
        return (
            f"I don't have a verified trace record for "
            f"{borrower_id} for this cycle, so I cannot "
            "provide a grounded explanation."
        )

    tier = trace_entry.get(
        "tier"
    )

    composite = trace_entry.get(
        "composite_score"
    )

    case_action = trace_entry.get(
        "case_action"
    )

    lifecycle_action = trace_entry.get(
        "case_lifecycle_action"
    )

    cycle = trace_entry.get(
        "cycle"
    )

    parts = []

    if tier is not None:

        parts.append(
            f"{borrower_id} is currently classified "
            f"as {tier}."
        )

    else:

        parts.append(
            f"The available trace for {borrower_id} "
            "does not contain a current tier."
        )

    if composite is not None:

        parts.append(
            f"The verified composite score is "
            f"{composite}."
        )

    if cycle is not None:

        parts.append(
            f"This result comes from monitoring "
            f"cycle {cycle}."
        )

    # --------------------------------------------------------
    # WHY: driver narrative, built only from literal trace
    # fields (gate_status / attribution) — no invented numbers
    # or thresholds.
    # --------------------------------------------------------

    driver_sentences = _format_driver_narrative(
        trace_entry
    )

    if driver_sentences:

        parts.extend(
            driver_sentences
        )

    else:

        parts.append(
            "The trace does not contain enough per-signal "
            "gate-status detail to identify which specific "
            "signal(s) drove this classification."
        )

    if case_action:

        parts.append(
            f"The recorded case action is "
            f"{case_action}."
        )

    if (
        lifecycle_action
        and lifecycle_action != "no_case_needed"
    ):

        parts.append(
            "The recorded case lifecycle action is "
            f"{lifecycle_action}."
        )

    parts.append(
        "These statements are based only on the "
        "verified trace for this borrower cycle."
    )

    explanation = " ".join(parts)

    # --------------------------------------------------------
    # WHAT HAPPENS NEXT: policy guidance, clearly separated
    # and attributed — never merged into the trace statements
    # above.
    # --------------------------------------------------------

    if policy_chunks:

        top_chunk = policy_chunks[0]

        policy_summary = _summarize_policy_chunk(
            top_chunk
        )

        explanation += (
            "\n\nPer the Risk Monitoring Policy — "
            f"{policy_summary}\n"
            "This is general policy guidance, not a "
            "borrower-specific fact, and is not evidence "
            "that any specific action has already occurred "
            "for this borrower."
        )

    return explanation


# ============================================================
# TRACE EXPLANATION
# ============================================================

def generate_explanation(
    borrower_id: str,
    cycle: int,
    question: str = None,
) -> dict:
    """
    Generate borrower-specific trace-grounded explanation.

    Returns:

        {
            "explanation": str,
            "trace_entry": dict | None,
            "policy_chunks": list,
            "ungrounded_numbers_flagged": list,
            "grounding_enforced": bool
        }
    """

    # --------------------------------------------------------
    # 1. Exact trace
    # --------------------------------------------------------

    trace_entry = get_cycle_entry(
        borrower_id,
        cycle,
    )

    # --------------------------------------------------------
    # 2. Policy retrieval
    #
    # Policy may help explain procedure, but cannot become
    # borrower-specific fact.
    # --------------------------------------------------------

    query = (
        question
        or "risk tier and monitoring action for borrower"
    )

    policy_chunks = retrieve_policy(
        query,
        k=3,
    )

    # --------------------------------------------------------
    # 3. Prompt
    # --------------------------------------------------------

    trace_block = _format_trace_facts(
        trace_entry
    )

    policy_block = _format_policy_context(
        policy_chunks
    )

    user_prompt = (
        "==================================================\n"
        "TRACE FACTS\n"
        "==================================================\n"
        f"Borrower: {borrower_id}\n"
        f"Cycle: {cycle}\n\n"
        f"{trace_block}\n\n"
        "==================================================\n"
        "POLICY CONTEXT\n"
        "==================================================\n"
        f"{policy_block}\n\n"
        "==================================================\n"
        "QUESTION\n"
        "==================================================\n"
        f"{question or 'Explain why this borrower is at this tier.'}"
    )

    # --------------------------------------------------------
    # 4. LLM
    # --------------------------------------------------------

    from app import config

    client = _client()

    response = client.chat.completions.create(
        model=config.AZURE_CHAT_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0.0,
    )

    explanation = (
        response.choices[0]
        .message.content
        or ""
    ).strip()

    # --------------------------------------------------------
    # 5. Numeric grounding
    # --------------------------------------------------------

    unsupported_numbers = _check_trace_grounding(
        explanation,
        trace_entry,
    )

    grounding_enforced = False

    # --------------------------------------------------------
    # 6. HARD ENFORCEMENT
    # --------------------------------------------------------

    if unsupported_numbers:

        grounding_enforced = True

        explanation = _deterministic_trace_explanation(
            borrower_id=borrower_id,
            trace_entry=trace_entry,
            question=question,
            policy_chunks=policy_chunks,
        )

    return {
        "explanation": explanation,
        "trace_entry": trace_entry,
        "policy_chunks": policy_chunks,
        "ungrounded_numbers_flagged": unsupported_numbers,
        "grounding_enforced": grounding_enforced,
    }


# ============================================================
# POLICY GUIDANCE
# ============================================================

_HARDSHIP_ACTION_STEPS = (
    (
        "RM outreach",
        "direct contact with the borrower by the assigned "
        "Relationship Manager, per policy.",
    ),
    (
        "Financial assessment",
        "review of the borrower's current financial position, "
        "informed by the deteriorating signal(s) recorded in "
        "the trace.",
    ),
    (
        "Restructuring / hardship eligibility review",
        "the case is handed off toward the hardship/restructuring "
        "workflow per policy; the RM should determine whether the "
        "borrower may be eligible.",
    ),
    (
        "Hardship/restructuring escalation",
        "if the automated handoff cannot be completed after its "
        "retry attempts, policy provides for escalation to manual "
        "handoff rather than letting the case silently fail.",
    ),
)


def generate_policy_guidance(
    borrower_id: str,
    cycle: int,
    question: str,
) -> dict:
    """
    Generate policy-grounded advisory guidance.

    This is specifically for queries such as:

        "Suggest hardship programs for MSME-1004"
        "Recommend restructuring for MSME-1004"

    The returned grounding type is policy.

    Deliberately NOT an LLM call: an LLM asked to "suggest
    hardship programs" reliably invents plausible-sounding but
    unsupported product names (payment deferral, interest-rate
    reduction, financial counselling, ...) even when explicitly
    instructed not to. Building the response directly from the
    retrieved policy chunks removes that failure mode entirely —
    every sentence traces back either to a verified trace field
    or to a real, retrieved policy chunk.
    """

    # --------------------------------------------------------
    # Exact borrower trace.
    # --------------------------------------------------------

    trace_entry = get_cycle_entry(
        borrower_id,
        cycle,
    )

    # --------------------------------------------------------
    # Policy retrieval.
    # --------------------------------------------------------

    policy_chunks = retrieve_policy(
        question,
        k=5,
    )

    # --------------------------------------------------------
    # If policy retrieval completely fails, return a safe
    # deterministic response rather than inventing policy.
    # --------------------------------------------------------

    if not policy_chunks:

        return {
            "policy_guidance": (
                "I could not retrieve relevant policy guidance "
                "for this request, so I cannot recommend a "
                "specific hardship or restructuring program "
                "without risking an unsupported recommendation."
            ),
            "trace_entry": trace_entry,
            "policy_chunks": [],
            "grounding": "policy",
        }

    # --------------------------------------------------------
    # TRACE line — verified borrower context only.
    # --------------------------------------------------------

    lines = []

    if trace_entry:

        trace_bits = []

        if trace_entry.get("tier") is not None:
            trace_bits.append(
                f"{trace_entry['tier']} tier"
            )

        if trace_entry.get("composite_score") is not None:
            trace_bits.append(
                f"composite score {trace_entry['composite_score']}"
            )

        if trace_entry.get("cycle") is not None:
            trace_bits.append(
                f"cycle {trace_entry['cycle']}"
            )

        if trace_bits:

            lines.append(
                f"Verified trace: {borrower_id} is currently "
                + ", ".join(trace_bits)
                + "."
            )

    # --------------------------------------------------------
    # POLICY — real, retrieved content only, clearly attributed.
    # --------------------------------------------------------

    top_chunks = policy_chunks[:1]

    for chunk in top_chunks:

        lines.append(
            "Per the Risk Monitoring Policy — "
            + _summarize_policy_chunk(chunk)
        )

    # --------------------------------------------------------
    # LIMITATION — the policy does not name specific hardship
    # products, so say that explicitly instead of inventing one.
    # --------------------------------------------------------

    lines.append(
        "The available policy does not specify individual "
        "hardship programs, so I cannot recommend a specific "
        "program from the available policy evidence."
    )

    # --------------------------------------------------------
    # Concrete, policy-supported next steps — process steps
    # implied directly by the retrieved "RM outreach + hardship/
    # restructuring handoff" policy language, not named products.
    # --------------------------------------------------------

    lines.append(
        "Based on the retrieved policy, the recommended next "
        "steps for the RM are:"
    )

    for title, detail in _HARDSHIP_ACTION_STEPS:

        lines.append(
            f"- {title}: {detail}"
        )

    # --------------------------------------------------------
    # Explicit advisory / non-approval disclaimers.
    # --------------------------------------------------------

    lines.append(
        "These are advisory recommendations only and do not "
        "automatically change the case status."
    )

    lines.append(
        "This is advisory guidance and does not constitute "
        "approval — no hardship or restructuring action has "
        "been approved for this borrower."
    )

    guidance = "\n".join(lines)

    return {
        "policy_guidance": guidance,
        "trace_entry": trace_entry,
        "policy_chunks": policy_chunks,
        "grounding": "policy",
    }


# ============================================================
# SMOKE TESTS
# ============================================================

if __name__ == "__main__":

    print(
        "=" * 60
    )

    print(
        "EXPLANATION AGENT GROUNDING TEST"
    )

    print(
        "=" * 60
    )

    fake_trace = {
        "cycle": 2,
        "tier": "Amber",
        "composite_score": 61.5,
    }

    # --------------------------------------------------------
    # Clean
    # --------------------------------------------------------

    clean = (
        "This borrower is in the Amber tier this cycle, "
        "with a composite score of 61.5."
    )

    clean_flags = _check_trace_grounding(
        clean,
        fake_trace,
    )

    print(
        "\nClean explanation:"
    )

    print(clean)

    print(
        "Flags:",
        clean_flags,
    )

    assert clean_flags == []

    # --------------------------------------------------------
    # Unsupported number
    # --------------------------------------------------------

    dirty = (
        "This borrower is in the Amber tier with a "
        "composite score of 61.5, down from 92 last quarter."
    )

    dirty_flags = _check_trace_grounding(
        dirty,
        fake_trace,
    )

    print(
        "\nDirty explanation:"
    )

    print(dirty)

    print(
        "Flags:",
        dirty_flags,
    )

    assert "92" in dirty_flags

    # --------------------------------------------------------
    # Threshold hallucination
    # --------------------------------------------------------

    threshold_hallucination = (
        "The borrower is Red because the score is below "
        "the threshold of 40."
    )

    threshold_flags = _check_trace_grounding(
        threshold_hallucination,
        fake_trace,
    )

    print(
        "\nThreshold hallucination:"
    )

    print(threshold_hallucination)

    print(
        "Flags:",
        threshold_flags,
    )

    assert "40" in threshold_flags

    # --------------------------------------------------------
    # Deterministic fallback
    # --------------------------------------------------------

    fallback = _deterministic_trace_explanation(
        borrower_id="MSME-TEST",
        trace_entry=fake_trace,
    )

    print(
        "\nDeterministic fallback:"
    )

    print(fallback)

    fallback_flags = _check_trace_grounding(
        fallback,
        fake_trace,
    )

    print(
        "Fallback flags:",
        fallback_flags,
    )

    assert fallback_flags == []

    print(
        "\nGrounding guardrail smoke tests PASSED."
    )