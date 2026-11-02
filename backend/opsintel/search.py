import re
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from opsintel.locations import label, locate

Mode = Literal["fulltext", "phrase", "exact"]
MAX_COUNT = 10_000
PREVIEW_CONTEXT = 2
MAX_PREVIEW_LINE_CHARS = 400
MAX_MATCH_LINES = 50

_TOKEN_RE = re.compile(r"\w+\*?", re.UNICODE)


class InvalidQuery(ValueError):
    pass


@dataclass
class SearchRequest:
    q: str
    mode: Mode = "fulltext"
    repo_ids: list[int] | None = None
    branch: str | None = None
    file_types: list[str] | None = None
    languages: list[str] | None = None
    path_prefix: str | None = None
    case_sensitive: bool = False
    page: int = 1
    page_size: int = 20


@dataclass
class Highlighted:
    line: int | None
    index: int  # line position inside the chunk
    label: str
    text: str
    highlights: list[tuple[int, int]] = field(default_factory=list)


def _quote(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def build_match(req: SearchRequest) -> tuple[str, str, re.Pattern]:
    """Return (fts_table, MATCH expression, highlight regex)."""
    q = req.q
    if req.mode == "exact":
        if len(q) < 3:
            raise InvalidQuery("exact search needs at least 3 characters")
        flags = 0 if req.case_sensitive else re.IGNORECASE
        return "chunks_tri", _quote(q), re.compile(re.escape(q), flags)

    tokens = _TOKEN_RE.findall(q)
    if not tokens:
        raise InvalidQuery("query has no searchable terms")
    if req.mode == "phrase":
        words = [t.rstrip("*") for t in tokens]
        pattern = r"(?<!\w)" + r"\W+".join(re.escape(w) for w in words) + r"(?!\w)"
        return "chunks_fts", _quote(" ".join(words)), re.compile(pattern, re.IGNORECASE)

    parts, alts = [], []
    for t in tokens:
        if t.endswith("*"):
            word = t[:-1]
            parts.append(_quote(word) + "*")
            alts.append(r"(?<!\w)" + re.escape(word) + r"\w*")
        else:
            parts.append(_quote(t))
            alts.append(r"(?<!\w)" + re.escape(t) + r"(?!\w)")
    return "chunks_fts", " ".join(parts), re.compile("|".join(alts), re.IGNORECASE)


def _filters(req: SearchRequest) -> tuple[str, list]:
    clauses, params = [], []
    if req.repo_ids:
        clauses.append(f"f.repo_id IN ({','.join('?' * len(req.repo_ids))})")
        params += req.repo_ids
    if req.branch is not None:
        clauses.append("f.branch = ?")
        params.append(req.branch)
    if req.file_types:
        clauses.append(f"f.file_type IN ({','.join('?' * len(req.file_types))})")
        params += req.file_types
    if req.languages:
        clauses.append(f"f.language IN ({','.join('?' * len(req.languages))})")
        params += req.languages
    if req.path_prefix:
        escaped = req.path_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("f.path LIKE ? ESCAPE '\\'")
        params.append(escaped + "%")
    if req.mode == "exact" and req.case_sensitive:
        clauses.append("instr(c.text, ?) > 0")
        params.append(req.q)
    return "".join(f" AND {c}" for c in clauses), params


def search(conn: sqlite3.Connection, req: SearchRequest) -> dict:
    table, match, pattern = build_match(req)
    where, params = _filters(req)
    base = (
        f"FROM {table} JOIN chunks c ON c.id = {table}.rowid "
        "JOIN files f ON f.id = c.file_id JOIN repositories r ON r.id = f.repo_id "
        f"WHERE {table} MATCH ? AND r.enabled = 1{where}"
    )
    args = [match, *params]
    total = conn.execute(f"SELECT count(*) FROM (SELECT 1 {base} LIMIT {MAX_COUNT + 1})", args).fetchone()[0]  # noqa: S608
    offset = (req.page - 1) * req.page_size
    rows = conn.execute(
        "SELECT c.id AS chunk_id, c.file_id, c.text, c.coord_kind, c.start_line, c.end_line, c.page, c.sheet, "
        "c.row_num, c.section_path, c.extra_json, "
        "f.path, f.file_type, f.language, f.branch, f.commit_sha, f.line_count, f.indexed_at, "
        f"r.id AS repo_id, r.name AS repo_name, bm25({table}) AS score {base} "  # noqa: S608
        "ORDER BY score LIMIT ? OFFSET ?",
        [*args, req.page_size, offset],
    ).fetchall()

    return {
        "query": req.q,
        "mode": req.mode,
        "page": req.page,
        "page_size": req.page_size,
        "total": min(total, MAX_COUNT),
        "total_is_lower_bound": total > MAX_COUNT,
        "results": [_result(row, pattern) for row in rows],
    }


def _result(row: sqlite3.Row, pattern: re.Pattern) -> dict:
    lines = row["text"].split("\n")
    matches = [(i, m.start()) for i, line in enumerate(lines) if (m := pattern.search(line))]
    anchor, match_start = matches[0] if matches else (0, None)
    lo, hi = max(0, anchor - PREVIEW_CONTEXT), min(len(lines), anchor + PREVIEW_CONTEXT + 1)
    preview = [_highlight(row, i, lines[i], pattern) for i in range(lo, hi)]
    is_line = row["coord_kind"] == "line"
    first = row["start_line"] or 1
    return {
        "chunk_id": row["chunk_id"],
        "file_id": row["file_id"],
        "repo": {"id": row["repo_id"], "name": row["repo_name"]},
        "branch": row["branch"],
        "commit_sha": row["commit_sha"],
        "path": row["path"],
        "file_type": row["file_type"],
        "language": row["language"],
        "indexed_at": row["indexed_at"],
        "location": locate(row, anchor, lines[anchor], match_start),
        "match_count": len(matches),
        "match_lines": [first + i for i, _ in matches[:MAX_MATCH_LINES]] if is_line else [],
        "preview": [p.__dict__ for p in preview],
        "score": round(-row["score"], 4),
    }


def _highlight(chunk: sqlite3.Row, idx: int, text: str, pattern: re.Pattern) -> Highlighted:
    spans = [(m.start(), m.end()) for m in pattern.finditer(text) if m.end() > m.start()]
    gutter = label(chunk, idx, text)
    line_no = (chunk["start_line"] or 1) + idx if chunk["coord_kind"] == "line" else None
    if len(text) > MAX_PREVIEW_LINE_CHARS:
        start = max(0, (spans[0][0] if spans else 0) - MAX_PREVIEW_LINE_CHARS // 4)
        end = start + MAX_PREVIEW_LINE_CHARS
        text = text[start:end]
        spans = [(s - start, min(e, end) - start) for s, e in spans if s >= start and s < end]
    return Highlighted(line=line_no, index=idx, label=gutter, text=text, highlights=spans)
