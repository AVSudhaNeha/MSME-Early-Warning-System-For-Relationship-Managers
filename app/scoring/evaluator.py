"""
Day 8 — Golden Evaluator.

Runs run_scoring() against all 9 borrowers x their cycles, resets ALL case
state before running for reproducibility, and diffs the real engine's
output against golden_archetypes.json's scripted expectations.

GOLDEN EVALUATION MODE ONLY (mock GST historical + mock AA) — deterministic,
no real GST API calls here. Hitting the live GST API per-cycle would
return today's static "Active" status regardless of which golden cycle
we're on, which can't vary the way per-cycle filing-delay data needs to —
making the eval meaningless for that signal. (Integration-mode — a single
real GST call to prove connectivity — is separate and already verified;
see app/collectors/gst_collector.py.)

UPDATED (Day 13) — sandbox_outage (MSME-1009), cycle 2:
cashflow_collector AND vendor_collector both independently call
get_aa_client().fetch_aa_data(), which raises AAConnectionError on this
cycle for EITHER caller — the mock doesn't distinguish "cash_flow failed"
from "vendor_payment failed", the whole AA call fails. So the engine
genuinely loses BOTH cash_flow and vendor_payment that cycle (not just
cash_flow, as golden_archetypes.json originally scripted). As of Day 13,
apply_cached_fallback() substitutes both from their cycle-1 last-known-good
scores before the gate/composite ever see a gap, so this no longer drops
below MIN_SIGNALS_REQUIRED and no longer flags insufficient — it stays
Green, matching golden's expected outcome. It won't match EXACTLY: golden
scripted vendor_payment as a fresh single_period_dip (82, a real dip from
83), while the engine now reports it as a cached_fallback repeat of 83
(stable_or_improving), since the mock truly can't distinguish the two
failures. That specific per-signal gate_status divergence is expected and
documented here, not a bug — see NOTES_day1-3.md.

Composite scores will also rarely match EXACTLY — the mock's small
intentional noise (baseline variance, transaction-count quantization —
see aa_client_mock.py / vendor_collector.py docstrings) means "close"
(within a few points) is the realistic bar, not bit-for-bit identical.
Both an exact-match and a within-tolerance count are reported below so
that expected noise doesn't get mistaken for a broken engine.
"""

import json

from app.config import DATA_DIR
from app.scoring.engine import run_scoring
from app.scoring.gates import reset_case_state
from app.case_trace import reset_trace
from app.case_lifecycle import reset_case_record


ARCHETYPES_PATH = DATA_DIR / "golden_archetypes.json"

COMPOSITE_TOLERANCE = 5.0


def load_golden() -> list:
    """
    Load the complete golden evaluation dataset.

    golden_archetypes.json contains the scripted borrower archetypes and
    expected results used to evaluate the deterministic scoring engine.
    """
    with open(ARCHETYPES_PATH) as f:
        return json.load(f)


def run_golden_evaluation(verbose: bool = True) -> list:
    """
    Run every borrower/cycle in golden_archetypes.json through the real
    scoring engine and compare the actual output with the expected output.

    IMPORTANT:
    The evaluator must not pollute the real/demo monitoring history.

    Therefore all three state stores are reset before evaluation:

        data/case_state/
        data/case_traces/
        data/cases/

    and reset again after evaluation.

    This makes every evaluation reproducible and prevents repeated
    evaluator runs from creating fake monitoring cycles in Case Trace.
    """

    golden = load_golden()

    # -------------------------------------------------------------
    # TEST ISOLATION — CLEAN STATE BEFORE EVALUATION
    # -------------------------------------------------------------

    # Gate / tier history
    reset_case_state()

    # Case Trace history
    #
    # This was missing from the original evaluator after Case Trace was
    # introduced on Day 15. Without this reset, every evaluator run
    # silently appended another copy of the golden cycles into
    # data/case_traces/.
    reset_trace()

    # Case lifecycle records
    reset_case_record()

    # -------------------------------------------------------------
    # EVALUATION COUNTERS
    # -------------------------------------------------------------

    results = []

    tier_matches = 0
    composite_exact = 0
    composite_close = 0
    gate_matches = 0

    total_cycles = 0

    # -------------------------------------------------------------
    # RUN EVERY GOLDEN BORROWER / CYCLE
    # -------------------------------------------------------------

    for archetype in golden:

        borrower_id = archetype["borrower_id"]

        for expected_cycle in archetype["cycles"]:

            cycle = expected_cycle["cycle"]

            total_cycles += 1

            # Run the REAL scoring engine.
            actual = run_scoring(
                borrower_id,
                cycle,
            )

            # -----------------------------------------------------
            # TIER COMPARISON
            # -----------------------------------------------------

            tier_match = (
                actual["tier"]
                == expected_cycle["tier"]
            )

            # -----------------------------------------------------
            # COMPOSITE COMPARISON
            # -----------------------------------------------------

            exp_c = expected_cycle["composite_score"]
            act_c = actual["composite_score"]

            composite_match = (
                exp_c == act_c
            )

            composite_within_tolerance = (
                exp_c is not None
                and act_c is not None
                and abs(exp_c - act_c)
                <= COMPOSITE_TOLERANCE
            )

            # -----------------------------------------------------
            # GATE COMPARISON
            # -----------------------------------------------------

            gate_match = (
                actual["gate_status"]
                == expected_cycle["gate_status"]
            )

            # -----------------------------------------------------
            # UPDATE COUNTERS
            # -----------------------------------------------------

            tier_matches += tier_match
            composite_exact += composite_match
            composite_close += composite_within_tolerance
            gate_matches += gate_match

            # -----------------------------------------------------
            # STORE DETAILED RESULT
            # -----------------------------------------------------

            results.append(
                {
                    "borrower_id": borrower_id,
                    "archetype": archetype["archetype"],
                    "cycle": cycle,

                    "expected_tier": expected_cycle["tier"],
                    "actual_tier": actual["tier"],
                    "tier_match": tier_match,

                    "expected_composite": exp_c,
                    "actual_composite": act_c,
                    "composite_within_tolerance":
                        composite_within_tolerance,

                    "expected_gate":
                        expected_cycle["gate_status"],
                    "actual_gate":
                        actual["gate_status"],
                    "gate_match":
                        gate_match,
                }
            )

    # -------------------------------------------------------------
    # PRINT EVALUATION SUMMARY
    # -------------------------------------------------------------

    if verbose:

        print(
            f"Total cycles: {total_cycles}"
        )

        print(
            f"Tier matches:                "
            f"{tier_matches}/{total_cycles}"
        )

        print(
            f"Composite matches (exact):   "
            f"{composite_exact}/{total_cycles}"
        )

        print(
            f"Composite matches "
            f"(±{COMPOSITE_TOLERANCE}):    "
            f"{composite_close}/{total_cycles}"
        )

        print(
            f"Gate matches:                "
            f"{gate_matches}/{total_cycles}"
        )

        print()

        # ---------------------------------------------------------
        # PRINT ONLY IMPORTANT MISMATCHES
        # ---------------------------------------------------------

        for r in results:

            if (
                not r["tier_match"]
                or not r["gate_match"]
            ):

                print(
                    f"MISMATCH "
                    f"{r['borrower_id']} "
                    f"({r['archetype']}) "
                    f"cycle {r['cycle']}:\n"

                    f"    tier:      "
                    f"expected="
                    f"{r['expected_tier']!r:>8} "
                    f"actual="
                    f"{r['actual_tier']!r:>8}\n"

                    f"    composite: "
                    f"expected="
                    f"{r['expected_composite']} "
                    f"actual="
                    f"{r['actual_composite']}\n"

                    f"    gate:      "
                    f"expected="
                    f"{r['expected_gate']}\n"

                    f"               "
                    f"actual  ="
                    f"{r['actual_gate']}"
                )

    # -------------------------------------------------------------
    # TEST ISOLATION — CLEAN STATE AFTER EVALUATION
    # -------------------------------------------------------------

    # The golden evaluator is TESTING, not a real monitoring run.
    #
    # Therefore nothing generated during this evaluation should remain
    # as borrower monitoring history.

    reset_case_state()
    reset_trace()
    reset_case_record()

    return results


if __name__ == "__main__":

    run_golden_evaluation()