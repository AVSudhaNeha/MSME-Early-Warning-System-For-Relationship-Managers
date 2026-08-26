"""
Day 11 — Case Lifecycle Check.

Before creating a new case for a borrower's cycle result, check whether an
OPEN case already exists — if so, update it instead of spawning a
duplicate. Rules:
  - Green while no case is open -> nothing to do.
  - Green while a case IS open -> auto-resolve it.
  - Amber/Red while no case is open -> open a new case.
  - Amber/Red while a case is already open -> update it, don't duplicate.
  - Insufficient data (tier=None) -> leave the existing case completely
    untouched either way. Missing data isn't evidence of recovery, so it
    must not auto-resolve a real open case — but it also shouldn't be
    allowed to open a brand new one on its own; that needs a real tier.

State: data/cases/<borrower_id>.json — deliberately SEPARATE from
data/case_state/<borrower_id>.json (Day 6's gate/tier scoring state).
case_state tracks the SCORING history (gate streaks, tier smoothing);
cases/ tracks the WORKFLOW/action history (open case_id, resolution) an
RM or credit officer would actually see. Keeping them separate means this
Case Lifecycle Check can be reset/rebuilt independently of the scoring
engine's own state, and vice versa.
"""

import json
from pathlib import Path

from app.config import DATA_DIR
from app.rm_lookup import get_rm_for_borrower

CASES_DIR = DATA_DIR / "cases"
CASES_DIR.mkdir(parents=True, exist_ok=True)


def _case_path(borrower_id: str) -> Path:
    return CASES_DIR / f"{borrower_id}.json"


def _default_case_record(borrower_id: str) -> dict:
    return {
        "borrower_id": borrower_id,
        "open_case_id": None,
        "case_status": None,  # 'open' | 'resolved' | None
        "next_case_number": 1,
        "history": [],
    }


def load_case_record(borrower_id: str) -> dict:
    path = _case_path(borrower_id)
    if not path.exists():
        return _default_case_record(borrower_id)
    with open(path) as f:
        return json.load(f)


def save_case_record(borrower_id: str, record: dict) -> None:
    with open(_case_path(borrower_id), "w") as f:
        json.dump(record, f, indent=2)


def reset_case_record(borrower_id: str | None = None) -> None:
    """Wipe one borrower's case history, or ALL borrowers' if None —
    same reproducibility purpose as gates.py's reset_case_state()."""
    if borrower_id is not None:
        path = _case_path(borrower_id)
        if path.exists():
            path.unlink()
        return
    for f in CASES_DIR.glob("*.json"):
        f.unlink()


def get_or_create_case(borrower_id: str, cycle: int, tier) -> dict:
    """Returns {case_id, case_status, action, rm_id, rm_name}, where
    action is one of: 'no_case_needed' | 'case_opened' | 'case_updated' |
    'case_resolved' | 'case_untouched_insufficient_data'.

    rm_id/rm_name are included on EVERY return path, not just when a
    case is open — ownership is permanent per borrower (per the RM
    Assignment requirement), not something that only exists while a case
    happens to be open. Looked up via app.rm_lookup.get_rm_for_borrower()
    rather than duplicated here, so this and any Flow B ownership query
    always agree."""
    record = load_case_record(borrower_id)
    owner = get_rm_for_borrower(borrower_id) or {"rm_id": None, "rm_name": None}

    if tier is None:
        return {
            "case_id": record["open_case_id"],
            "case_status": record["case_status"],
            "action": "case_untouched_insufficient_data",
            "rm_id": owner["rm_id"],
            "rm_name": owner["rm_name"],
        }

    if tier == "Green":
        if record["case_status"] == "open":
            action = "case_resolved"
            record["case_status"] = "resolved"
            record["history"].append(
                {"cycle": cycle, "tier": tier, "action": action, "case_id": record["open_case_id"]}
            )
            save_case_record(borrower_id, record)
        else:
            action = "no_case_needed"
        return {
            "case_id": record["open_case_id"],
            "case_status": record["case_status"],
            "action": action,
            "rm_id": owner["rm_id"],
            "rm_name": owner["rm_name"],
        }

    # tier is Amber or Red
    if record["case_status"] == "open":
        action = "case_updated"
        record["history"].append(
            {"cycle": cycle, "tier": tier, "action": action, "case_id": record["open_case_id"]}
        )
    else:
        case_id = f"{borrower_id}-CASE-{record['next_case_number']}"
        record["open_case_id"] = case_id
        record["case_status"] = "open"
        record["next_case_number"] += 1
        action = "case_opened"
        record["history"].append(
            {
                "cycle": cycle,
                "tier": tier,
                "action": action,
                "case_id": case_id,
                "assigned_rm_id": owner["rm_id"],
                "assigned_rm_name": owner["rm_name"],
            }
        )

    save_case_record(borrower_id, record)
    return {
        "case_id": record["open_case_id"],
        "case_status": record["case_status"],
        "action": action,
        "rm_id": owner["rm_id"],
        "rm_name": owner["rm_name"],
    }


if __name__ == "__main__":
    from app.scoring.gates import reset_case_state
    from app.scoring.engine import run_scoring

    # Smoke test: replay MSME-1003 (gradual_decline: Green,Green,Amber,Amber,Red)
    # and MSME-1005 (cold_start: Amber,Amber) through the real engine, and
    # confirm case lifecycle opens/updates correctly, never duplicates.
    #
    # IMPORTANT: run_scoring() already calls get_or_create_case() internally
    # (wired in as of Day 11) — read case info from its return value, don't
    # call get_or_create_case() again here, or you'll see every case as
    # already-open by the time this second call runs.
    for borrower_id, cycles in [("MSME-1003", [1, 2, 3, 4, 5]), ("MSME-1005", [1, 2])]:
        reset_case_state(borrower_id)
        reset_case_record(borrower_id)
        print(f"--- {borrower_id} ---")
        for c in cycles:
            result = run_scoring(borrower_id, c)
            tier_display = result["tier"] if result["tier"] else "None"
            print(f"  cycle {c}: tier={tier_display:<6}  case_id={result['case_id']}  "
                  f"status={result['case_status']}  action={result['case_lifecycle_action']}")
        reset_case_state(borrower_id)
        reset_case_record(borrower_id)