import hashlib
import json
import math
import sqlite3
from functools import lru_cache

import httpx

from opsintel.db import transaction


class EmbeddingError(RuntimeError):
    pass


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embedding_prefixes(model: str) -> tuple[str, str]:
    """(query_prefix, document_prefix): nomic models are trained with task prefixes and degrade without them."""
    if "nomic" in model.lower():
        return "search_query: ", "search_document: "
    return "", ""


def _validate_vectors(vectors: list, expected: int) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != expected:
        raise EmbeddingError(f"Ollama returned {len(vectors) if isinstance(vectors, list) else 'invalid'} "
                             f"embeddings for {expected} inputs")
    checked: list[list[float]] = []
    dimensions = None
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            raise EmbeddingError("Ollama returned an empty or invalid embedding")
        if dimensions is None:
            dimensions = len(vector)
        if len(vector) != dimensions:
            raise EmbeddingError("Ollama returned embeddings with inconsistent dimensions")
        try:
            values = [float(value) for value in vector]
        except (TypeError, ValueError) as exc:
            raise EmbeddingError("Ollama returned non-numeric embedding values") from exc
        if not all(math.isfinite(value) for value in values):
            raise EmbeddingError("Ollama returned non-finite embedding values")
        checked.append(values)
    return checked


async def embed_texts(base_url: str, model: str, texts: list[str], timeout_s: float = 60) -> list[list[float]]:
    if not model.strip():
        raise EmbeddingError("OLLAMA_EMBED_MODEL is not configured")
    if not texts:
        return []
    try:
        async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s) as client:
            response = await client.post("/api/embed", json={"model": model, "input": texts})
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise EmbeddingError(f"Ollama embedding request failed: {exc}") from exc
    return _validate_vectors(payload.get("embeddings"), len(texts))


@lru_cache(maxsize=256)
def embed_query(base_url: str, model: str, query: str, timeout_s: float = 30.0) -> tuple[float, ...]:
    if not model.strip():
        raise EmbeddingError("OLLAMA_EMBED_MODEL is not configured")
    text = embedding_prefixes(model)[0] + query
    try:
        response = httpx.post(base_url.rstrip("/") + "/api/embed", json={"model": model, "input": [text]},
                              timeout=timeout_s)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise EmbeddingError(f"Ollama embedding request failed: {exc}") from exc
    return tuple(_validate_vectors(payload.get("embeddings"), 1)[0])


async def index_embeddings(conn: sqlite3.Connection, base_url: str, model: str, repo_ids: list[int] | None = None,
                          batch_size: int = 32, timeout_s: float = 60) -> dict:
    if batch_size < 1:
        raise ValueError("embedding batch size must be positive")
    if repo_ids and len(repo_ids) != 1:
        raise ValueError("embedding indexing accepts at most one repository filter")
    repo_id = repo_ids[0] if repo_ids else None
    document_prefix = embedding_prefixes(model)[1]
    cached = {row["text_hash"] for row in conn.execute(
        "SELECT text_hash FROM embedding_cache WHERE model = ?", (model,)
    )}
    seen: set[str] = set()
    texts_seen = embedded = cached_count = 0
    dimensions = None
    last_chunk_id = 0
    while True:
        rows = conn.execute(
            "SELECT c.id, c.text FROM chunks c JOIN files f ON f.id = c.file_id "
            "JOIN repositories r ON r.id = f.repo_id "
            "WHERE r.enabled = 1 AND (? IS NULL OR f.repo_id = ?) AND c.id > ? ORDER BY c.id LIMIT ?",
            (repo_id, repo_id, last_chunk_id, batch_size),
        ).fetchall()
        if not rows:
            break
        last_chunk_id = rows[-1]["id"]
        batch_by_hash = {}
        for row in rows:
            prefixed = document_prefix + row["text"]
            key = text_hash(prefixed)
            if key in seen:
                continue
            seen.add(key)
            texts_seen += 1
            if key in cached:
                cached_count += 1
            else:
                batch_by_hash[key] = prefixed
        batch = list(batch_by_hash.values())
        if not batch:
            continue
        vectors = await embed_texts(base_url, model, batch, timeout_s)
        cache_embeddings(conn, model, batch, vectors)
        cached.update(batch_by_hash)
        embedded += len(batch)
        dimensions = len(vectors[0]) if vectors else dimensions
    return {
        "model": model,
        "texts_seen": texts_seen,
        "embedded": embedded,
        "cached": cached_count,
        "dimensions": dimensions,
    }


def get_cached_embedding(conn: sqlite3.Connection, model: str, text: str) -> list[float] | None:
    row = conn.execute(
        "SELECT vector_json FROM embedding_cache WHERE model = ? AND text_hash = ?",
        (model, text_hash(text)),
    ).fetchone()
    return json.loads(row["vector_json"]) if row else None


def cache_embeddings(conn: sqlite3.Connection, model: str, texts: list[str], vectors: list[list[float]]) -> None:
    if len(texts) != len(vectors):
        raise ValueError("embedding count must match text count")
    checked = _validate_vectors(vectors, len(texts))
    with transaction(conn):
        conn.executemany(
            "INSERT INTO embedding_cache(model, text_hash, dimensions, vector_json) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(model, text_hash) DO UPDATE SET dimensions = excluded.dimensions, "
            "vector_json = excluded.vector_json, created_at = datetime('now')",
            [(model, text_hash(text), len(vector), json.dumps(vector, separators=(",", ":")))
               for text, vector in zip(texts, checked, strict=True)],
        )
