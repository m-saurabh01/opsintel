"""Rank-quality evaluation of search modes against a query set with expected files."""

import json
import sqlite3
from pathlib import Path

from opsintel.config import Settings
from opsintel.hybrid import hybrid_search, keyword_candidates
from opsintel.search import InvalidQuery, SearchRequest, search
from opsintel.terms import NEVER_MATCH

MODES = ("fulltext", "keywords", "semantic", "hybrid")
FETCH = 50


def load_queries(path: Path) -> tuple[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["repo"], data["queries"]


def _unique(paths: list[str]) -> list[str]:
    return list(dict.fromkeys(paths))


def _keywords(conn: sqlite3.Connection, req: SearchRequest) -> list[str]:
    from opsintel.hybrid import fetch_results

    ids = keyword_candidates(conn, req)
    hits = fetch_results(conn, ids, NEVER_MATCH)
    return [hits[chunk_id]["path"] for chunk_id in ids if chunk_id in hits]


def ranked_files(conn: sqlite3.Connection, settings: Settings, mode: str, query: str,
                 repo_ids: list[int]) -> list[str]:
    req = SearchRequest(q=query, repo_ids=repo_ids, page_size=FETCH)
    if mode == "keywords":
        return _unique(_keywords(conn, req))
    try:
        if mode == "fulltext":
            return _unique([hit["path"] for hit in search(conn, req)["results"]])
        found = hybrid_search(conn, req, settings, semantic_only=mode == "semantic")
    except InvalidQuery:
        return []
    return _unique([hit["path"] for hit in found["results"]])


def evaluate(conn: sqlite3.Connection, settings: Settings, queries: list[dict], repo_ids: list[int],
             modes: tuple[str, ...] = MODES, depth: int = 10) -> dict:
    summary: dict[str, dict] = {}
    for mode in modes:
        reciprocal, hit1, hit5, empty, misses = [], 0, 0, 0, []
        for item in queries:
            ranked = ranked_files(conn, settings, mode, item["q"], repo_ids)[:depth]
            position = next((i for i, path in enumerate(ranked, start=1) if path in item["expect"]), None)
            reciprocal.append(1 / position if position else 0.0)
            hit1 += position == 1
            hit5 += position is not None and position <= 5
            empty += not ranked
            if position is None or position > 5:
                misses.append({"q": item["q"], "rank": position, "top": ranked[:3]})
        total = len(queries)
        summary[mode] = {
            "mrr": round(sum(reciprocal) / total, 3),
            "hit@1": round(hit1 / total, 3),
            "hit@5": round(hit5 / total, 3),
            "no_results": empty,
            "queries": total,
            "misses": misses,
        }
    return summary
