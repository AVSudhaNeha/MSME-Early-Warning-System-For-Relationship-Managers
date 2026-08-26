"""
MSME Early Warning Agent — Evaluation Runner.

Pipeline:

    golden_dataset.json
          ↓
    route_query()
          ↓
    synthesize_response()
          ↓
    LLM Judge
          ↓
    evaluation_report.json
    evaluation_report.md

Reports are rewritten after EVERY test case.

golden_dataset.json is read-only.
"""

import json
import re
import sys
import traceback
from pathlib import Path

from app.query.router import route_query
from app.query.response_synthesis import (
    synthesize_response,
)

from .config import (
    GOLDEN_DATASET_PATH,
    REPORT_JSON_PATH,
    REPORT_MD_PATH,
    REPORT_TXT_PATH,
    PASS_THRESHOLD,
)

from .judge_prompt import (
    build_judge_prompt,
)

from .providers import (
    get_judge,
)

from .report import (
    compute_summary,
    write_json_report,
    write_markdown_report,
    write_text_report,
)


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


# ============================================================
# LOAD GOLDEN DATASET
# ============================================================

def _load_golden_dataset():

    with open(
        GOLDEN_DATASET_PATH,
        "r",
        encoding="utf-8",
    ) as file:

        data = json.load(
            file
        )

    if not isinstance(
        data,
        list,
    ):

        raise ValueError(
            "golden_dataset.json must "
            "contain a JSON list."
        )

    return data


# ============================================================
# JUDGE JSON EXTRACTION
# ============================================================

def _extract_json(
    raw_text: str,
) -> dict:

    if raw_text is None:

        raise ValueError(
            "Judge returned None."
        )

    cleaned = str(
        raw_text
    ).strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
    ).strip()

    try:

        parsed = json.loads(
            cleaned
        )

        if not isinstance(
            parsed,
            dict,
        ):

            raise ValueError(
                "Judge JSON is not an object."
            )

        return parsed

    except json.JSONDecodeError:

        start = cleaned.find(
            "{"
        )

        end = cleaned.rfind(
            "}"
        )

        if (
            start == -1
            or end == -1
            or end <= start
        ):

            raise

        parsed = json.loads(
            cleaned[
                start:end + 1
            ]
        )

        if not isinstance(
            parsed,
            dict,
        ):

            raise ValueError(
                "Extracted judge JSON is not an object."
            )

        return parsed


# ============================================================
# NORMALIZE JUDGE
# ============================================================

def _normalize_judge(
    judge: dict,
) -> dict:

    dimensions = [
        "correctness",
        "faithfulness",
        "grounding",
        "authorization",
        "clarification",
        "reasoning",
        "safety",
        "formatting",
    ]

    normalized = dict(
        judge or {}
    )

    for dimension in dimensions:

        try:

            normalized[
                dimension
            ] = float(
                normalized.get(
                    dimension,
                    1,
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            normalized[
                dimension
            ] = 1.0

    try:

        normalized[
            "overall_score"
        ] = float(
            normalized.get(
                "overall_score",
                1,
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        normalized[
            "overall_score"
        ] = 1.0

    normalized.setdefault(
        "summary",
        "",
    )

    normalized.setdefault(
        "strengths",
        [],
    )

    normalized.setdefault(
        "weaknesses",
        [],
    )

    normalized.setdefault(
        "failed_dimensions",
        [],
    )

    return normalized


# ============================================================
# INVALID JUDGE
# ============================================================

def _invalid_judge(
    reason: str,
) -> dict:

    return {
        "overall_score": 1.0,
        "correctness": 1.0,
        "faithfulness": 1.0,
        "grounding": 1.0,
        "authorization": 1.0,
        "clarification": 1.0,
        "reasoning": 1.0,
        "safety": 1.0,
        "formatting": 1.0,
        "summary": (
            "Judge output was invalid."
        ),
        "strengths": [],
        "weaknesses": [
            reason
        ],
        "failed_dimensions": [
            "formatting"
        ],
    }


# ============================================================
# RUN ONE CASE
# ============================================================

def run_case(
    case: dict,
    call_judge,
) -> dict:

    cycle_override = case.get(
        "cycle"
    )

    # --------------------------------------------------------
    # Real agent pipeline
    # --------------------------------------------------------

    route_result = route_query(
        user_id=case[
            "user_id"
        ],
        text=case[
            "query"
        ],
        cycle_override=cycle_override,
    )

    synthesized = (
        synthesize_response(
            route_result
        )
    )

    response_text = synthesized[
        "reply"
    ]

    actual_grounded_in = (
        synthesized[
            "grounded_in"
        ]
    )

    # --------------------------------------------------------
    # Judge prompt
    # --------------------------------------------------------

    cycle_context = (
        f"Evaluation cycle override: "
        f"{cycle_override}."
        if cycle_override is not None
        else
        "No cycle override was supplied; "
        "production latest-cycle behavior was used."
    )

    prompt = build_judge_prompt(
        query=case[
            "query"
        ],
        response=response_text,
        expected=case[
            "expected_behavior"
        ],
        grounded_in=(
            f"System reported grounded_in="
            f"'{actual_grounded_in}'. "
            f"Expected grounded_in="
            f"'{case['expected_grounded_in']}'. "
            f"{cycle_context}"
        ),
    )

    # --------------------------------------------------------
    # Judge
    # --------------------------------------------------------

    raw_output = call_judge(
        prompt
    )

    try:

        judge = _normalize_judge(
            _extract_json(
                raw_output
            )
        )

    except Exception as exc:

        judge = _invalid_judge(
            str(exc)
        )

    failed_dimensions = judge.get(
        "failed_dimensions",
        [],
    )

    passed = (
        judge[
            "overall_score"
        ] >= PASS_THRESHOLD
        and not failed_dimensions
    )

    return {
        "id": case[
            "id"
        ],

        "category": case.get(
            "category",
            "unknown",
        ),

        "query": case[
            "query"
        ],

        "user_id": case[
            "user_id"
        ],

        "cycle_override": (
            cycle_override
        ),

        "response": response_text,

        "actual_grounded_in": (
            actual_grounded_in
        ),

        "expected_grounded_in": case[
            "expected_grounded_in"
        ],

        "judge": judge,

        "passed": passed,
    }


# ============================================================
# PIPELINE ERROR
# ============================================================

def _pipeline_error(
    case: dict,
    exc: Exception,
) -> dict:

    return {
        "id": case[
            "id"
        ],
        "category": case.get(
            "category",
            "unknown",
        ),
        "query": case[
            "query"
        ],
        "user_id": case[
            "user_id"
        ],
        "cycle_override": case.get(
            "cycle"
        ),
        "response": (
            f"[pipeline error: {exc}]"
        ),
        "actual_grounded_in": None,
        "expected_grounded_in": case.get(
            "expected_grounded_in"
        ),
        "judge": _invalid_judge(
            f"Pipeline error: {exc}"
        ),
        "passed": False,
        "error_type": type(
            exc
        ).__name__,
    }


# ============================================================
# SAVE REPORT
# ============================================================

def _save_report(
    results: list,
):

    summary = compute_summary(
        results
    )

    write_json_report(
        results,
        summary,
        REPORT_JSON_PATH,
    )

    write_markdown_report(
        results,
        summary,
        REPORT_MD_PATH,
    )

    write_text_report(
        results,
        summary,
        REPORT_TXT_PATH,
    )

    return summary


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "MSME EARLY WARNING AGENT EVALUATION"
    )

    print(
        "=" * 60
    )

    print(
        f"\nReport JSON will be written to: "
        f"{Path(REPORT_JSON_PATH).resolve()}"
    )

    print(
        f"Report MD   will be written to: "
        f"{Path(REPORT_MD_PATH).resolve()}"
    )

    print(
        f"Report TXT  will be written to: "
        f"{Path(REPORT_TXT_PATH).resolve()}\n"
    )

    results = []

    # --------------------------------------------------------
    # IMPORTANT:
    # From this point on, ANY failure — judge init, dataset
    # load, or a per-case crash — must still result in a fresh
    # report being written that reflects *this* run, even if
    # that report just says 0/0 with an error summary. A run
    # that dies before ever calling _save_report() is exactly
    # what leaves a stale, misleading old report on disk, so
    # every exit path below goes through _save_report(results)
    # first.
    # --------------------------------------------------------

    try:

        # ----------------------------------------------------
        # Judge
        # ----------------------------------------------------

        try:

            call_judge, model_name = (
                get_judge()
            )

        except Exception as exc:

            print(
                f"{RED}Judge initialization failed:{RESET}"
            )

            print(
                exc
            )

            _save_report(
                results
            )

            print(
                f"{YELLOW}A fresh (empty) report was written "
                f"to reflect this failed run — the previous "
                f"report has been overwritten, not left "
                f"stale.{RESET}"
            )

            sys.exit(1)

        print(
            f"Provider : {model_name}"
        )

        # ----------------------------------------------------
        # Dataset
        # ----------------------------------------------------

        try:

            cases = _load_golden_dataset()

        except Exception as exc:

            print(
                f"{RED}Failed to load golden dataset:{RESET}"
            )

            print(
                exc
            )

            _save_report(
                results
            )

            print(
                f"{YELLOW}A fresh (empty) report was written "
                f"to reflect this failed run.{RESET}"
            )

            sys.exit(1)

        print(
            f"Cases    : {len(cases)}\n"
        )

        # ----------------------------------------------------
        # IMPORTANT:
        # Start a fresh report before running any case, so a
        # crash on case 1 still overwrites stale data from a
        # previous run instead of leaving it untouched.
        # ----------------------------------------------------

        _save_report(
            results
        )

        # ----------------------------------------------------
        # Run all cases
        # ----------------------------------------------------

        for index, case in enumerate(
            cases,
            start=1,
        ):

            print(
                f"Running {case['id']} "
                f"({index}/{len(cases)}) — "
                f"{case.get('category', 'unknown')}"
            )

            try:

                result = run_case(
                    case,
                    call_judge,
                )

            except Exception as exc:

                print(
                    f"  {RED}ERROR{RESET}: "
                    f"{exc}"
                )

                traceback.print_exc()

                result = _pipeline_error(
                    case,
                    exc,
                )

            results.append(
                result
            )

            status = (
                f"{GREEN}PASS{RESET}"
                if result["passed"]
                else f"{RED}FAIL{RESET}"
            )

            print(
                f"  {status} "
                f"score="
                f"{result['judge'].get('overall_score')}"
            )

            # --------------------------------------------------
            # SAVE IMMEDIATELY
            # --------------------------------------------------

            try:

                _save_report(
                    results
                )

                print(
                    f"  {CYAN}Report updated on disk "
                    f"({len(results)}/{len(cases)}) — "
                    f"{Path(REPORT_JSON_PATH).resolve()}"
                    f"{RESET}"
                )

            except Exception as exc:

                print(
                    f"  {YELLOW}WARNING: "
                    f"Report write failed: "
                    f"{exc}{RESET}"
                )

            print()

        # ----------------------------------------------------
        # Final
        # ----------------------------------------------------

        summary = _save_report(
            results
        )

    except SystemExit:

        raise

    except Exception as exc:

        # Anything unexpected anywhere above still gets a
        # report written for whatever results exist so far,
        # instead of silently leaving the old file in place.

        print(
            f"{RED}Unexpected evaluation error:{RESET} {exc}"
        )

        traceback.print_exc()

        _save_report(
            results
        )

        sys.exit(1)

    print(
        "=" * 60
    )

    print(
        "SUMMARY"
    )

    print(
        "=" * 60
    )

    print(
        f"\nPassed  : "
        f"{summary['passed']}"
    )

    print(
        f"Failed  : "
        f"{summary['failed']}"
    )

    print(
        f"Average : "
        f"{summary['average_overall_score']}\n"
    )

    for dimension, average in (
        summary[
            "dimension_averages"
        ].items()
    ):

        print(
            f"{dimension.capitalize():<15}: "
            f"{average}"
        )

    print(
        "\nReports written to:"
    )

    print(
        f"  {Path(REPORT_JSON_PATH).resolve()}"
    )

    print(
        f"  {Path(REPORT_MD_PATH).resolve()}"
    )

    print(
        f"  {Path(REPORT_TXT_PATH).resolve()}"
    )

    # --------------------------------------------------------
    # Print full detail for every FAILED case directly to the
    # terminal — no file needs to be opened to see what went
    # wrong. Editors can be unreliable about reloading a file
    # that changed on disk; the terminal cannot lie about this.
    # --------------------------------------------------------

    failed_results = [
        r
        for r in results
        if not r["passed"]
    ]

    if failed_results:

        print(
            f"\n{'=' * 60}"
        )

        print(
            f"{RED}FAILED CASES — FULL DETAIL "
            f"({len(failed_results)}){RESET}"
        )

        print(
            "=" * 60
        )

        for r in failed_results:

            judge = r["judge"]

            print(
                f"\n{RED}[FAIL]{RESET} {r['id']} "
                f"({r.get('category', 'unknown')}) — "
                f"score {judge.get('overall_score')}/5"
            )

            print(
                f"  Query      : {r['query']}"
            )

            print(
                f"  Response   : {r['response']}"
            )

            print(
                f"  Grounded in: actual="
                f"{r.get('actual_grounded_in')} "
                f"expected="
                f"{r.get('expected_grounded_in')}"
            )

            if judge.get(
                "failed_dimensions"
            ):

                print(
                    f"  Failed dims: "
                    f"{', '.join(judge['failed_dimensions'])}"
                )

            if judge.get(
                "weaknesses"
            ):

                print(
                    "  Weaknesses :"
                )

                for weakness in judge[
                    "weaknesses"
                ]:

                    print(
                        f"    - {weakness}"
                    )

    else:

        print(
            f"\n{GREEN}All cases passed — nothing to "
            f"show.{RESET}"
        )

    sys.exit(
        0
        if summary["failed"] == 0
        else 1
    )


if __name__ == "__main__":
    main()