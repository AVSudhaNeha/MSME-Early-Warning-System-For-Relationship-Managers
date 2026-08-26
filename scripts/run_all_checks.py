"""
Day 28 — Bug fixing + full re-run.

This is the actual Day 28 deliverable: not new features, a single
command that re-runs EVERYTHING built through Day 27 in one pass, so
"did anything break" has one answer instead of eighteen separate manual
commands. Built after a full sweep (Day 28's own bug-fixing pass) found
zero regressions from Day 26/27's changes — this script is what made
that sweep repeatable instead of a one-off.

Six layers, in order:
  1. Every individual module's own __main__ smoke test (the ones spread
     across Days 6-26) — run as subprocesses so one module's sys.exit()
     or state-file side effect can't affect another's.
  2. scripts/full_eval_harness.py — golden traces + the 7 hardening checks.
  3. scripts/red_team_tests.py — the 2 adversarial scenarios.
  4. scripts/verify_sandbox_disconnect.py — the 5 Day 29 checks.
  5. scripts/flow_a_e2e_test.py — the full automated monitoring pipeline,
     driven through the real trigger_cycle() entry point.
  6. scripts/flow_b_e2e_test.py — the full interactive query pipeline,
     driven through the real route_query() entry point. One scenario
     (the live Azure OpenAI explanation call) is environment-dependent
     and reported as SKIPPED, not silently hidden and not counted as a
     failure — see that script's own docstring.

Ends with an unmistakable "FINAL REGRESSION PASSED" (or FAILED) line, so
"does the complete project still work" has one obvious answer.
"""

import subprocess
import sys

MODULES = [
    "app.case_trace",
    "app.rag.retrieval",
    "app.rag.policy_store",
    "app.rag.trace_store",
    "app.agents.explanation_agent",
    "app.sla_check",
    "app.handoff_retry",
    "app.query.query_understanding",
    "app.query.entity_resolution",
    "app.query.authorization_gate",
    "app.query.router",
    "app.query.response_synthesis",
    "app.query.simulate_scenario",
    "app.query.whatif_abuse_check",
    "app.scoring.gates",
    "app.scoring.tiering",
    "app.scoring.peer_adjustment",
    "app.scheduler",
    "app.collectors.industry_collector",
]

FAILURES = []


def run_module_smoke_tests():
    print("=== Layer 1: individual module smoke tests ===")
    for module in MODULES:
        result = subprocess.run(
            [sys.executable, "-m", module], capture_output=True, text=True
        )
        status = "PASS" if result.returncode == 0 else "FAIL"
        print(f"[{status}] {module}")
        if result.returncode != 0:
            FAILURES.append(module)
            print(result.stdout[-500:])
            print(result.stderr[-500:])


SKIPPED = []


def _run_script_layer(layer_num: int, label: str, module: str) -> None:
    print(f"\n=== Layer {layer_num}: {label} ===")
    result = subprocess.run([sys.executable, "-m", module], capture_output=True, text=True)
    output = result.stdout
    print(output.strip().splitlines()[-1] if output.strip() else "(no output)")
    if "SKIPPED" in output:
        skipped_lines = [l for l in output.splitlines() if l.strip().startswith("SKIPPED")]
        for l in skipped_lines:
            print(f"  {l.strip()}")
            SKIPPED.append(f"{module}: {l.strip()}")
    if "FAILED" in output or result.returncode != 0:
        FAILURES.append(module)


if __name__ == "__main__":
    run_module_smoke_tests()

    _run_script_layer(2, "full_eval_harness", "scripts.full_eval_harness")
    _run_script_layer(3, "red_team_tests", "scripts.red_team_tests")
    _run_script_layer(4, "verify_sandbox_disconnect", "scripts.verify_sandbox_disconnect")
    _run_script_layer(5, "flow_a_e2e_test", "scripts.flow_a_e2e_test")
    _run_script_layer(6, "flow_b_e2e_test", "scripts.flow_b_e2e_test")

    # Test scripts create this as a side effect of exercising rate
    # limiting — clean it up so a real deployment doesn't inherit test
    # artifacts.
    whatif_log = __import__("app.config", fromlist=["DATA_DIR"]).DATA_DIR / "whatif_call_log.json"
    if whatif_log.exists():
        whatif_log.unlink()

    total = len(MODULES) + 5
    passed = total - len(FAILURES)
    print(f"\n{passed}/{total} checks passed.")
    if SKIPPED:
        print("SKIPPED (external dependency, not a failure):")
        for s in SKIPPED:
            print(f"  {s}")
    if FAILURES:
        print("FAILED:", FAILURES)
        print("\nFINAL REGRESSION FAILED")
        sys.exit(1)
    else:
        print("\nFINAL REGRESSION PASSED")