import json
import re
import sqlite3

from opsintel.db import transaction

CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
ACRONYM_BOUNDARY_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
IDENTIFIER_RE = re.compile(r"[\w.-]+", re.UNICODE)
SEARCH_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _expanded(value: str) -> str:
    words = []
    for token in IDENTIFIER_RE.findall(value):
        parts = re.split(r"[_\-.]+|" + CAMEL_BOUNDARY_RE.pattern + r"|" + ACRONYM_BOUNDARY_RE.pattern, token)
        words.extend(part for part in (token, *parts) if part)
    return " ".join(words)


def build_search_metadata(text: str, sheet: str | None = None, section_path: str | None = None,
                          key_path: str | None = None, extra_json: str | None = None) -> str:
    values = [text, sheet, section_path, key_path]
    if extra_json:
        try:
            extra = json.loads(extra_json)
        except (TypeError, json.JSONDecodeError):
            extra = {}
        if isinstance(extra, dict):
            headers = extra.get("headers")
            if isinstance(headers, dict):
                values.extend(str(value) for value in headers.values())
                values.extend(str(value) for value in headers.keys())
            elif isinstance(headers, list):
                values.extend(str(value) for value in headers)
            values.extend(str(value) for value in (extra.get("title"), extra.get("author")) if value)
    return " ".join(_expanded(str(value)) for value in values if value)


def metadata_query_terms(query: str) -> list[str]:
    expanded = _expanded(query).lower()
    return list(dict.fromkeys(word for word in SEARCH_WORD_RE.findall(expanded) if len(word) >= 2))


def backfill_search_metadata(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT c.id, c.text, c.sheet, c.section_path, c.key_path, c.extra_json "
        "FROM chunks c "
        "WHERE c.search_metadata = ''"
    ).fetchall()
    if not rows:
        return 0
    conn.execute("INSERT INTO chunks_meta_fts(chunks_meta_fts) VALUES ('rebuild')")
    with transaction(conn):
        conn.executemany(
            "UPDATE chunks SET search_metadata = ? WHERE id = ?",
            [(build_search_metadata(row["text"], row["sheet"], row["section_path"], row["key_path"],
                                    row["extra_json"]),
              row["id"]) for row in rows],
        )
    return len(rows)
