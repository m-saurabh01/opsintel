# OCR + Hybrid Search (Chroma) — Manual Application Guide

Apply these edits to the eHelp backend (`eHelp/backend/`) by hand. Edit the files in the order given;
every path is relative to `backend/`. Line numbers refer to the code **before** your edits, so search for the
quoted anchor text if they have drifted.

Alternative: `git apply -p3 ../ocr-hybrid-chroma.patch` from `backend/` (the patch is next to this file).

What you get:

- **OCR** for scanned PDFs through the Tesseract binary (already coded in `parsers/pdf.py`, only needs wiring).
- **Hybrid search**: SQLite FTS5 BM25 plus `nomic-embed-text` vectors (Ollama) stored in ChromaDB, merged by
  reciprocal-rank fusion, for both Global Search and the AI assistant.
- A one-line fix: `Response` was missing from the `fastapi.responses` import in `app.py` (search and document metadata
  crash without it).

---

## 0. Prerequisites (offline)

1. Ollama has the model: `ollama list` shows `nomic-embed-text` (copy `~/.ollama/models` from an online machine).
2. `chromadb` wheel set installed in the backend venv (tested with 1.5.9, Python 3.12).
3. For OCR: `tesseract` binary with `eng.traineddata` installed.
4. Run **one** Uvicorn worker (embedded Chroma is not safe for concurrent writers). For several workers run a Chroma
   server and set `EHELP_CHROMA_URL`.

---

## 1. NEW FILE `ehelp/embeddings.py`

Create it with exactly this content:

```python
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
```

---

## 2. `ehelp/config.py`  (OCR settings)

**2a.** In the `Config` dataclass, directly after the line `ai_max_queue: int = 4` (≈ line 18) add:

```python
    ocr_enabled: bool = False
    tesseract_path: str = ""
```

**2b.** In `load_config()`, directly after the line `ai_max_queue=int(env("EHELP_AI_MAX_QUEUE", "4")),` (≈ line 61) add:

```python
        ocr_enabled=env("EHELP_OCR_ENABLED", "0").lower() in ("1", "true", "yes"),
        tesseract_path=env("EHELP_TESSERACT_PATH", ""),
```

---

## 3. `ehelp/parsers/registry.py`  (pass OCR settings to the PDF parser)

**3a.** In `ParserRegistry.__init__` (≈ line 26) change the signature to:

```python
    def __init__(self, libreoffice_path: str = "", timeout_s: float = 120, ocr_enabled: bool = False,
                 tesseract_path: str = ""):
```

**3b.** In the `_by_ext` dict (≈ line 32) change

```python
            "pdf": PdfParser(CHARS, ocr_enabled, ""),
```

to

```python
            "pdf": PdfParser(CHARS, ocr_enabled, tesseract_path),
```

---

## 4. `ehelp/db.py`

Nothing to change. (Chroma keeps its own storage; no SQLite table is needed.)

---

## 5. `ehelp/indexing.py`  (embed on upload, clean up on reindex)

**5a.** Imports (top of file, ≈ line 6): add above `from ehelp.db import transaction`:

```python
from ehelp import embeddings
```

**5b.** In `Indexer.index_document`, find:

```python
        with transaction(self.conn):
            self.conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
```

and add one line **before** the `with`:

```python
        embeddings.delete_document(doc_id)
        with transaction(self.conn):
            self.conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
```

**5c.** At the end of `index_document`, directly after the `UPDATE documents SET index_status ...` statement and
**outside** (dedented from) the `with transaction(...)` block, add:

```python
        if embeddings.enabled() and chunks:
            try:
                embeddings.embed_missing(self.conn, doc_id)
            except Exception as exc:  # noqa: BLE001 - keyword search still works; startup backfill retries
                log.warning("embedding failed for document %s: %s", doc_id, exc)
```

---

## 6. `ehelp/app.py`

**6a.** ≈ line 15 — add `Response` to the import (bug fix, required):

```python
from fastapi.responses import FileResponse, Response, StreamingResponse
```

**6b.** ≈ line 24 — add next to the other `ehelp` imports:

```python
from ehelp import embeddings
```

**6c.** In `create_app` (≈ line 72) change

```python
    indexer = Indexer(index_conn, ParserRegistry(config.libreoffice_path))
```

to

```python
    indexer = Indexer(index_conn, ParserRegistry(config.libreoffice_path, ocr_enabled=config.ocr_enabled,
                                                 tesseract_path=config.tesseract_path))
```

**6d.** In `lifespan` (≈ line 78) add the backfill thread **before** `yield`:

```python
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if embeddings.enabled():
            threading.Thread(target=embeddings.backfill, args=(connect(config.db_path),), daemon=True).start()
        yield
        indexer.close()
        boot.close()
```

**6e.** In the `delete_document` endpoint (≈ line 483), after the `DELETE FROM documents` line add the vector cleanup:

```python
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        embeddings.delete_document(doc_id)
        (config.files_dir / row["stored_name"]).unlink(missing_ok=True)
```

---

## 7. `ehelp/search.py`  (hybrid Global Search)

**7a.** Imports: after `from dataclasses import dataclass, field` add a blank line and:

```python
from ehelp import embeddings
```

**7b.** In the `DocHit` dataclass add a field after `matches: int = 0`:

```python
    rrf: float = 0.0
```

**7c.** In `search_documents`, add `c.id AS cid,` as the first selected column of **both** chunk queries:

```python
            "SELECT c.id AS cid, c.doc_id, c.page, c.label, c.text, 0.0 AS score FROM chunks c JOIN documents d ..."
```

```python
            f"SELECT c.id AS cid, c.doc_id, c.page, c.label, snippet(chunks_fts, 0, ...
```

**7d.** Change the result loop header and add the RRF line. Replace

```python
    for row in rows:
        hit = hits.setdefault(row["doc_id"], DocHit(row["doc_id"]))
        hit.matches += 1
```

with

```python
    for rank, row in enumerate(rows):
        hit = hits.setdefault(row["doc_id"], DocHit(row["doc_id"]))
        hit.rrf += 1 / (60 + rank)
        hit.matches += 1
```

**7e.** Replace the final line of the function

```python
    return sorted(hits.values(), key=lambda h: (not h.title_match, h.best, -h.matches))
```

with:

```python
    vec_ids = embeddings.semantic_search(conn, query) if mode == "smart" else []
    if not vec_ids:
        return sorted(hits.values(), key=lambda h: (not h.title_match, h.best, -h.matches))
    marks = ",".join("?" * len(vec_ids))
    by_id = {r["cid"]: r for r in conn.execute(
        "SELECT c.id AS cid, c.doc_id, c.page, c.label, c.text FROM chunks c JOIN documents d ON d.id = c.doc_id "
        f"WHERE c.id IN ({marks}){where}", [*vec_ids, *args]).fetchall()}
    shown = {r["cid"] for r in rows}
    for rank, cid in enumerate(i for i in vec_ids if i in by_id):
        row = by_id[cid]
        hit = hits.setdefault(row["doc_id"], DocHit(row["doc_id"]))
        hit.rrf += 1 / (60 + rank)
        if cid not in shown:
            hit.matches += 1
            if len(hit.snippets) < SNIPPETS_PER_DOC:
                hit.snippets.append({"page": row["page"], "label": row["label"],
                                     "text": row["text"][:220].replace("\n", " ")})
    return sorted(hits.values(), key=lambda h: (not h.title_match, -h.rrf))
```

Exact mode and keyword-only behaviour are unchanged when embeddings are off or Ollama/Chroma is unreachable.

---

## 8. `ehelp/ai.py`  (hybrid retrieval for the AI assistant)

**8a.** Imports: after `import httpx` add a blank line and:

```python
from ehelp import embeddings
```

**8b.** Add this function directly **above** `def retrieve(`:

```python
def fuse_chunks(conn: sqlite3.Connection, rows, vec_ids: list[int], category: str | None) -> list:
    """Reciprocal-rank fusion of BM25 rows and vector-ranked chunk ids."""
    scores: dict[int, float] = {}
    for rank, row in enumerate(rows):
        scores[row["id"]] = scores.get(row["id"], 0) + 1 / (60 + rank)
    for rank, cid in enumerate(vec_ids):
        scores[cid] = scores.get(cid, 0) + 1 / (60 + rank)
    by_id = {r["id"]: r for r in rows}
    missing = [i for i in scores if i not in by_id]
    if missing:
        marks = ",".join("?" * len(missing))
        extra = conn.execute(
            "SELECT c.id, c.doc_id, c.page, c.label, c.text, d.title FROM chunks c JOIN documents d ON d.id = c.doc_id "
            f"WHERE c.id IN ({marks})"
            + (" AND d.category_id = (SELECT id FROM categories WHERE slug = ?)" if category else ""),
            (*missing, *([category] if category else []))).fetchall()
        by_id.update({r["id"]: r for r in extra})
    return [by_id[i] for i in sorted(scores, key=scores.get, reverse=True) if i in by_id]
```

**8c.** Inside `retrieve()`, between the `rows = conn.execute(...)` statement and the line
`evidence, remaining, per_doc = [], max_chars, {}`, add:

```python
    vec_ids = embeddings.semantic_search(conn, question, top_k * 4)
    if vec_ids:
        rows = fuse_chunks(conn, rows, vec_ids, category)
```

---

## 9. `pyproject.toml`

Add to `dependencies`: `"chromadb>=1.0",`

---

## 10. `.env` (backend)

```
# OCR for scanned PDFs
EHELP_OCR_ENABLED=1
EHELP_TESSERACT_PATH=C:\tools\tesseract\tesseract.exe

# Hybrid search
EHELP_EMBED_ENABLED=1
EHELP_EMBED_MODEL=nomic-embed-text
EHELP_EMBED_MIN_SCORE=0.55
# Optional: where Chroma stores vectors (default <data dir>/chroma) or a Chroma server host:port
EHELP_CHROMA_PATH=
EHELP_CHROMA_URL=
```

`EHELP_OLLAMA_URL` (already used by the AI assistant) is reused for embeddings.

---

## 11. Docker / RHEL

In `Dockerfile.rhel` add `tesseract tesseract-langpack-eng` to the package install line (needs the RHEL repos or
RPMs available offline). `chromadb` comes in with `pip install` from `pyproject.toml`.

---

## 12. Activate and verify

1. Restart the app. With `EHELP_EMBED_ENABLED=1` existing chunks are embedded in the background (watch the log for
   `embedded N existing chunks`).
2. **Re-index scanned PDFs once** (Admin → document → reindex) so OCR runs; already-indexed documents are not
   re-OCR'd automatically. The document's index message will say `OCR extracted text from N scanned page(s)`.
3. Search for a synonym that is not in the text (e.g. "engine repair" for a document that says "turbine blade
   overhaul"); it should appear in Global Search and be cited by the AI assistant.
4. Optional test (add to `tests/test_api.py`) — `test_hybrid_search_finds_semantic_match` in the repo fakes
   `embeddings._embed` and checks both retrieval and cleanup on delete.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| No semantic hits, log says "semantic search unavailable" | Ollama unreachable or model not pulled; keyword search keeps working. |
| Too few semantic hits | Lower `EHELP_EMBED_MIN_SCORE` (try 0.45). Too noisy: raise it (0.65). |
| OCR warning "Tesseract was not found" | Set `EHELP_TESSERACT_PATH` or put `tesseract` on PATH; confirm `eng.traineddata` is installed. |
| Chroma errors with several workers | Run one worker, or use a Chroma server via `EHELP_CHROMA_URL`. |
| Changed `EHELP_EMBED_MODEL` | A new collection is created and re-embedded at startup; the old one can be deleted from `data/chroma`. |
