"""Vector candidate search and reciprocal-rank fusion over the existing lexical index."""

import heapq
import json
import math
import re
import sqlite3
from collections import defaultdict
from dataclasses import replace

from opsintel.config import Settings
from opsintel.embeddings import embed_query, embedding_prefixes, text_hash
from opsintel.search import InvalidQuery, SearchRequest, _filters, _result, build_match, search
from opsintel.search_metadata import metadata_query_terms
from opsintel.terms import NEVER_MATCH, search_terms, substring_pattern, terms_pattern

RRF_K = 60
CANDIDATES = 50
SCAN_BATCH = 500
SEMANTIC_RELATIVE_CUTOFF = 0.10
MAX_RELATED = 10


class SemanticUnavailable(RuntimeError):
    pass


def semantic_available(settings: Settings) -> bool:
    return bool(settings.semantic_search_enabled and settings.ollama_embed_model.strip())


def _norm(vector) -> float:
    return math.sqrt(sum(x * x for x in vector))


def vector_candidates(conn: sqlite3.Connection, req: SearchRequest, settings: Settings,
                      limit: int = CANDIDATES) -> list[tuple[int, float]]:
    """Top chunks by cosine similarity among chunks that match the request filters and have a cached vector."""
    model = settings.ollama_embed_model
    if conn.execute("SELECT 1 FROM embedding_cache WHERE model = ? LIMIT 1", (model,)).fetchone() is None:
        raise SemanticUnavailable(f"no embeddings cached for '{model}'; run `opsintel experimental embedding-index`")
    query = embed_query(settings.ollama_base_url, model, req.q)
    query_norm = _norm(query)
    if query_norm == 0:
        return []
    document_prefix = embedding_prefixes(model)[1]
    where, params = _filters(replace(req, mode="fulltext"))
    scan = (
        "SELECT c.id, c.text FROM chunks c JOIN files f ON f.id = c.file_id "  # noqa: S608
        "JOIN repositories r ON r.id = f.repo_id "
        f"WHERE r.enabled = 1{where} AND c.id > ? ORDER BY c.id LIMIT ?"
    )
    best: list[tuple[float, int]] = []
    last_id = 0
    while True:
        rows = conn.execute(scan, [*params, last_id, SCAN_BATCH]).fetchall()
        if not rows:
            break
        last_id = rows[-1]["id"]
        hashes = {row["id"]: text_hash(document_prefix + row["text"]) for row in rows}
        marks = ",".join("?" * len(set(hashes.values())))
        vectors = {r["text_hash"]: r["vector_json"] for r in conn.execute(
            f"SELECT text_hash, vector_json FROM embedding_cache WHERE model = ? AND text_hash IN ({marks})",  # noqa: S608
            [model, *set(hashes.values())],
        )}
        for chunk_id, digest in hashes.items():
            raw = vectors.get(digest)
            if raw is None:
                continue
            vector = json.loads(raw)
            if len(vector) != len(query):
                continue
            norm = _norm(vector)
            if norm == 0:
                continue
            score = sum(a * b for a, b in zip(query, vector, strict=True)) / (query_norm * norm)
            if len(best) < limit:
                heapq.heappush(best, (score, chunk_id))
            elif score > best[0][0]:
                heapq.heapreplace(best, (score, chunk_id))
    return [(chunk_id, score) for score, chunk_id in sorted(best, reverse=True)]


def keyword_candidates(conn: sqlite3.Connection, req: SearchRequest, limit: int = CANDIDATES) -> list[int]:
    """Per-term full-text queries fused with RRF, so a natural-language question is not an all-terms AND."""
    terms = search_terms(req.q)
    subqueries = [" ".join(terms[:5]), *terms] if terms else [req.q]
    scores: dict[int, float] = defaultdict(float)
    for sub in dict.fromkeys(subqueries):
        try:
            found = search(conn, replace(req, q=sub, mode="fulltext", page=1, page_size=limit))
        except InvalidQuery:
            continue
        for rank, hit in enumerate(found["results"], start=1):
            scores[hit["chunk_id"]] += 1 / (RRF_K + rank)
    return sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:limit]


def fuse(rankings: dict[str, list[int]]) -> dict[int, float]:
    scores: dict[int, float] = defaultdict(float)
    for ranked in rankings.values():
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] += 1 / (RRF_K + rank)
    return scores


def fetch_results(conn: sqlite3.Connection, chunk_ids: list[int], pattern: re.Pattern) -> dict[int, dict]:
    if not chunk_ids:
        return {}
    marks = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        "SELECT c.id AS chunk_id, c.file_id, c.text, c.coord_kind, c.start_line, c.end_line, c.page, c.sheet, "  # noqa: S608
        "c.row_num, c.section_path, c.extra_json, "
        "f.path, f.file_type, f.language, f.branch, f.commit_sha, f.line_count, f.indexed_at, "
        "r.id AS repo_id, r.name AS repo_name, r.kind AS repo_kind, 0.0 AS score "
        "FROM chunks c JOIN files f ON f.id = c.file_id JOIN repositories r ON r.id = f.repo_id "
        f"WHERE c.id IN ({marks}) AND r.enabled = 1",
        chunk_ids,
    ).fetchall()
    return {row["chunk_id"]: _result(row, pattern) for row in rows}


def _metadata_candidates(conn: sqlite3.Connection, req: SearchRequest, limit: int = CANDIDATES) -> list[int]:
    terms = metadata_query_terms(req.q)
    where, params = _filters(replace(req, mode="fulltext"))
    scores: dict[int, float] = defaultdict(float)
    for term in terms:
        match = '"' + term.replace('"', '""') + '"'
        rows = conn.execute(
            "SELECT c.id FROM chunks_meta_fts JOIN chunks c ON c.id = chunks_meta_fts.rowid "  # noqa: S608
            "JOIN files f ON f.id = c.file_id JOIN repositories r ON r.id = f.repo_id "
            f"WHERE chunks_meta_fts MATCH ? AND r.enabled = 1{where} "
            "ORDER BY bm25(chunks_meta_fts) LIMIT ?",  # noqa: S608
            [match, *params, limit],
        ).fetchall()
        for rank, row in enumerate(rows, start=1):
            scores[row["id"]] += 1 / (RRF_K + rank)
    return sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:limit]


def _substring_candidates(conn: sqlite3.Connection, req: SearchRequest, terms: list[str],
                          limit: int = CANDIDATES) -> list[int]:
    where, params = _filters(replace(req, mode="fulltext"))
    values = list(dict.fromkeys(part for term in terms for part in re.split(r"[_\-.]+", term)
                                if len(part) >= 3))
    scores: dict[int, float] = {}
    for value in values:
        rows = conn.execute(
            "SELECT c.id FROM chunks_tri JOIN chunks c ON c.id = chunks_tri.rowid "  # noqa: S608
            "JOIN files f ON f.id = c.file_id JOIN repositories r ON r.id = f.repo_id "
            f"WHERE chunks_tri MATCH ? AND r.enabled = 1{where} "
            "ORDER BY bm25(chunks_tri) LIMIT ?",  # noqa: S608
            ['"' + value.replace('"', '""') + '"', *params, limit],
        ).fetchall()
        for rank, row in enumerate(rows, start=1):
            chunk_id = row["id"]
            scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (RRF_K + rank)
    return sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:limit]


def hybrid_search(conn: sqlite3.Connection, req: SearchRequest, settings: Settings, *,
                  semantic_only: bool = False, include_semantic: bool = True) -> dict:
    _, _, fallback_pattern = build_match(replace(req, mode="fulltext"))  # rejects queries without searchable terms
    terms = search_terms(req.q)
    pattern = terms_pattern(terms) if terms else fallback_pattern
    lexical = [] if semantic_only else keyword_candidates(conn, req)
    metadata = [] if semantic_only else _metadata_candidates(conn, req)
    semantic = vector_candidates(conn, req, settings) if include_semantic and semantic_available(settings) else []
    cosine = dict(semantic)
    semantic_ranked = [chunk_id for chunk_id, _ in semantic]
    if semantic_ranked:
        cutoff = cosine[semantic_ranked[0]] - SEMANTIC_RELATIVE_CUTOFF
        semantic_ranked = [chunk_id for chunk_id in semantic_ranked if cosine[chunk_id] >= cutoff]
    substring = [] if semantic_only else _substring_candidates(conn, req, terms)
    primary = set(lexical) | set(metadata)
    substring_only = [chunk_id for chunk_id in substring if chunk_id not in primary]
    related_candidates = semantic_ranked if semantic_only else [
        chunk_id for chunk_id in semantic_ranked if chunk_id not in primary and chunk_id not in substring_only
    ]
    related = related_candidates[:MAX_RELATED]
    rankings = {"semantic": semantic_ranked} if semantic_only else {
        "lexical": lexical, "metadata": metadata, "semantic": [chunk_id for chunk_id in semantic_ranked
                                                                    if chunk_id in primary],
    }
    if not semantic_only:
        rankings = {name: ranked for name, ranked in rankings.items() if ranked}
    fused = fuse(rankings)
    primary_order = sorted(primary, key=lambda chunk_id: (-fused.get(chunk_id, 0), chunk_id))
    if semantic_only:
        primary_order = []
    ordered = [*primary_order, *related, *substring_only]
    offset = (req.page - 1) * req.page_size
    page_ids = ordered[offset:offset + req.page_size]
    primary_hits = fetch_results(conn, [chunk_id for chunk_id in page_ids if chunk_id in primary], pattern)
    related_hits = fetch_results(conn, [chunk_id for chunk_id in page_ids if chunk_id in related], NEVER_MATCH)
    substring_hits = fetch_results(conn, [chunk_id for chunk_id in page_ids if chunk_id in substring_only],
                                   substring_pattern(terms))
    results = []
    for chunk_id in page_ids:
        hit = substring_hits.get(chunk_id) if chunk_id in substring_only else \
            related_hits.get(chunk_id) if chunk_id in related else primary_hits.get(chunk_id)
        if hit is None:
            continue
        hit["score"] = round(fused.get(chunk_id, 0), 5)
        hit["sources"] = [name for name, ranked in rankings.items() if chunk_id in ranked]
        hit["match_type"] = "related" if chunk_id in related else \
            "substring" if chunk_id in substring_only else "match"
        if chunk_id in cosine:
            hit["semantic_score"] = round(cosine[chunk_id], 4)
        results.append(hit)
    match_total = len(primary)
    related_total = len(related)
    substring_total = len(substring_only)
    match_lower_bound = not semantic_only and (len(lexical) >= CANDIDATES or len(metadata) >= CANDIDATES)
    substring_lower_bound = not semantic_only and len(substring) >= CANDIDATES
    related_truncated = len(related_candidates) > MAX_RELATED or len(semantic) >= CANDIDATES
    return {
        "query": req.q,
        "mode": "semantic" if semantic_only else "hybrid",
        "page": req.page,
        "page_size": req.page_size,
        "total": len(ordered),
        "match_total": match_total,
        "match_total_is_lower_bound": match_lower_bound,
        "related_total": related_total,
        "related_truncated": related_truncated,
        "substring_total": substring_total,
        "substring_total_is_lower_bound": substring_lower_bound,
        "total_is_lower_bound": match_lower_bound or related_truncated or substring_lower_bound,
        "results": results,
    }
