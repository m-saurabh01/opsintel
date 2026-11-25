"""Optional semantic search: nomic-embed-text served by Ollama, vectors stored in SQLite, cosine via numpy."""
import logging
import os
import sqlite3
import threading

import httpx

log = logging.getLogger(__name__)

DOC_PREFIX, QUERY_PREFIX = "search_document: ", "search_query: "
BATCH = 16
MAX_CHARS = 2000
_cache: dict = {"key": None, "ids": None, "matrix": None}
_lock = threading.Lock()


def enabled() -> bool:
    return os.environ.get("EHELP_EMBED_ENABLED", "0").lower() in ("1", "true", "yes")


def _model() -> str:
    return os.environ.get("EHELP_EMBED_MODEL", "nomic-embed-text")


def _embed(texts: list[str], prefix: str) -> list[list[float]]:
    url = os.environ.get("EHELP_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    response = httpx.post(f"{url}/api/embed", timeout=120,
                          json={"model": _model(), "input": [prefix + t[:MAX_CHARS] for t in texts]})
    response.raise_for_status()
    return response.json()["embeddings"]


def _pack(vectors: list[list[float]]) -> list[bytes]:
    import numpy as np

    arr = np.asarray(vectors, dtype=np.float32)
    arr /= np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9)
    return [row.tobytes() for row in arr]


def embed_missing(conn: sqlite3.Connection, doc_id: int | None = None) -> int:
    """Embed chunks that have no vector for the current model (one document, or all when doc_id is None)."""
    done = 0
    while True:
        rows = conn.execute(
            "SELECT c.id, c.text FROM chunks c LEFT JOIN chunk_vectors v ON v.chunk_id = c.id "
            "WHERE (v.chunk_id IS NULL OR v.model != ?)" + (" AND c.doc_id = ?" if doc_id else "") + " LIMIT ?",
            (_model(), *([doc_id] if doc_id else []), BATCH)).fetchall()
        if not rows:
            return done
        blobs = _pack(_embed([r["text"] for r in rows], DOC_PREFIX))
        conn.executemany("INSERT OR REPLACE INTO chunk_vectors(chunk_id, model, vec) VALUES (?, ?, ?)",
                         [(r["id"], _model(), b) for r, b in zip(rows, blobs)])
        done += len(rows)


def backfill(conn: sqlite3.Connection) -> None:
    try:
        count = embed_missing(conn)
        if count:
            log.info("embedded %d existing chunks", count)
    except Exception as exc:  # noqa: BLE001 - Ollama may be down; keyword search keeps working
        log.warning("embedding backfill stopped: %s", exc)
    finally:
        conn.close()


def _matrix(conn: sqlite3.Connection):
    import numpy as np

    stamp = conn.execute("SELECT count(*), coalesce(max(chunk_id), 0) FROM chunk_vectors WHERE model = ?",
                         (_model(),)).fetchone()
    key = (_model(), stamp[0], stamp[1])
    with _lock:
        if _cache["key"] != key:
            rows = conn.execute("SELECT chunk_id, vec FROM chunk_vectors WHERE model = ?", (_model(),)).fetchall()
            _cache["ids"] = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
            _cache["matrix"] = (np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
                                if rows else None)
            _cache["key"] = key
        return _cache["ids"], _cache["matrix"]


def semantic_search(conn: sqlite3.Connection, query: str, limit: int = 100) -> list[int]:
    """Chunk ids ranked by cosine similarity to the query; empty when disabled or unavailable."""
    if not enabled():
        return []
    try:
        import numpy as np

        ids, matrix = _matrix(conn)
        if matrix is None:
            return []
        q = np.frombuffer(_pack(_embed([query], QUERY_PREFIX))[0], dtype=np.float32)
        scores = matrix @ q
        top = np.argsort(-scores)[:limit]
        floor = float(os.environ.get("EHELP_EMBED_MIN_SCORE", "0.55"))
        return [int(ids[i]) for i in top if scores[i] >= floor]
    except Exception as exc:  # noqa: BLE001
        log.warning("semantic search unavailable: %s", exc)
        return []
