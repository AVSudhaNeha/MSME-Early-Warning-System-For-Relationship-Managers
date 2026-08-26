# Project Status — MSME Early Warning System (Days 1–30)

Last full-harness run: `Tier matches: 30/30`, `7/7 hardening checks passed`,
`2/2 red-team tests passed`, `5/5 sandbox-disconnect checks passed`. Run
`python -m scripts.full_eval_harness`, `python -m scripts.red_team_tests`,
and `python -m scripts.verify_sandbox_disconnect` yourself to reproduce —
nothing in this document is asserted without those commands backing it up.

## What's real vs. mock, honestly, signal by signal

| Signal | Mock | Live |
|---|---|---|
| GST filing delay | ✅ scripted | Depends on your GST integration (Days 4–8, not touched in 14–30) |
| Cash flow | ✅ scripted | ✅ Real Setu AA — verified end-to-end (Day 14), `COMPLETED` session confirmed |
| Vendor payment | ✅ scripted | ❌ Not live, **and not meant to be** — your own proposal documents this as fully synthetic; no real API gives inter-business payment-timeliness data at any tier |
| Industry index | ✅ placeholder constant | ⚠️ Scaffolded (Day 26), **not verified** — needs your data.gov.in API key + a confirmed working resource_id + real field names in `industry_sector_map.json` before it will actually work |

## What's built and tested (Days 14–30)

- **Day 14:** Real Setu AA pull, wired into `aa_client_live.py`. Known limitation: `on_time` is a placeholder (`True` always) — real bank data has no lateness flag.
- **Day 15:** Case Trace store — exact, append-only per-cycle facts.
- **Days 16–17:** Dependency-free TF-IDF RAG (Risk Policy store, Case Trace store) + Explanation Agent with the trace-vs-policy separation guardrail.
- **Day 18:** SLA Timeout Check, Handoff Retry Check.
- **Days 19–25:** Full Interactive Query Layer — Query Understanding, Entity Resolution, Authorization Gate, Router, Response Synthesis, simulate_scenario (side-effect-free), What-If Abuse Check.
- **Day 26:** Industry Index live-mode scaffolding — off by default, fails loudly (not silently) if used without real credentials.
- **Day 27:** Full eval harness (`scripts/full_eval_harness.py`), red-team tests (`scripts/red_team_tests.py`), downstream handoff contract documented (`docs/downstream_handoff_contract.md`).
- **Day 28:** Bug-fixing pass — re-ran every module's own smoke test plus the Day 27 suites in one sweep (21 checks total). Zero regressions found from Day 26/27's changes. Built `scripts/run_all_checks.py` so this sweep is one command going forward instead of 19 manual ones.
- **Day 29:** Sandbox-disconnect verification (`scripts/verify_sandbox_disconnect.py`) — proves graceful degradation through the real `run_scoring()` entry point, not just the isolated cache function.

## Known gaps — not silently swept under the rug

1. **Risk Policy content** — ✅ done. `docs/policies/risk_monitoring_policy.md` replaces `TEMPLATE-policy.md` (deleted), documents what the system actually implements (tier thresholds, gate logic, cached fallback, handoff retry, SLA, peer adjustment, critical floor, simulation rules), and is explicit that the numeric thresholds are still marked `[PLACEHOLDER]` in `constants.py` pending real credit-policy review — this document doesn't overclaim that. One honest limitation found while testing it: the TF-IDF retriever mismatches on paraphrased queries that don't share literal keywords with the policy text (e.g. "open too long without action" ranks the real SLA section 3rd, not 1st, since the query never says "SLA"). Documented, not hidden — see `retrieval.py`'s own docstring for the embedding-swap upgrade path if this becomes a real problem.
2. **Golden-evaluation reconciliation** — done. One real bug found and fixed: `aa_client_mock.py` generated only 8 vendor transactions per cycle (~12.5-point score resolution), too coarse to reproduce golden's fine-grained per-cycle targets, silently flattening vendor_payment's gate trend. Fixed by raising to 50 transactions. Effect: Composite ±5 went 24/30 → 27/30, Gate matches 14/30 → 16/30, Tier stayed 30/30. A second suspected fix (raising `DEFAULT_INDUSTRY_INDEX` from 0.0 to "neutral" 50.0) was investigated, applied, found to be WRONG on direct verification — `normalizers.py`'s `normalize_industry()` treats this value as a growth-rate percentage (`score = 50 + growth * 1.5`), so `0.0` already produced a correct neutral score of 50, while `50.0` fed through as a growth rate normalizes to 100 (the maximum, not neutral), silently inflating every composite. Reverted. No changes needed to `golden_archetypes.json` — MSME-1003's Red-tier scenario was already reaching Red for the correct, borrower-specific reason (verified directly: composite 36.9, `attribution: borrower_specific`, `case_action: rm_outreach_plus_hardship_handoff`). Remaining mismatches (industry_index gate always flat by design, MSME-1008/1009's residual RNG-noise-driven diffs) are classified and documented as legitimate mock-data variance, not bugs.
3. **Industry index live mode — FROZEN as mock for this project.** Scaffolding from Day 26 (`INDUSTRY_INDEX_MOCK_MODE`, `industry_collector.py`'s live-mode code path, `data/industry_sector_map.json`) remains in place for future integration, but is not being completed now. Reason, based on actual verification, not assumption: India's sector-level Index of Industrial Production (IIP) was the intended live source per the proposal, but every IIP dataset checked on data.gov.in (3 separate resources) returned "The API for this resource does not exist — Request API" rather than a working endpoint; RBI's DBIE has no programmatic API; NSE sector indices actively block non-browser access. No fake `resource_id`, sector mapping, or field name was guessed to force this live. `INDUSTRY_INDEX_MOCK_MODE=true` remains the setting used for the demo and all evaluation.
3. **Vendor payment timeliness** — deliberately, permanently synthetic per your own proposal. Not a gap to close.
4. **Downstream hardship/restructuring handoff** — the retry/escalate logic is real and tested; the actual downstream call is a documented contract (`docs/downstream_handoff_contract.md`), not a real integration, since no endpoint/credentials exist for it yet.
5. **Composite/gate exact-match rate against golden traces** — tier matches are 30/30, composite exact-match is 1/30, gate-label match is now 16/30 (up from 14/30 after the vendor-transaction-count fix above). Remaining gaps are attributable to the mock's inherent noise and the `industry_index` placeholder never varying by design, not bugs — see item 2 above for the full reconciliation.

## Commands to reproduce everything in this document

```
python -m scripts.run_all_checks
python -m scripts.verify_sandbox_disconnect
```