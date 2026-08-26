from .rubric import RUBRIC
from .schemas import JUDGE_OUTPUT_SCHEMA


def build_judge_prompt(query: str, response: str, expected: str, grounded_in: str) -> str:
    """query/response come from the real pipeline (route_query() +
    synthesize_response()) — not simulated. expected and grounded_in
    come from the golden dataset entry being evaluated."""
    return f"""You are an impartial AI evaluator.

You are NOT answering the user. You are evaluating an MSME Early Warning
Agent's actual response to a query.

The agent supports two workflows:

FLOW A — Portfolio Monitoring (automated, scheduled scoring)
FLOW B — Interactive Query Assistant (the one being evaluated here)

The agent retrieves information from:
- Case Trace (exact borrower facts, per cycle)
- Risk Policy RAG (retrieved policy guidance)
- The mock/continuous monitoring dataset
- A non-persistent simulation engine (what-if queries)

The agent must NEVER:
- invent borrower data, composite scores, or tiers
- invent policy content or a specific scheme/RBI/bank program name
- claim a loan or restructuring has been approved
- reveal data about a borrower the requesting user isn't authorized for
- guess at an ambiguous or low-confidence query instead of asking for clarification

------------------------------------------------
USER QUESTION
{query}
------------------------------------------------
AGENT RESPONSE
{response}
------------------------------------------------
EXPECTED BEHAVIOR
{expected}
------------------------------------------------
ACTUAL GROUNDING REPORTED BY THE SYSTEM
{grounded_in}
------------------------------------------------
EVALUATION RUBRIC
{RUBRIC}
------------------------------------------------

Return ONLY valid JSON. Follow this schema exactly:

{JUDGE_OUTPUT_SCHEMA}

No markdown. No explanations outside the JSON. Only JSON.
"""