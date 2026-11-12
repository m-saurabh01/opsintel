import json
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from opsintel.locations import label, locate
from opsintel.search import InvalidQuery

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "do", "does", "for", "from",
    "get", "how", "i", "in", "is", "it", "me", "of", "on", "or", "please", "show", "tell", "that",
    "the", "there", "this", "to", "was", "what", "when", "where", "which", "who", "with", "would",
    "you", "your", "file", "files", "find", "list", "give", "return", "containing", "contains", "has",
    "have", "include", "including", "about", "using", "used", "use", "did",
}
WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
ACRONYM_BOUNDARY_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
CELL_RE = re.compile(r"(?:^| \| )([A-Z]{1,3})(\d+): ")

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata_chunks (
    chunk_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    repo_id INTEGER NOT NULL,
    repo_name TEXT NOT NULL,
    path TEXT NOT NULL,
    branch TEXT NOT NULL,
    commit_sha TEXT,
    file_type TEXT NOT NULL,
    language TEXT,
    coord_kind TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    page INTEGER,
    sheet TEXT,
    row_num INTEGER,
    section_path TEXT,
    key_path TEXT,
    extra_json TEXT,
    source_text TEXT NOT NULL,
    search_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_metadata_repo_path ON metadata_chunks(repo_id, path);
CREATE VIRTUAL TABLE IF NOT EXISTS metadata_fts USING fts5(
    search_text, content='metadata_chunks', content_rowid='chunk_id',
    tokenize='unicode61 remove_diacritics 2'
);
"""

def normalize_text(value: str) -> str:
    value = CAMEL_BOUNDARY_RE.sub(" ", value)
    return " ".join(WORD_RE.findall(value)).lower()

def query_terms(query: str) -> list[str]:
    return [word for word in normalize_text(query).split() if len(word) > 1 and word not in STOP_WORDS]


def _flatten(value) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _flatten(child)
    elif isinstance(value, list | tuple):
        for child in value:
            yield from _flatten(child)
    elif value is not None:
        yield str(value)


def _row_metadata(row: sqlite3.Row) -> tuple[dict, str]:
    extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
    values = [
        row["repo_name"], row["path"], row["branch"], row["file_type"], row["language"],
        row["sheet"], row["section_path"], row["key_path"], row["source_text"], *_flatten(extra),
    ]
    search_text = normalize_text(" ".join(str(value) for value in values if value))
    return extra, search_text


class MetadataShadowIndex:
    """Experimental metadata-aware FTS in an isolated SQLite file, independent of the live search index."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def refresh(self, source: sqlite3.Connection, repo_id: int | None = None) -> dict:
        params: list[int] = []
        scope = ""
        if repo_id is not None:
            scope = " AND r.id = ?"
            params.append(repo_id)
        cursor = source.execute(
            "SELECT c.id AS chunk_id, c.file_id, c.text AS source_text, c.coord_kind, c.start_line, c.end_line, "
            "c.page, c.sheet, c.row_num, c.section_path, c.key_path, c.extra_json, f.path, f.branch, f.commit_sha, "
            "f.file_type, f.language, r.id AS repo_id, r.name AS repo_name "
            "FROM chunks c JOIN files f ON f.id = c.file_id JOIN repositories r ON r.id = f.repo_id "
            "WHERE f.status = 'indexed' AND r.enabled = 1" + scope + " ORDER BY r.id, f.path, c.ordinal",
            params,
        )
        now_count = 0
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            if repo_id is None:
                self.conn.execute("DELETE FROM metadata_chunks")
            else:
                self.conn.execute("DELETE FROM metadata_chunks WHERE repo_id = ?", (repo_id,))
            while rows := cursor.fetchmany(250):
                values = []
                for row in rows:
                    _, search_text = _row_metadata(row)
                    values.append((
                        row["chunk_id"], row["file_id"], row["repo_id"], row["repo_name"], row["path"],
                        row["branch"], row["commit_sha"], row["file_type"], row["language"], row["coord_kind"],
                        row["start_line"], row["end_line"], row["page"], row["sheet"], row["row_num"],
                        row["section_path"], row["key_path"], row["extra_json"], row["source_text"], search_text,
                    ))
                self.conn.executemany(
                    "INSERT INTO metadata_chunks(chunk_id,file_id,repo_id,repo_name,path,branch,commit_sha,file_type,"
                    "language,coord_kind,start_line,end_line,page,sheet,row_num,section_path,key_path,extra_json,"
                    "source_text,search_text) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    values,
                )
                now_count += len(values)
            self.conn.execute("INSERT INTO metadata_fts(metadata_fts) VALUES ('rebuild')")
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        return {"repo_id": repo_id, "chunks_refreshed": now_count, "index_path": str(self.path)}

    def search(
        self,
        query: str,
        *,
        mode: str = "fulltext",
        repo_id: int | None = None,
        repo_ids: list[int] | None = None,
        branch: str | None = None,
        file_types: list[str] | None = None,
        languages: list[str] | None = None,
        path_prefix: str | None = None,
        page: int = 1,
        page_size: int = 20,
        limit: int | None = None,
    ) -> dict:
        terms = query_terms(query)
        if not terms:
            raise InvalidQuery("query has no searchable terms")
        if mode not in {"fulltext", "phrase", "exact"}:
            raise InvalidQuery("mode must be fulltext, phrase or exact")
        if repo_id is not None:
            repo_ids = [repo_id]
        page = max(int(page), 1)
        page_size = min(max(int(limit if limit is not None else page_size), 1), 100)
        offset = (page - 1) * page_size
        path_like = None
        if path_prefix:
            path_like = path_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filter_params = (
            branch, branch,
            json.dumps(file_types or []), json.dumps(file_types or []),
            json.dumps(languages or []), json.dumps(languages or []),
            path_like, path_like,
            json.dumps(repo_ids or []), json.dumps(repo_ids or []),
        )
        filters = (
            " AND (? IS NULL OR c.branch = ?)"
            " AND (json_array_length(?) = 0 OR c.file_type IN (SELECT value FROM json_each(?)))"
            " AND (json_array_length(?) = 0 OR c.language IN (SELECT value FROM json_each(?)))"
            " AND (? IS NULL OR c.path LIKE ? ESCAPE '\\')"
            " AND (json_array_length(?) = 0 OR c.repo_id IN "
            "(SELECT CAST(value AS INTEGER) FROM json_each(?)))"
        )
        if mode == "exact":
            normalized = normalize_text(query)
            if len(normalized) < 3:
                raise InvalidQuery("exact search needs at least 3 normalized characters")
            count_query = "SELECT count(*) FROM metadata_chunks c WHERE instr(c.search_text, ?) > 0" + filters  # noqa: S608
            search_query = "SELECT c.*, 0.0 AS score FROM metadata_chunks c WHERE instr(c.search_text, ?) > 0" + \
                filters + " ORDER BY c.repo_name, c.path, c.chunk_id LIMIT ? OFFSET ?"  # noqa: S608
            count = self.conn.execute(count_query, (normalized, *filter_params)).fetchone()[0]
            rows = self.conn.execute(search_query, (normalized, *filter_params, page_size, offset)).fetchall()
        else:
            match = '"' + " ".join(terms).replace('"', '""') + '"' if mode == "phrase" else \
                " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
            count_query = (
                "SELECT count(*) FROM metadata_fts JOIN metadata_chunks c ON c.chunk_id = metadata_fts.rowid "  # noqa: S608
                "WHERE metadata_fts MATCH ?" + filters
            )  # noqa: S608
            search_query = (
                "SELECT c.*, bm25(metadata_fts) AS score FROM metadata_fts "  # noqa: S608
                "JOIN metadata_chunks c ON c.chunk_id = metadata_fts.rowid WHERE metadata_fts MATCH ?" + filters +
                " ORDER BY score, c.repo_name, c.path LIMIT ? OFFSET ?"
            )  # noqa: S608
            count = self.conn.execute(count_query, (match, *filter_params)).fetchone()[0]
            rows = self.conn.execute(search_query, (match, *filter_params, page_size, offset)).fetchall()
        return {
            "query": query, "mode": mode, "page": page, "page_size": page_size,
            "total": count, "total_is_lower_bound": False,
            "results": [self._result(row, terms) for row in rows],
        }

    @staticmethod
    def _result(row: sqlite3.Row, terms: list[str]) -> dict:
        lines = row["source_text"].split("\n")
        scores = [sum(term in normalize_text(line).split() for term in terms) for line in lines]
        anchor = max(range(len(lines)), key=lambda index: (scores[index], -index)) if lines else 0
        extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
        location = locate(row, anchor, lines[anchor]) if lines else {"kind": row["coord_kind"]}
        headers = extra.get("headers")
        if row["coord_kind"] == "cell" and isinstance(headers, dict):
            matching_column = next((column for column, header in headers.items()
                                    if set(terms) & set(query_terms(str(header)))), None)
            if matching_column:
                source_row = row["start_line"] or 1
                location.update({"cell": f"{matching_column}{source_row}", "row": source_row,
                                 "column": matching_column, "header": headers[matching_column]})
        elif row["coord_kind"] == "row" and isinstance(headers, list):
            matching_column = next(
                (index for index, header in enumerate(headers, 1)
                 if set(terms) & set(query_terms(str(header)))), None,
            )
            if matching_column:
                location.update({"row": row["row_num"], "column_index": matching_column,
                                 "column": headers[matching_column - 1]})
        matched = [index for index, score in enumerate(scores) if score]
        start = max(0, anchor - 1)
        end = min(len(lines), anchor + 2)
        preview = []
        for index in range(start, end):
            line = lines[index]
            spans = []
            for term in terms:
                pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
                spans.extend((match.start(), match.end()) for match in pattern.finditer(line))
            preview.append({"line": row["start_line"] + index if row["coord_kind"] == "line" else None,
                            "index": index, "label": label(row, index, line), "text": line,
                            "highlights": sorted(set(spans))})
        return {
            "chunk_id": row["chunk_id"], "file_id": row["file_id"],
            "repo": {"id": row["repo_id"], "name": row["repo_name"]},
            "path": row["path"], "file_type": row["file_type"],
            "language": row["language"], "branch": row["branch"], "commit_sha": row["commit_sha"],
            "location": location, "match_count": len(matched),
            "match_lines": [(row["start_line"] or 1) + index for index in matched[:50]]
            if row["coord_kind"] == "line" else [],
            "preview": preview, "text": row["source_text"], "score": -float(row["score"]),
        }
