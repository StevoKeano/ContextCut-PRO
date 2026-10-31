"""
ContextCut-PRO - In-memory BM25 index for hybrid retrieval (Vector + BM25)
"""

import os
import re
import time
import threading
from typing import List, Dict, Any, Optional, Tuple

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except Exception:
    BM25_AVAILABLE = False
    BM25Okapi = None


# Simple stopwords - keep minimal to avoid hurting technical queries
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he",
    "in", "is", "it", "its", "of", "on", "that", "the", "to", "was", "were",
    "will", "with", "or", "this", "but", "they", "have", "had", "what", "when",
    "where", "who", "which", "why", "how", "i", "you", "we", "they", "me", "my",
    "your", "our", "their", "can", "could", "should", "would", "do", "does", "did"
}


class BM25Index:
    def __init__(self, qclient, collection: str, ttl_seconds: int = 30):
        self.qclient = qclient
        self.collection = collection
        self.ttl_seconds = ttl_seconds

        self._lock = threading.RLock()
        self._bm25 = None
        self._corpus_tokens: List[List[str]] = []
        self._docs: List[Dict[str, Any]] = []  # parallel to corpus_tokens
        self._last_build = 0.0
        self._dirty = True

    def _tokenize(self, text: str) -> List[str]:
        if not text:
            return []
        # Lowercase
        text = text.lower()
        # Keep alphanumerics, underscores, hyphens (good for code/identifiers)
        tokens = re.findall(r"[a-z0-9_\-]+", text)
        result = []
        for t in tokens:
            # Be more lenient with numbers (IDs, reservation numbers etc)
            if t.isdigit():
                if len(t) >= 4:
                    result.append(t)
                continue
            if len(t) <= 2:
                continue
            if t in _STOPWORDS:
                continue
            result.append(t)
        return result

    def invalidate(self):
        with self._lock:
            self._dirty = True

    def is_fresh(self) -> bool:
        with self._lock:
            if self._dirty or self._bm25 is None:
                return False
            if time.time() - self._last_build >= self.ttl_seconds:
                return False
            return True

    def build(self, force: bool = False) -> bool:
        if not BM25_AVAILABLE:
            return False

        with self._lock:
            if not force and not self._dirty and self._bm25 is not None:
                if time.time() - self._last_build < self.ttl_seconds:
                    return True
            self._dirty = False

        try:
            corpus_tokens: List[List[str]] = []
            docs: List[Dict[str, Any]] = []

            # Scroll all points from collection
            offset = None
            while True:
                try:
                    points, next_offset = self.qclient.scroll(
                        collection_name=self.collection,
                        limit=1000,
                        offset=offset,
                        with_payload=True,
                        with_vectors=False,
                    )
                except TypeError:
                    # Older qdrant-client API
                    points, next_offset = self.qclient.scroll(
                        self.collection,
                        limit=1000,
                        offset=offset,
                        with_payload=True,
                        with_vectors=False,
                    )

                if not points:
                    break

                for p in points:
                    payload = getattr(p, "payload", None) or {}
                    text = payload.get("text", "") or ""
                    if not text:
                        continue
                    tokens = self._tokenize(text)
                    if not tokens:
                        continue
                    corpus_tokens.append(tokens)
                    docs.append({
                        "id": getattr(p, "id"),
                        "text": text,
                        "filename": payload.get("filename", payload.get("source", "?")),
                        "path": payload.get("path", ""),
                        "chunk_index": payload.get("chunk_index"),
                        "total_chunks": payload.get("total_chunks"),
                    })

                if next_offset is None:
                    break
                offset = next_offset

            if not corpus_tokens:
                with self._lock:
                    self._bm25 = None
                    self._corpus_tokens = []
                    self._docs = []
                    self._last_build = time.time()
                return False

            bm25 = BM25Okapi(corpus_tokens)

            with self._lock:
                self._bm25 = bm25
                self._corpus_tokens = corpus_tokens
                self._docs = docs
                self._last_build = time.time()
                self._dirty = False

            return True
        except Exception as e:
            print(f"[bm25] build error: {e}")
            with self._lock:
                self._dirty = True
            return False

    def ensure_fresh(self, force: bool = False) -> bool:
        if not BM25_AVAILABLE:
            return False
        if force or not self.is_fresh():
            return self.build(force=force)
        return True

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        if not BM25_AVAILABLE:
            return []
        if not self.ensure_fresh():
            return []

        with self._lock:
            bm25 = self._bm25
            docs = self._docs
            if bm25 is None or not docs:
                return []

        tokens = self._tokenize(query)
        if not tokens:
            return []

        try:
            scores = bm25.get_scores(tokens)
        except Exception:
            return []

        # Get top results
        scored = []
        for i, s in enumerate(scores):
            if s <= 0:
                continue
            scored.append((i, float(s)))
        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[:limit]

        results = []
        for idx, s in scored:
            doc = docs[idx]
            results.append({
                "id": doc["id"],
                "score": s,
                "filename": doc["filename"],
                "text": doc["text"],
                "path": doc["path"],
                "chunk_index": doc["chunk_index"],
            })
        return results

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "available": BM25_AVAILABLE,
                "built": self._bm25 is not None,
                "docs": len(self._docs),
                "last_build": self._last_build,
                "dirty": self._dirty,
                "age_seconds": time.time() - self._last_build if self._last_build else None,
            }
