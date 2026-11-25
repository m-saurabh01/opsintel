"""Optional semantic search: nomic-embed-text served by Ollama, vectors stored in ChromaDB (cosine)."""
import logging
import os
import re
import sqlite3
import threading

import httpx

log = logging.getLogger(__name__)

DOC_PREFIX, QUERY_PREFIX = "search_document: ", "search_query: "
BATCH = 16
PAGE = 64
MAX_CHARS = 2000
_lock = threading.Lock()
_state: dict = {"client": None, "name": None, "col": None}


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


def _collection():
    """One collection per embedding model, so changing EHELP_EMBED_MODEL re-embeds cleanly."""
    import chromadb

    name = "chunks_" + re.sub(r"[^a-zA-Z0-9_-]", "_", _model())
    with _lock:
        if _state["col"] is None or _state["name"] != name:
            if _state["client"] is None:
                url = os.environ.get("EHELP_CHROMA_URL", "")
                if url:
                    host, _, port = url.removeprefix("http://").removeprefix("https://").partition(":")
                    _state["client"] = chromadb.HttpClient(host=host, port=int(port or 8000))
                else:
                    path = os.environ.get("EHELP_CHROMA_PATH") or str(
                        __import__("pathlib").Path(os.environ.get("EHELP_DATA_DIR", "./data")) / "chroma")
                    _state["client"] = chromadb.PersistentClient(path=path)
            _state["col"] = _state["client"].get_or_create_collection(name, metadata={"hnsw:space": "cosine"})
            _state["name"] = name
        return _state["col"]


def embed_missing(conn: sqlite3.Connection, doc_id: int | None = None) -> int:
    """Embed chunks that are not in Chroma yet (one document, or all when doc_id is None)."""
    col, done, last = _collection(), 0, 0
    while True:
        rows = conn.execute(
            "SELECT id, doc_id, text FROM chunks WHERE id > ?" + (" AND doc_id = ?" if doc_id else "")
            + " ORDER BY id LIMIT ?", (last, *([doc_id] if doc_id else []), PAGE)).fetchall()
        if not rows:
            return done
        last = rows[-1]["id"]
        have = set(col.get(ids=[str(r["id"]) for r in rows], include=[])["ids"])
        todo = [r for r in rows if str(r["id"]) not in have]
        for i in range(0, len(todo), BATCH):
            part = todo[i:i + BATCH]
            col.upsert(ids=[str(r["id"]) for r in part],
                       embeddings=_embed([r["text"] for r in part], DOC_PREFIX),
                       metadatas=[{"doc_id": r["doc_id"]} for r in part])
            done += len(part)


def delete_document(doc_id: int) -> None:
    """Remove a document's vectors (Chroma has no cascade from SQLite)."""
    if not enabled():
        return
    try:
        _collection().delete(where={"doc_id": doc_id})
    except Exception as exc:  # noqa: BLE001
        log.warning("could not delete vectors for document %s: %s", doc_id, exc)


def backfill(conn: sqlite3.Connection) -> None:
    try:
        count = embed_missing(conn)
        if count:
            log.info("embedded %d existing chunks", count)
    except Exception as exc:  # noqa: BLE001 - Ollama may be down; keyword search keeps working
        log.warning("embedding backfill stopped: %s", exc)
    finally:
        conn.close()


def semantic_search(conn: sqlite3.Connection, query: str, limit: int = 100) -> list[int]:
    """Chunk ids ranked by cosine similarity to the query; empty when disabled or unavailable."""
    if not enabled():
        return []
    try:
        col = _collection()
        total = col.count()
        if not total:
            return []
        res = col.query(query_embeddings=_embed([query], QUERY_PREFIX), n_results=min(limit, total),
                        include=["distances"])
        floor = float(os.environ.get("EHELP_EMBED_MIN_SCORE", "0.55"))
        return [int(i) for i, d in zip(res["ids"][0], res["distances"][0]) if 1 - d >= floor]
    except Exception as exc:  # noqa: BLE001
        log.warning("semantic search unavailable: %s", exc)
        return []
