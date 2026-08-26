# Downstream Hardship/Restructuring Workflow — Handoff Contract

Day 27 per the roadmap. Being direct about scope here rather than
pretending this is more finished than it is: **there is no real
downstream workflow endpoint to call yet** — same situation as Setu
before Day 14 and data.gov.in for Day 26, except this time the other
side of the integration (the downstream hardship/restructuring workflow
your proposal says this project integrates with) isn't something I have
credentials, a URL, or even a confirmed API shape for. Nothing here
should be read as "wired up and tested" — it's the documented contract
`app/handoff_retry.py`'s `_call_downstream_handoff()` stub is already
built to satisfy, so plugging in the real call later is a one-function
change, not a redesign.

## What already exists, and is real

- `app/handoff_retry.py` — `attempt_handoff(borrower_id, cycle, call_fn=...)`.
  The retry/escalate logic (3 attempts, exponential-ish backoff, escalate
  on exhaustion or on an unretryable exception) is fully built and
  tested — see Day 18. `call_fn` is the injection point.
- The trigger condition already exists: `engine.py`'s `_case_action()`
  returns `"rm_outreach_plus_hardship_handoff"` for Red-tier borrowers —
  that string is what should cause `attempt_handoff()` to actually get
  called, once something calls it (see "What's still missing" below).

## The contract `_call_downstream_handoff()` must satisfy

```python
def _call_downstream_handoff(borrower_id: str, cycle: int) -> bool:
    """Must return True on a successful handoff, False on a failure
    that's worth retrying (e.g. a 5xx, a timeout). Raise ONLY for a
    genuinely unretryable error (e.g. borrower not found downstream,
    a 4xx that retrying won't fix) — attempt_handoff() treats any raise
    as immediate escalation, no retries."""
```

Whatever the real downstream call ends up being (REST call, message
queue publish, another LangGraph invocation — your proposal just says
"integrates with it directly via a Red-tier handoff," not which
transport), it needs to be wrapped to satisfy this exact
`(borrower_id, cycle) -> bool` contract, raising only for unretryable
failures. That wrapping is the only thing `attempt_handoff()` needs —
it's already agnostic to what's underneath.

## What's still missing before this is a real integration

1. **The actual endpoint/interface** for the downstream workflow — URL,
   auth scheme, request/response shape. I don't have this; it depends on
   what that other system actually looks like.
2. **A caller.** Nothing currently calls `attempt_handoff()` automatically
   when `case_action == "rm_outreach_plus_hardship_handoff"` — Day 18
   built the retry mechanism, but wiring it to fire automatically off
   `engine.py`'s output is a separate, small piece of glue code that
   depends on point 1 being real first (no point wiring an automatic
   trigger to a stub that always raises `NotImplementedError`).
3. **What "cycle" means to the downstream system** — does it expect your
   `cycle` integer, a calendar date, or its own case reference? Same
   ambiguity `peer_adjustment.py`'s docstring already flags for cycle
   numbers generally (see its "Simplifying assumption" note) — worth
   resolving once, not per-integration.

Once you have the real endpoint details, send them and I'll write the
actual `_call_downstream_handoff()` implementation and the auto-trigger
glue — the same way Setu went from stub to real Day 14.