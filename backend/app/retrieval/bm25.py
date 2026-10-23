import math
import re
import threading
from collections import Counter, defaultdict

TOKEN_RE = re.compile(r"[a-z0-9]+")
K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


class BM25Index:
    """Okapi BM25 over chunk text. Rebuilt from PostgreSQL when the index revision changes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.revision = -1
        self.doc_ids: list[str] = []
        self.tfs: list[Counter] = []
        self.lengths: list[int] = []
        self.df: dict[str, int] = {}
        self.avgdl = 0.0
        self.meta: dict[str, dict] = {}

    def rebuild(self, rows: list[dict], revision: int) -> None:
        doc_ids: list[str] = []
        tfs: list[Counter] = []
        lengths: list[int] = []
        df: dict[str, int] = defaultdict(int)
        meta: dict[str, dict] = {}
        for row in rows:
            tokens = tokenize(row["content"])
            counts = Counter(tokens)
            doc_ids.append(row["id"])
            tfs.append(counts)
            lengths.append(len(tokens) or 1)
            for term in counts:
                df[term] += 1
            meta[row["id"]] = row
        avgdl = (sum(lengths) / len(lengths)) if lengths else 0.0
        with self._lock:
            self.revision = revision
            self.doc_ids = doc_ids
            self.tfs = tfs
            self.lengths = lengths
            self.df = dict(df)
            self.avgdl = avgdl
            self.meta = meta

    def search(
        self,
        query: str,
        top_k: int,
        allowed_ids: set[str] | None = None,
    ) -> list[dict]:
        terms = tokenize(query)
        if not terms:
            return []
        with self._lock:
            doc_ids = self.doc_ids
            tfs = self.tfs
            lengths = self.lengths
            df = self.df
            avgdl = self.avgdl or 1.0
            total = len(doc_ids)
        if total == 0:
            return []
        scores: list[tuple[str, float]] = []
        unique_terms = list(dict.fromkeys(terms))
        idf = {}
        for term in unique_terms:
            document_frequency = df.get(term, 0)
            idf[term] = math.log(1 + (total - document_frequency + 0.5) / (document_frequency + 0.5))
        for index, doc_id in enumerate(doc_ids):
            if allowed_ids is not None and doc_id not in allowed_ids:
                continue
            score = 0.0
            length = lengths[index]
            counts = tfs[index]
            for term in unique_terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                denom = frequency + K1 * (1 - B + B * length / avgdl)
                score += idf[term] * (frequency * (K1 + 1)) / denom
            if score > 0:
                scores.append((doc_id, score))
        scores.sort(key=lambda item: item[1], reverse=True)
        ranked = []
        for rank, (doc_id, score) in enumerate(scores[:top_k], start=1):
            ranked.append({"id": doc_id, "score": score, "rank": rank})
        return ranked


bm25_index = BM25Index()
