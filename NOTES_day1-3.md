# Day 1–3 — What was built, what's assumed, what's still open

## Done

- **Shell renamed** to the MSME Early Warning Agent (`app/main.py`, system prompt).
- **`data/users.json`** — 2 RMs with disjoint portfolios + 1 credit officer with
  full visibility. Deliberately disjoint so the Authorization Gate (Part 4 /
  proposal §8) has something real to test against later.
- **`data/records.json`** — 9 borrowers, one per archetype, each tagged with
  `sector` (for peer grouping) and `rm_id` (for authorization).
- **`scripts/golden_archetypes.py`** → **`data/golden_archetypes.json`** — the
  actual Day 1–3 deliverable: 9 archetypes (6 core from §13.1 + the 3 hardening
  ones your roadmap names explicitly), 30 labeled cycles total, each with
  sub-scores, gate status, composite score, tier, peer attribution, and
  expected case action.

## Assumptions baked in (flag these, don't treat as final)

These aren't in the proposal — defensible placeholders picked so the
archetypes would have *something* consistent to be scored against, now
also the real engine's constants (`app/scoring/constants.py` — single
source of truth shared by both the golden script and the engine):

- **Weights:** cash_flow 0.35, vendor_payment 0.30, gst_filing_delay 0.20,
  industry_index 0.15. `gst_registration` is treated as an availability gate,
  not a weighted signal.
- **Tier thresholds:** Green ≥ 70, Amber 40–69, Red < 40, critical floor at 25
  (Red fires regardless of peer context below this).
- **Minimum signals for a scoreable cycle:** 2 of 4 *real* signals (see
  Option A below — a placeholder signal doesn't count toward this).

## Resolved: tier smoothing (was an open question, now decided)

**Decision:** normal tier deterioration requires confirmation from 2
consecutive declining cycles. A single-period dip is flagged
(`single_period_dip_smoothed_tier_held`) but does not move the displayed
tier. Exception: if the composite falls below `CRITICAL_FLOOR` (25), Red
fires immediately — a catastrophic collapse is never hidden by smoothing.
Recoveries/improvements are never smoothed either, no reason to delay good
news.

Implemented in `smoothed_tier()` (both `scripts/golden_archetypes.py` and,
as of Day 7, the real engine's `app/scoring/tiering.py`, with persistent
per-borrower state). Each cycle carries both `raw_tier` (pure threshold
banding) and `tier` (what's actually displayed/acted on), plus a
`smoothing_note` explaining which rule fired.

**Changelog — 3 data corrections made after re-checking the archetypes'
arithmetic against their own stated intent:**
- `sharp_decline` cycle 3: was (40,15,22,73) → composite 30.8, didn't
  actually cross the critical floor despite the note claiming it did. Fixed
  to (25,8,12,70) → composite 21.9, now correctly triggers
  `critical_floor_override_immediate`.
- `peer_wide_shock` cycle 3: was (76,50,58,44) with `peer_avg_delta=-3`,
  which read as `peer_driven` — contradicting the note's claim of
  `borrower_specific`. Fixed to (72,40,48,45) with `peer_avg_delta=0` so
  peers genuinely stabilize while the borrower keeps sliding.
- `sandbox_outage` cycle 2: cached fallback was `cash_flow=78`, but a
  last-known-good cache should reproduce cycle 1's actual reading, `80`.
  Fixed to `80`.

## Days 4–8 — Signal Collectors + Scoring Engine (done)

Built and verified: `app/collectors/` (GST registration — real API;
GST filing delay, Cash Flow, Vendor Payment — mock; Industry Index —
placeholder), `app/scoring/normalizers.py`, `app/scoring/gates.py`
(persistent per-borrower state in `data/case_state/`, with
`reset_case_state()` for reproducible eval runs), `app/scoring/composite.py`,
`app/scoring/tiering.py`, and `app/scoring/engine.py` orchestrating all of
it into `run_scoring(borrower_id, cycle)`.

**Option A implemented:** `industry_index` is sourced from a hardcoded
placeholder (no real data source integrated yet), so it's excluded from
`MIN_SIGNALS_REQUIRED` via `PLACEHOLDER_SIGNALS` in `constants.py` — a
constant that can never fail or vary shouldn't be able to mask a cycle
that genuinely lacks real data. It still contributes its (neutral) value
to the weighted composite once real signals clear the bar. TODO left in
`industry_collector.py`: once a real industry/sector API is integrated,
set `available` based on whether that call actually succeeded, and remove
`"industry_index"` from `PLACEHOLDER_SIGNALS`.

### Day 8 evaluation results — 29/30 tier matches, one documented limitation

Full golden evaluation (`python -m app.scoring.evaluator`) against all 9
archetypes / 30 cycles: **29/30 tier matches**, 2 real bugs found and
fixed during the process (not left as noise):
- `avg_monthly_balance` was derived from `current_balance`, making
  ratio-based cash-flow normalization silently useless — fixed in
  `aa_client_mock.py`.
- `vendor_payment` returned a fake perfect score (100) instead of
  reporting unavailable when the underlying signal was missing — fixed in
  `aa_client_mock.py` + `vendor_collector.py`.

**Known, accepted limitation — `MSME-1009` (sandbox_outage) cycle 2:**
`cashflow_collector.py` and `vendor_collector.py` both independently call
`get_aa_client().fetch_aa_data()`. The mock AA client fails that ENTIRE
call on an outage cycle — it can't fail just `cash_flow` while leaving
`vendor_payment` available, the way `golden_archetypes.json` scripted it.
Combined with Option A (industry_index correctly excluded from the
availability count), this cycle now has only 1 real signal
(`gst_filing_delay`) — below `MIN_SIGNALS_REQUIRED` — so the engine
correctly flags it insufficient, while the golden trace expected `Green`.

**Decision: not fixing this now.** Building independent per-signal failure
into the mock would mainly improve the test harness, not the actual Early
Warning Agent — and Days 9-13 already includes "the cached-fallback path
for sandbox outages" as its own planned work. Revisit only if a mentor
specifically requires 30/30, or once the mock AA client is replaced by
the real Setu integration (at which point the evaluator should reflect
actual production failure behavior instead of the mock's simplified one).

## Not done yet

- Real Setu AA sandbox — GSTIN sandbox is confirmed working; Setu AA
  consent flow is stuck in an OTP loop on the Setu FIP 2 mock bank,
  currently with Setu support (ticket 125184).
- `docs/policies/` — your Risk Policy RAG document (Part 1 of coursework.md).
- Days 9–13: Peer-Relative Adjustment + peer-size fallback, LangGraph
  fan-out/fan-in for the Signal Collectors, Case Lifecycle Check,
  scheduler idempotency, and the cached-fallback path for sandbox outages
  (this is also where the MSME-1009 limitation above gets properly fixed).