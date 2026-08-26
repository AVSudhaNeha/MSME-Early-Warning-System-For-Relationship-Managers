"""
Turns a list of per-case judge results into a JSON report and a
human-readable Markdown report. Kept separate from run_eval.py so the
report format can change without touching the evaluation loop itself.
"""

import json
from datetime import datetime, timezone

DIMENSIONS = [
    "correctness", "faithfulness", "grounding", "authorization",
    "clarification", "reasoning", "safety", "formatting",
]


def compute_summary(results: list) -> dict:
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    avg_overall = round(sum(r["judge"]["overall_score"] for r in results) / len(results), 2) if results else 0.0
    dim_averages = {}
    for dim in DIMENSIONS:
        vals = [r["judge"].get(dim, 0) for r in results]
        dim_averages[dim] = round(sum(vals) / len(vals), 2) if vals else 0.0
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "average_overall_score": avg_overall,
        "dimension_averages": dim_averages,
    }


def write_json_report(results: list, summary: dict, path: str) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "results": results,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def write_text_report(results: list, summary: dict, path: str) -> None:
    """
    Plain-text mirror of the report. No JSON syntax, no Markdown
    syntax — just readable lines, so it's viewable in any editor,
    `type`/`cat`, or a browser tab with zero rendering ambiguity.
    """
    lines = []
    lines.append("MSME EARLY WARNING AGENT - EVALUATION REPORT")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append(f"Passed  : {summary['passed']} / {summary['total']}")
    lines.append(f"Failed  : {summary['failed']} / {summary['total']}")
    lines.append(f"Average : {summary['average_overall_score']} / 5")
    lines.append("")
    lines.append("Dimension averages:")
    for dim, avg in summary["dimension_averages"].items():
        lines.append(f"  {dim.capitalize():<15}: {avg}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("")

    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        lines.append(f"[{status}] {r['id']} ({r.get('category', 'unknown')}) - score {r['judge']['overall_score']}/5")
        lines.append(f"  Query      : {r['query']}")
        lines.append(f"  Response   : {r['response']}")
        lines.append(f"  Grounded in: actual={r.get('actual_grounded_in')}  expected={r.get('expected_grounded_in')}")
        if r["judge"].get("failed_dimensions"):
            lines.append(f"  Failed dims: {', '.join(r['judge']['failed_dimensions'])}")
        if r["judge"].get("weaknesses"):
            lines.append("  Weaknesses :")
            for w in r["judge"]["weaknesses"]:
                lines.append(f"    - {w}")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_markdown_report(results: list, summary: dict, path: str) -> None:
    lines = []
    lines.append("# MSME Early Warning Agent — Evaluation Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Passed: **{summary['passed']} / {summary['total']}**")
    lines.append(f"- Failed: **{summary['failed']} / {summary['total']}**")
    lines.append(f"- Average overall score: **{summary['average_overall_score']} / 5**")
    lines.append("")
    lines.append("### Dimension averages")
    lines.append("")
    lines.append("| Dimension | Average |")
    lines.append("|---|---|")
    for dim, avg in summary["dimension_averages"].items():
        lines.append(f"| {dim.capitalize()} | {avg} |")
    lines.append("")
    lines.append("## Per-case results")
    lines.append("")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        lines.append(f"### [{status}] {r['id']} — {r['category']}")
        lines.append("")
        lines.append(f"**Query:** {r['query']}")
        lines.append("")
        lines.append(f"**Response:** {r['response']}")
        lines.append("")
        lines.append(f"**Overall score:** {r['judge']['overall_score']} / 5")
        lines.append("")
        if r["judge"].get("failed_dimensions"):
            lines.append(f"**Failed dimensions:** {', '.join(r['judge']['failed_dimensions'])}")
            lines.append("")
        if r["judge"].get("weaknesses"):
            lines.append("**Weaknesses:**")
            for w in r["judge"]["weaknesses"]:
                lines.append(f"- {w}")
            lines.append("")
        lines.append("---")
        lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))