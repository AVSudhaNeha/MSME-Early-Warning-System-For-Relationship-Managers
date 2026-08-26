# MSME Early Warning — Risk Monitoring Policy

## About this document

This policy documents the rules the MSME Early Warning system actually
enforces in code today (`app/scoring/constants.py`, `app/scoring/*.py`,
`app/case_lifecycle.py`, `app/sla_check.py`, `app/handoff_retry.py`).
It replaces `TEMPLATE-policy.md` as the real source the Risk Policy RAG
store (`app/rag/policy_store.py`) indexes, so the Explanation Agent can
ground its answers in real rules instead of placeholder section headers.

**Honesty note, not boilerplate:** the specific numeric thresholds below
(70, 40, 25, etc.) are marked `[PLACEHOLDER]` in `constants.py` itself —
*"All values below are PLACEHOLDERS pending real weight-rationale."*
This document accurately describes what the system does with those
numbers today; it is not a claim that a credit committee has validated
70/40/25 as the right cutoffs for real lending decisions. Update both
`constants.py` and this document together if/when real thresholds are
set — see "Known placeholder values" at the end.

## Section 1: Tier Definitions

A borrower's composite score places them into one of three risk tiers,
or a fourth non-tier state when there isn't enough data to score at all.

- **Green** — composite score of 70 or above. Healthy. No case is opened;
  the cycle is logged only.
- **Amber** — composite score between 40 (inclusive) and 70 (exclusive).
  Elevated risk. A case is opened if one isn't already, and the assigned
  RM's action is outreach to the borrower.
- **Red** — composite score below 40, OR composite score below 25
  regardless of any peer-relative adjustment (the Critical Floor — see
  Section 6). Severe risk. The RM performs outreach AND the case is
  handed off toward the hardship/restructuring workflow (Section 5).
- **Insufficient Data** — fewer than 2 signals returned a real reading
  this cycle (see Section 4). No tier is assigned; the case action is
  manual review, not an automated tier-based action.

## Section 2: Signal Weights

Four signals feed the composite score, weighted as follows:

- Cash flow: 35%
- Vendor payment timeliness: 30%
- GST filing delay: 20%
- Industry index: 15%

Cash flow and vendor payment carry the most weight because they're the
most direct evidence of near-term repayment capacity; GST filing delay
is a compliance-behavior proxy; industry index is macro context, weighted
lowest since it reflects sector conditions the borrower doesn't control.

## Section 3: Gate Status (per-signal trend)

Independently of the composite score, each signal is also tracked
cycle-over-cycle for its own trend, with three possible statuses:

- **stable_or_improving** — this cycle's reading is not below the last
  recorded reading for this signal.
- **single_period_dip** — this cycle's reading is below the last
  reading, but it's the first such decline (not yet a confirmed trend).
- **confirmed_deteriorating** — the signal has declined for 2 consecutive
  cycles in a row. This is the threshold for treating a decline as a
  real trend rather than single-cycle noise.
- **unavailable_this_cycle** — no reading was obtained for this signal
  this cycle, and no cached fallback was eligible (Section 4).

## Section 4: Data Availability and Cached Fallback

At least 2 of the 4 signals must return a real reading (fresh or
validly cached) for a cycle to produce a composite score and tier at
all. Below that, the cycle is marked Insufficient Data and routed to
manual review rather than guessed at.

When a signal's source is unreachable (a connectivity outage, not a
case of the source genuinely having no data this cycle), the system
substitutes that signal's last successfully-seen reading rather than
treating the cycle as a data gap — a cache hit counts as available data,
not as unavailable. This substitution:

- Is only used for connectivity-type failures. A source that responds
  but genuinely has nothing to report this cycle (e.g. a borrower's very
  first cycle before enough history exists) is NOT papered over by a
  cache hit — it stays reported as unavailable, since there is nothing
  to determine.
- Is capped at 2 consecutive cycles. If a source stays down longer than
  that, the signal reverts to genuinely unavailable rather than
  indefinitely reusing an increasingly stale reading.
- Is disclosed, not hidden — every signal's provenance (fresh, cached
  fallback, or unavailable) is recorded per cycle and available to the
  Explanation Agent to cite.

The Industry Index signal is a special case: while it remains a fixed
placeholder value (not backed by a real live data source), it is
explicitly excluded from the "2 of 4 signals available" count, since a
constant that can never vary and can never fail isn't real evidence of
anything. It still participates in the weighted composite once enough
real signals clear the availability bar.

## Section 5: Red Tier — RM Outreach and Hardship Handoff

When a borrower is scored Red, two things happen: the assigned RM
performs direct outreach, and the case is handed off toward the
hardship/restructuring workflow.

The handoff itself is attempted up to 3 times. If an attempt fails in a
retryable way (e.g. the downstream system is temporarily unreachable),
it's retried with a short delay before the next attempt. If all 3
attempts are exhausted, or if a single attempt fails in a way judged
unretryable, the case is escalated for manual handoff rather than left
to silently fail.

## Section 6: Peer-Relative Adjustment and the Critical Floor

A borrower's cycle-over-cycle change is compared against their peer
group (same sector) where enough peers have valid data to make that
comparison meaningful. Three possible attributions:

- **borrower_specific** — the borrower's change diverges meaningfully
  from their peers; something specific to this borrower, not the sector
  as a whole.
- **peer_wide_shock** — the borrower's change closely tracks a
  similar-direction move across their peer group; likely a sector-wide
  event, not borrower-specific.
- **critical_floor_override** — regardless of what peers are doing, a
  composite score below the Critical Floor (25) is treated as Red. No
  amount of "the whole sector is struggling too" reasoning moves a
  borrower below this floor back out of Red. This override always takes
  precedence over any peer-relative softening.

If too few peers have valid data this cycle to make a meaningful
comparison, the system falls back to reporting the borrower's own change
without a peer-relative attribution, rather than comparing against an
unreliably small peer sample.

## Section 7: Case Lifecycle and Duplicate Prevention

A case is opened the first cycle a borrower enters Amber or Red, and
stays open (updated, not re-opened) across subsequent cycles at Amber or
Red. Re-scoring the same borrower for the same cycle does not open a
second case — the case lifecycle explicitly checks for and prevents
duplicate cases for a cycle already processed.

## Section 8: SLA Expectations

An open case (Amber or Red) that goes more than 3 consecutive cycles
without resolution is flagged as an SLA breach — someone was expected to
act on it, and didn't, within that window. This is a distinct concern
from the risk tier itself: an SLA breach is a process failure to
escalate, not a restatement of the borrower's risk level.

## Section 9: What-If Simulation Rules

A hypothetical "what if signal X were Y" query never writes to any
persisted state — no gate history, no tier-smoothing state, no case
record. Every simulation result is explicitly labeled as hypothetical in
its output, both in structured metadata and in the rendered text
response, so it can never be mistaken for a real, persisted scoring
outcome. Repeated simulation requests for the same borrower by the same
user are rate-limited, to prevent using repeated probing to infer the
exact numeric thresholds in Sections 1 and 6.

## Section 10: Known placeholder values

The following numeric thresholds are implemented and enforced exactly
as stated above, but are documented in `constants.py` as placeholders
pending a real weight-rationale exercise — not yet validated by a credit
policy review:

- Tier cutoffs: Green >= 70, Amber [40, 70), Red < 40, Critical Floor 25
- Signal weights: cash flow 35%, vendor payment 30%, GST 20%, industry 15%
- Minimum signals required for a valid cycle: 2 of 4
- Consecutive declining cycles to confirm a trend: 2
- Consecutive cycles a cached fallback may be reused: 2
- Consecutive cycles an open case may go without action before an SLA
  breach: 3
- Handoff retry attempts before escalation: 3

The Industry Index default (`DEFAULT_INDUSTRY_INDEX = 0.0`) is a growth-
rate PERCENTAGE fed through a separate formula
(`normalizers.py`'s `normalize_industry()`: `score = 50 + growth * 1.5`),
not a direct 0-100 score — `0.0` growth correctly produces a neutral `50`
score once normalized. (A prior version of this document briefly said
this should be changed to `50.0`; that was traced back and reverted —
setting it to `50.0` would feed through as a growth rate and normalize
to `100`, the maximum score, not neutral. Verified directly against the
actual post-normalization subscore, not inferred from aggregate
composite deltas.)

Vendor payment timeliness is, and is intended to remain, fully synthetic
data — real bank/AA transaction feeds provide transaction records but
not invoice due dates, so real on-time/late determination isn't
obtainable from that data source at all. This is a documented design
limitation, not an integration left unfinished.