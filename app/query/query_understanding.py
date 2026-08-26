"""
Day 19 — Query Understanding.

Deterministic intent classification for Flow B.

Supported intents:

    explain_tier
    get_status
    get_history
    simulate_scenario
    ownership
    rm_portfolio
    hardship_guidance
    approval_confirmation

The classifier deliberately does not call an LLM. This keeps routing
fast, deterministic, and testable.

A later production version can replace classify_query() with an LLM
classifier while preserving the same return shape.
"""

import re


CLARIFICATION_THRESHOLD = 0.60


# ============================================================
# INTENT PATTERNS
# ============================================================

_INTENT_PATTERNS = {

    # --------------------------------------------------------
    # Approval confirmation
    # --------------------------------------------------------

    "approval_confirmation": [
        r"\bconfirm\b.*\bapproved\b",
        r"\bconfirm\b.*\bapproval\b",
        r"\bhas\b.*\bbeen approved\b",
        r"\bwas\b.*\bapproved\b",
        r"\bloan\b.*\bapproved\b",
        r"\brestructur(?:e|ing)\b.*\bapproved\b",
        r"\bapproval\b.*\bconfirmed\b",
        r"\bconfirm\b.*\brestructur",
        r"\bapproved\b.*\bunder\b",
    ],

    # --------------------------------------------------------
    # Hardship / restructuring / relief
    # --------------------------------------------------------

    "hardship_guidance": [
        r"\bhardship\b",
        r"\bhardship programs?\b",
        r"\bhardship options?\b",
        r"\bhardship assistance\b",
        r"\bfinancial hardship\b",
        r"\brelief programs?\b",
        r"\brelief options?\b",
        r"\bsupport programs?\b",
        r"\bsupport options?\b",
        r"\brestructur(?:e|ing)\b",
        r"\brestructuring options?\b",
        r"\brestructuring recommendation\b",
        r"\brecommend\b.*\brestructur",
        r"\bsuggest\b.*\bhardship\b",
        r"\bsuggest\b.*\brestructur",
        r"\bwhat help\b",
        r"\bwhat assistance\b",
        r"\bwhat support\b",
        r"\bpayment relief\b",
        r"\brepayment relief\b",
        r"\bloan relief\b",
        r"\bfinancial assistance\b",
        r"\brepayment plan\b",
    ],

    # --------------------------------------------------------
    # Explanation
    # --------------------------------------------------------

    "explain_tier": [
        r"\bwhy\b",
        r"\bexplain\b",
        r"\breason\b",
        r"\bwhy is\b",
        r"\bwhy was\b",
        r"\bwhy has\b",
    ],

    # --------------------------------------------------------
    # Status
    # --------------------------------------------------------

    "get_status": [
        r"\bstatus\b",
        r"\bcurrent status\b",
        r"\bcurrently\b",
        r"\bcurrent\b",
        r"\bhow is\b",
        r"\brisk\b",
        r"\bwhere does\b",
    ],

    # --------------------------------------------------------
    # Simulation
    # --------------------------------------------------------

    "simulate_scenario": [
        r"\bwhat if\b",
        r"\bsimulate\b",
        r"\bhypothetical\b",
        r"\bscenario\b",
        r"\bif\b.*\bimproved\b",
        r"\bif\b.*\bworsened\b",
        r"\bif\b.*\bincreased\b",
        r"\bif\b.*\bdecreased\b",
        r"\bassuming\b",
    ],

    # --------------------------------------------------------
    # History
    # --------------------------------------------------------

    "get_history": [
        r"\bhistory\b",
        r"\bhistorical\b",
        r"\bpast\b",
        r"\bmonitoring history\b",
        r"\bmonitoring cycles\b",
        r"\bprevious cycles\b",
        r"\ball cycles\b",
        r"\bover time\b",
        r"\bhistoric\b",
        r"\bshow\b.*\bhistory\b",
        r"\bgive\b.*\bhistory\b",
    ],

    # --------------------------------------------------------
    # Ownership
    # --------------------------------------------------------

    "ownership": [
        r"\bwho owns\b",
        r"\bwhich rm\b",
        r"\bwho manages\b",
        r"\bwho is the rm\b",
        r"\bwho handles\b",
        r"\bwho is handling\b",
        r"\bassigned rm\b",
        r"\brelationship manager\b.*\bborrower\b",
    ],

    # --------------------------------------------------------
    # RM portfolio
    # --------------------------------------------------------

    "rm_portfolio": [
        r"\bportfolio\b",
        r"\bborrowers assigned to\b",
        r"\bborrowers assigned\b",
        r"\ball borrowers\b.*\brm\d+\b",
        r"\bshow\b.*\bborrowers\b.*\brm\d+\b",
        r"\bhow many\b.*\bborrowers\b.*\brm\d+\b",
        r"\bhow many\b.*\bdoes\b.*\brm\d+\b.*\bmanage\b",
        r"\bwhat borrowers\b.*\brm\d+\b",
    ],
}


# ============================================================
# ENTITY PATTERNS
# ============================================================

_BORROWER_MENTION_RE = re.compile(
    r"\bmsme-\d+\b|\b\d{3,}\b",
    re.IGNORECASE,
)

_RM_MENTION_RE = re.compile(
    r"\brm\d+\b",
    re.IGNORECASE,
)


# ============================================================
# PRIORITY
# ============================================================

_INTENT_PRIORITY = [
    "approval_confirmation",
    "hardship_guidance",
    "get_history",
    "simulate_scenario",
    "ownership",
    "rm_portfolio",
    "explain_tier",
    "get_status",
]


# ============================================================
# CLASSIFIER
# ============================================================

def classify_query(text: str) -> dict:

    if not isinstance(text, str):
        return {
            "intent": None,
            "confidence": 0.0,
            "entities_needed": ["borrower"],
        }

    text_lower = text.lower().strip()

    if not text_lower:
        return {
            "intent": None,
            "confidence": 0.0,
            "entities_needed": ["borrower"],
        }

    scores = {}

    for intent, patterns in _INTENT_PATTERNS.items():

        hits = sum(
            1
            for pattern in patterns
            if re.search(pattern, text_lower)
        )

        if hits:
            scores[intent] = (
                1.0 if hits >= 2 else 0.7
            )

    if not scores:
        return {
            "intent": None,
            "confidence": 0.0,
            "entities_needed": ["borrower"],
        }

    best_score = max(
        scores.values()
    )

    candidates = [
        intent
        for intent, score in scores.items()
        if score == best_score
    ]

    best_intent = next(
        intent
        for intent in _INTENT_PRIORITY
        if intent in candidates
    )

    if best_intent == "rm_portfolio":

        entities_needed = (
            []
            if _RM_MENTION_RE.search(text_lower)
            else ["rm"]
        )

    else:

        entities_needed = (
            []
            if _BORROWER_MENTION_RE.search(text_lower)
            else ["borrower"]
        )

    return {
        "intent": best_intent,
        "confidence": round(
            scores[best_intent],
            2,
        ),
        "entities_needed": entities_needed,
    }


# ============================================================
# CLARIFICATION
# ============================================================

def needs_clarification(
    classification: dict,
) -> bool:

    if not classification:
        return True

    return (
        classification.get("intent") is None
        or classification.get("confidence", 0.0)
        < CLARIFICATION_THRESHOLD
    )


# ============================================================
# SMOKE TEST
# ============================================================

if __name__ == "__main__":

    tests = [
        (
            "Why is MSME-1004 Red?",
            "explain_tier",
        ),
        (
            "What's the current status of MSME-1002?",
            "get_status",
        ),
        (
            "What if cash flow for MSME-1003 improved to 90?",
            "simulate_scenario",
        ),
        (
            "Show me MSME-1003's history",
            "get_history",
        ),
        (
            "Suggest hardship programs for MSME-1004",
            "hardship_guidance",
        ),
        (
            "Recommend restructuring for MSME-1004",
            "hardship_guidance",
        ),
        (
            "Who owns MSME-1006?",
            "ownership",
        ),
        (
            "Show all borrowers assigned to RM001",
            "rm_portfolio",
        ),
        (
            "Confirm that MSME-1004's loan restructuring has been approved",
            "approval_confirmation",
        ),
        (
            "asdkjfh random gibberish",
            None,
        ),
    ]

    for text, expected in tests:

        result = classify_query(text)

        print(
            text,
            "->",
            result,
        )

        assert result["intent"] == expected

    print(
        "Query understanding smoke test passed."
    )