"""Simple pure-Python BM25 retriever for Agent-J failure-class runbooks."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
DEFAULT_RUNBOOKS_DIR = Path(__file__).resolve().parent / "runbooks"


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class BM25RunbookRetriever:
    """BM25okapi retriever over markdown runbooks."""

    def __init__(self, runbooks_dir: Path | str | None = None, k1: float = 1.5, b: float = 0.75) -> None:
        self.runbooks_dir = Path(runbooks_dir) if runbooks_dir else DEFAULT_RUNBOOKS_DIR
        self.k1 = k1
        self.b = b
        self.docs: list[dict[str, Any]] = []
        self.doc_freqs: Counter[str] = Counter()
        self.avgdl: float = 0.0
        self._load()

    def _load(self) -> None:
        if not self.runbooks_dir.exists():
            return
        total_len = 0
        for path in sorted(self.runbooks_dir.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            title = path.stem.replace("_", " ").title()
            for line in content.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            tokens = _tokenize(content)
            tf = Counter(tokens)
            self.docs.append(
                {
                    "id": path.stem,
                    "title": title,
                    "path": str(path),
                    "content": content,
                    "tokens": tokens,
                    "tf": tf,
                    "dl": len(tokens),
                }
            )
            total_len += len(tokens)
            for term in tf:
                self.doc_freqs[term] += 1
        if self.docs:
            self.avgdl = total_len / len(self.docs)

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Return top_k matching runbooks ranked by BM25 score."""
        if not self.docs:
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        n_docs = len(self.docs)
        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in self.docs:
            score = 0.0
            dl = doc["dl"]
            tf = doc["tf"]
            for term in q_tokens:
                df = self.doc_freqs.get(term, 0)
                if df == 0:
                    continue
                idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
                freq = tf.get(term, 0)
                if freq == 0:
                    continue
                denom = freq + self.k1 * (1.0 - self.b + self.b * (dl / self.avgdl))
                score += idf * (freq * (self.k1 + 1.0)) / denom
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "id": doc["id"],
                "title": doc["title"],
                "score": round(score, 4),
                "content": doc["content"],
            }
            for score, doc in scored[:top_k]
        ]
