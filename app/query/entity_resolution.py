"""
Day 20 — Entity Resolution.

Resolves a borrower mention in free text (a full name, partial ID, or
exact borrower_id) to an actual borrower_id known to the system, using
data/records.json (the same borrower directory app/main.py already
loads) as the sole source of truth — no separate borrower list
maintained here.

Feeds directly into Day 19's confidence/clarification loop: an
"ambiguous" result here (multiple candidates) should trigger the same
kind of clarifying question a low-confidence intent classification does,
rather than the Router silently picking one.
"""

import json
import re

from app.config import DATA_DIR

RECORDS_PATH = DATA_DIR / "records.json"


def _load_borrowers() -> list:
    records = json.loads(RECORDS_PATH.read_text())
    # Defensive: handle either a flat list of borrower dicts (the current
    # records.json shape) or a dict keyed by borrower_id, in case that
    # ever changes.
    if isinstance(records, dict):
        return list(records.values())
    return records


def resolve_entity(mention: str) -> dict:
    """Returns {"status": "resolved" | "ambiguous" | "not_found",
    "borrower_id": str | None, "candidates": [...]}."""
    mention_norm = mention.strip().lower()
    borrowers = _load_borrowers()

    def bid(b):
        return b.get("id") or b.get("borrower_id") or ""

    # 1. Exact borrower_id match (case-insensitive) — cheapest, least
    #    ambiguous, try first.
    for b in borrowers:
        if bid(b).lower() == mention_norm:
            return {"status": "resolved", "borrower_id": bid(b), "candidates": [bid(b)]}

    # 2. Partial ID match, e.g. "1009" -> "MSME-1009".
    id_matches = [bid(b) for b in borrowers if mention_norm in bid(b).lower()]

    # 3. Name substring match (case-insensitive).
    name_matches = [bid(b) for b in borrowers if mention_norm in (b.get("name") or "").lower()]

    candidates = list(dict.fromkeys(id_matches + name_matches))  # dedupe, keep order

    if len(candidates) == 1:
        return {"status": "resolved", "borrower_id": candidates[0], "candidates": candidates}
    if len(candidates) > 1:
        return {"status": "ambiguous", "borrower_id": None, "candidates": candidates}
    return {"status": "not_found", "borrower_id": None, "candidates": []}


def resolve_entity_from_text(text: str) -> dict:
    """Scans a full free-text query for ANY known borrower's id or name,
    rather than requiring the caller to have already isolated a clean,
    short 'mention' substring first (that's what resolve_entity() above
    expects, and it's a fine model when the caller already has exactly
    an ID — but router.py's old ID-only regex extraction meant a query
    naming a borrower purely by name, like "what is the status of
    Deccan?", never even reached resolve_entity() at all, since it
    could never build a mention substring for a name).

    The key difference: resolve_entity() checks 'is my extracted
    mention a substring of the borrower's id/name'. This checks the
    opposite and correct direction for a name embedded in a sentence:
    'does the borrower's id/name (or a distinctive word of it) appear
    somewhere in the query text'."""
    text_norm = text.lower()
    borrowers = _load_borrowers()

    def bid(b):
        return b.get("id") or b.get("borrower_id") or ""

    matches = []
    for b in borrowers:
        id_ = bid(b).lower()
        name = (b.get("name") or "").lower()

        id_hit = bool(id_) and re.search(re.escape(id_), text_norm)

        numeric_part = id_.split("-")[-1] if "-" in id_ else ""
        numeric_hit = bool(numeric_part) and re.search(rf"\b{re.escape(numeric_part)}\b", text_norm)

        # Distinctive (len > 3, to skip filler words like "and"/"the")
        # words from the borrower's name, matched as whole words.
        name_words = [w for w in re.findall(r"[a-z]+", name) if len(w) > 3]
        name_hit = any(re.search(rf"\b{re.escape(w)}\b", text_norm) for w in name_words)

        if id_hit or numeric_hit or name_hit:
            matches.append(bid(b))

    candidates = list(dict.fromkeys(matches))  # dedupe, keep order

    if len(candidates) == 1:
        return {"status": "resolved", "borrower_id": candidates[0], "candidates": candidates}
    if len(candidates) > 1:
        return {"status": "ambiguous", "borrower_id": None, "candidates": candidates}
    return {"status": "not_found", "borrower_id": None, "candidates": []}


if __name__ == "__main__":
    r1 = resolve_entity("MSME-1009")
    print("exact id:", r1)
    assert r1 == {"status": "resolved", "borrower_id": "MSME-1009", "candidates": ["MSME-1009"]}

    r2 = resolve_entity("1009")
    print("partial id:", r2)
    assert r2["status"] == "resolved" and r2["borrower_id"] == "MSME-1009"

    r3 = resolve_entity("Deccan")
    print("ambiguous name (matches 1004 AND 1009's sister-unit name):", r3)
    assert r3["status"] == "ambiguous"

    r4 = resolve_entity("nonexistent-borrower-xyz")
    print("not found:", r4)
    assert r4["status"] == "not_found"

    print("Entity resolution smoke test passed.")

    r5 = resolve_entity_from_text("what is the status of Deccan?")
    print("free-text ambiguous name:", r5)
    assert r5["status"] == "ambiguous"

    r6 = resolve_entity_from_text("why is MSME-1009 in Red tier?")
    print("free-text exact id embedded in a sentence:", r6)
    assert r6 == {"status": "resolved", "borrower_id": "MSME-1009", "candidates": ["MSME-1009"]}

    r7 = resolve_entity_from_text("asdkjfh random gibberish")
    print("free-text no borrower mentioned:", r7)
    assert r7["status"] == "not_found"

    print("Free-text entity resolution smoke test passed.")