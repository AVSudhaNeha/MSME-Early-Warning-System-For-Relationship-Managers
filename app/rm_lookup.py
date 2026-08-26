"""
RM ownership lookup.

Both records.json's "rm_id" and users.json's per-RM "portfolio" list
already existed before this file — records.json's rm_id was present but
never actually read by any code (confirmed by grep across the whole
codebase), and users.json's portfolio field is the INVERSE mapping
(RM -> list of borrowers) already used by app.query.authorization_gate.
This file is the missing forward direction (borrower -> RM), built once
here so case_lifecycle.py and Flow B's new RM-ownership queries both
call the same function instead of each re-implementing the same
records.json + users.json join.
"""

import json

from app.config import DATA_DIR

RECORDS_PATH = DATA_DIR / "records.json"
USERS_PATH = DATA_DIR / "users.json"


def _load_records() -> list:
    return json.loads(RECORDS_PATH.read_text())


def _load_users() -> dict:
    users = json.loads(USERS_PATH.read_text())
    return {u["id"]: u for u in users}


def get_rm_for_borrower(borrower_id: str):
    """Returns {"borrower_id", "rm_id", "rm_name"}, or None if the
    borrower isn't found or has no rm_id set."""
    record = next((r for r in _load_records() if r["id"] == borrower_id), None)
    if record is None:
        return None
    rm_id = record.get("rm_id")
    if not rm_id:
        return None
    users = _load_users()
    rm_user = users.get(rm_id)
    return {
        "borrower_id": borrower_id,
        "rm_id": rm_id,
        "rm_name": rm_user["name"] if rm_user else None,
    }


def get_borrowers_for_rm(rm_id: str) -> list:
    """Returns the list of borrower_ids owned by this RM, read from
    records.json's rm_id field directly — NOT from users.json's
    portfolio list. The two are expected to agree (records.json's rm_id
    is meant to be the single source of truth per the ownership
    requirement), but reading records.json here rather than
    cross-checking keeps this function's contract simple: "who does
    records.json say owns MSME-X" is the actual question being asked."""
    return [r["id"] for r in _load_records() if r.get("rm_id") == rm_id]


def resolve_rm_from_text(text: str):
    """Scans free text for a known RM's id or name — same direction and
    reasoning as app.query.entity_resolution.resolve_entity_from_text()
    for borrowers, kept as a separate function (not merged into that
    one) because an RM query and a borrower query are asking about
    different kinds of entity, and conflating them would make it easy to
    accidentally resolve "RM001" as if it were a borrower mention or
    vice versa. Returns {"status": "resolved"|"ambiguous"|"not_found",
    "rm_id", "candidates"}."""
    import re

    text_norm = text.lower()
    users = json.loads(USERS_PATH.read_text())
    rms = [u for u in users if u.get("role") == "relationship_manager"]

    matches = []
    for rm in rms:
        rm_id = rm["id"].lower()
        name = (rm.get("name") or "").lower()

        id_hit = bool(re.search(re.escape(rm_id), text_norm))
        name_words = [w for w in re.findall(r"[a-z]+", name) if len(w) > 3]
        name_hit = any(re.search(rf"\b{re.escape(w)}\b", text_norm) for w in name_words)

        if id_hit or name_hit:
            matches.append(rm["id"])

    candidates = list(dict.fromkeys(matches))
    if len(candidates) == 1:
        return {"status": "resolved", "rm_id": candidates[0], "candidates": candidates}
    if len(candidates) > 1:
        return {"status": "ambiguous", "rm_id": None, "candidates": candidates}
    return {"status": "not_found", "rm_id": None, "candidates": []}


def get_rm_portfolio_status(rm_id: str) -> list:
    """Returns [{"borrower_id", "tier"}] for every borrower owned by
    this RM — tier is their LATEST app.case_trace entry's tier (None if
    that borrower has no trace yet, e.g. never scored). Used by Flow B's
    rm_portfolio queries ("show me RM001's borrowers", "how many Red
    does RM002 manage") — built here, not duplicated inside router.py,
    per the "don't duplicate lookup logic" requirement."""
    from app.case_trace import load_trace

    result = []
    for borrower_id in get_borrowers_for_rm(rm_id):
        trace = load_trace(borrower_id)
        tier = trace[-1]["tier"] if trace else None
        result.append({"borrower_id": borrower_id, "tier": tier})
    return result


if __name__ == "__main__":
    r1 = get_rm_for_borrower("MSME-1004")
    print("MSME-1004 owner:", r1)
    assert r1 == {"borrower_id": "MSME-1004", "rm_id": "RM002", "rm_name": "Arjun Verma"}

    r2 = get_borrowers_for_rm("RM001")
    print("RM001's borrowers:", r2)
    assert "MSME-1001" in r2 and "MSME-1004" not in r2

    r3 = resolve_rm_from_text("show all borrowers assigned to RM001")
    print("resolve 'RM001' from text:", r3)
    assert r3 == {"status": "resolved", "rm_id": "RM001", "candidates": ["RM001"]}

    r4 = resolve_rm_from_text("which borrowers does Arjun Verma handle")
    print("resolve 'Arjun Verma' from text:", r4)
    assert r4["status"] == "resolved" and r4["rm_id"] == "RM002"

    r5 = get_rm_for_borrower("MSME-NOT-REAL")
    print("unknown borrower:", r5)
    assert r5 is None

    print("rm_lookup smoke test passed.")