import re
import sqlite3
from dataclasses import dataclass, field

MARK_OPEN, MARK_CLOSE = "\x02", "\x03"
MAX_HITS = 2000
SNIPPETS_PER_DOC = 3


@dataclass
class DocHit:
    doc_id: int
    title_match: bool = False
    best: float = 0.0
    matches: int = 0
    snippets: list[dict] = field(default_factory=list)


def tokens_of(q: str) -> list[str]:
    return re.findall(r"\w+", q, flags=re.UNICODE)[:12]


def fts_query(tokens: list[str]) -> str:
    parts = [f'"{t}"' for t in tokens]
    parts[-1] += "*"
    return " AND ".join(parts)


def _filters(category_id: int | None, ext: str | None) -> tuple[str, list]:
    sql, args = "", []
    if category_id:
        sql += " AND d.category_id = ?"
        args.append(category_id)
    if ext:
        sql += " AND d.ext = ?"
        args.append(ext.lower())
    return sql, args


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _title_matches(conn: sqlite3.Connection, tokens: list[str], category_id, ext) -> set[int]:
    if not tokens:
        return set()
    where, args = _filters(category_id, ext)
    clause = " AND ".join("(lower(d.title || ' ' || d.description || ' ' || d.tags || ' ' || d.filename) "
                          "LIKE ? ESCAPE '\\')" for _ in tokens)
    rows = conn.execute(f"SELECT d.id FROM documents d WHERE {clause}{where}",
                        [f"%{_like_escape(t.lower())}%" for t in tokens] + args).fetchall()
    return {r["id"] for r in rows}


def _exact_snippet(text: str, query: str, width: int = 90) -> str:
    idx = text.lower().find(query.lower())
    if idx < 0:
        return text[: 2 * width]
    start, end = max(0, idx - width), min(len(text), idx + len(query) + width)
    body = (text[start:idx] + MARK_OPEN + text[idx: idx + len(query)] + MARK_CLOSE + text[idx + len(query): end])
    return ("…" if start else "") + body.replace("\n", " ") + ("…" if end < len(text) else "")


def search_documents(conn: sqlite3.Connection, query: str, mode: str = "smart", category_id: int | None = None,
                     ext: str | None = None) -> list[DocHit]:
    """Return documents ranked by relevance. Filename/title matches rank first, then content matches."""
    query = query.strip()
    tokens = tokens_of(query)
    if not tokens:
        return []
    hits: dict[int, DocHit] = {}
    for doc_id in _title_matches(conn, [query] if mode == "exact" else tokens, category_id, ext):
        hits[doc_id] = DocHit(doc_id, title_match=True)
    where, args = _filters(category_id, ext)
    if mode == "exact":
        rows = conn.execute(
            "SELECT c.doc_id, c.page, c.label, c.text, 0.0 AS score FROM chunks c JOIN documents d ON d.id = c.doc_id "
            f"WHERE instr(lower(c.text), lower(?)) > 0{where} ORDER BY c.doc_id, c.ordinal LIMIT {MAX_HITS}",
            [query, *args]).fetchall()
    else:
        rows = conn.execute(
            f"SELECT c.doc_id, c.page, c.label, snippet(chunks_fts, 0, '{MARK_OPEN}', '{MARK_CLOSE}', '…', 28) AS text,"
            " bm25(chunks_fts) AS score FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            f"JOIN documents d ON d.id = c.doc_id WHERE chunks_fts MATCH ?{where} ORDER BY score LIMIT {MAX_HITS}",
            [fts_query(tokens), *args]).fetchall()
    for row in rows:
        hit = hits.setdefault(row["doc_id"], DocHit(row["doc_id"]))
        hit.matches += 1
        hit.best = min(hit.best, row["score"])
        if len(hit.snippets) < SNIPPETS_PER_DOC:
            text = _exact_snippet(row["text"], query) if mode == "exact" else row["text"]
            hit.snippets.append({"page": row["page"], "label": row["label"], "text": text.replace("\n", " ")})
    return sorted(hits.values(), key=lambda h: (not h.title_match, h.best, -h.matches))
