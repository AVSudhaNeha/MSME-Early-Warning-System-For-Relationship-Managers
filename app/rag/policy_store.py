"""
Day 16 — Risk Policy RAG Store.

Indexes the REAL policy documents under docs/policies/.

TEMPLATE-policy.md is deliberately excluded because it is only a
development scaffold and must never be retrieved as if it were
real policy.

Uses the project's lightweight TF-IDF retrieval engine.
"""

import re

from app.config import DOCS_DIR
from app.rag.retrieval import (
    TfidfIndex,
)


POLICIES_DIR = (
    DOCS_DIR / "policies"
)

EXCLUDED_FILES = {
    "TEMPLATE-policy.md",
}


_index = None


# ============================================================
# CHUNKING
# ============================================================

def _chunk_markdown(
    path,
) -> list:

    text = path.read_text(
        encoding="utf-8"
    )

    parts = re.split(
        r"(?m)^## ",
        text,
    )

    chunks = []

    if parts[0].strip():

        chunks.append({
            "heading": path.stem,
            "body": parts[0].strip(),
        })

    for part in parts[1:]:

        lines = part.split(
            "\n",
            1,
        )

        heading = (
            lines[0].strip()
        )

        body = (
            lines[1].strip()
            if len(lines) > 1
            else ""
        )

        if body:

            chunks.append({
                "heading": heading,
                "body": body,
            })

    return chunks


# ============================================================
# BUILD INDEX
# ============================================================

def build_index() -> TfidfIndex:

    global _index

    _index = TfidfIndex()

    if not POLICIES_DIR.exists():

        _index.build()

        return _index

    for path in sorted(
        POLICIES_DIR.glob("*.md")
    ):

        if path.name in EXCLUDED_FILES:
            continue

        for chunk in _chunk_markdown(
            path
        ):

            doc_id = (
                f"{path.name}"
                f"#{chunk['heading']}"
            )

            text = (
                f"{chunk['heading']}\n"
                f"{chunk['body']}"
            )

            _index.add(
                doc_id,
                text,
                metadata={
                    "source_file": path.name,
                    "heading": chunk[
                        "heading"
                    ],
                },
            )

    _index.build()

    return _index


# ============================================================
# QUERY NORMALIZATION
# ============================================================

def _expand_policy_query(
    query: str,
) -> str:

    query_lower = query.lower()

    expansions = []

    if any(
        word in query_lower
        for word in [
            "hardship",
            "restructur",
            "relief",
            "payment",
            "assistance",
        ]
    ):

        expansions.extend([
            "hardship",
            "restructuring",
            "hardship handoff",
            "RM outreach",
            "financial assessment",
            "eligibility review",
            "escalation",
        ])

    if "red" in query_lower:

        expansions.extend([
            "Red tier",
            "RM outreach",
            "hardship handoff",
        ])

    if "approval" in query_lower:

        expansions.extend([
            "approval",
            "advisory",
            "not approval",
        ])

    return (
        query
        + " "
        + " ".join(expansions)
    )


# ============================================================
# RETRIEVE
# ============================================================

def retrieve_policy(
    query: str,
    k: int = 3,
) -> list:

    global _index

    if _index is None:

        build_index()

    expanded_query = (
        _expand_policy_query(
            query
        )
    )

    results = _index.retrieve(
        expanded_query,
        k=max(k, 5),
    )

    # Remove weak/no-overlap results.
    #
    # This prevents unrelated policy sections from being
    # presented as authoritative matches.
    meaningful = [
        result
        for result in results
        if result.get(
            "score",
            0.0,
        ) > 0
    ]

    return meaningful[:k]


# ============================================================
# SMOKE TEST
# ============================================================

if __name__ == "__main__":

    build_index()

    results = retrieve_policy(
        "Recommend restructuring for a Red tier borrower",
        k=3,
    )

    print(
        f"Retrieved {len(results)} "
        "policy chunks:"
    )

    for result in results:

        print(
            f"[{result['score']:.3f}] "
            f"{result['id']}"
        )

        print(
            result["text"][:250]
        )

        print()