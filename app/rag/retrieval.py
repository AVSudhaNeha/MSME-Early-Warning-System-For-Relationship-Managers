"""
Day 16 — lightweight, dependency-free retrieval engine shared by the Risk
Policy store (app/rag/policy_store.py) and the Case Trace store
(app/rag/trace_store.py).

Deliberately NOT using chromadb + a downloaded sentence-transformer
model: this sandbox's network is domain-allowlisted and doesn't include
huggingface.co, so a model download would just fail; a real deployment
might not have Azure OpenAI embeddings configured either. This uses a
plain TF-IDF + cosine-similarity scorer instead — zero external calls,
no model download, fully testable offline, good enough for a corpus this
small (a handful of policy docs / one borrower's case-trace history).

EMBEDDING SWAP: retrieve() only cares about (id, text, metadata) pairs in
and (id, text, metadata, score) pairs out. If real embeddings become
available later, swap TfidfIndex's internals for a vector store — nothing
in policy_store.py, trace_store.py, or explanation_agent.py needs to
change.
"""

import math
import re
from collections import Counter


def _tokenize(text: str) -> list:
    return re.findall(r"[a-z0-9]+", text.lower())


class TfidfIndex:
    """A minimal from-scratch TF-IDF index — not meant to compete with a
    real vector store on a large corpus, meant to be correct and require
    zero external dependencies for a small one."""

    def __init__(self):
        self._docs = []  # [{"id", "text", "metadata"}]
        self._df = Counter()
        self._built = False

    def add(self, doc_id: str, text: str, metadata: dict = None) -> None:
        self._docs.append({"id": doc_id, "text": text, "metadata": metadata or {}})
        self._built = False

    def build(self) -> None:
        self._df = Counter()
        for doc in self._docs:
            for term in set(_tokenize(doc["text"])):
                self._df[term] += 1
        self._built = True

    def _vector(self, text: str) -> Counter:
        n = len(self._docs) or 1
        tf = Counter(_tokenize(text))
        vec = Counter()
        for term, count in tf.items():
            idf = math.log((n + 1) / (self._df.get(term, 0) + 1)) + 1
            vec[term] = count * idf
        return vec

    @staticmethod
    def _cosine(a: Counter, b: Counter) -> float:
        common = set(a) & set(b)
        dot = sum(a[t] * b[t] for t in common)
        norm_a = math.sqrt(sum(v * v for v in a.values())) or 1.0
        norm_b = math.sqrt(sum(v * v for v in b.values())) or 1.0
        return dot / (norm_a * norm_b)

    def retrieve(self, query: str, k: int = 3) -> list:
        if not self._built:
            self.build()
        query_vec = self._vector(query)
        scored = []
        for doc in self._docs:
            score = self._cosine(query_vec, self._vector(doc["text"]))
            scored.append({**doc, "score": score})
        scored.sort(key=lambda d: d["score"], reverse=True)
        return scored[:k]


if __name__ == "__main__":
    idx = TfidfIndex()
    idx.add("doc1", "Red tier borrowers require RM outreach and hardship handoff")
    idx.add("doc2", "Amber tier borrowers require relationship manager outreach")
    idx.add("doc3", "Green tier borrowers are logged only, no action required")
    for r in idx.retrieve("what happens for a red tier case", k=2):
        print(f"[{r['score']:.3f}] {r['id']}: {r['text']}")