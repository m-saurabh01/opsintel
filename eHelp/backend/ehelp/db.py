import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    icon TEXT NOT NULL DEFAULT 'folder',
    banner TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    ext TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    revision TEXT NOT NULL DEFAULT '',
    page_count INTEGER,
    views INTEGER NOT NULL DEFAULT 0,
    index_status TEXT NOT NULL DEFAULT 'pending',
    index_error TEXT NOT NULL DEFAULT '',
    uploaded_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS documents_category ON documents(category_id);
CREATE INDEX IF NOT EXISTS documents_updated ON documents(updated_at);
CREATE TABLE IF NOT EXISTS document_relations (
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    related_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (doc_id, related_id)
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    page INTEGER,
    label TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id, ordinal);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_usage (day TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0);
"""

DEFAULT_CATEGORIES = [
    ("aviation", "Aviation", "Flight operations, aircraft and airfield documents.", "plane"),
    ("engineering", "Engineering", "Designs, technical specifications and engineering procedures.", "settings"),
    ("repairs", "Repairs", "Repair schemes, damage assessment and structural repair documents.", "wrench"),
    ("maintenance", "Maintenance", "Maintenance procedures, schedules and servicing instructions.", "hammer"),
    ("safety", "Safety & Quality", "Flight safety, circulars and quality assurance.", "shield-check"),
    ("training", "Training & Manuals", "Training material, handbooks and manuals.", "book-open"),
]

DEFAULT_SETTINGS = {
    "app_name": "eHelp",
    "subtitle": "Document Intelligence Platform",
    "hero_eyebrow": "WELCOME TO EHELP",
    "hero_title": "Every Document.",
    "hero_highlight": "One Destination.",
    "hero_text": "Search, discover and access all documents across categories in a single, secure portal.",
    "search_placeholder": "Search across all documents, categories and keywords...",
    "logo": "/img/iaf_logo.png",
    "hero_image": "/img/hero.jpg",
    "theme": "iaf",
    "accent_color": "#0b78d1",
    "highlight_color": "#22d3ee",
    "sidebar_color": "#0b2447",
    "bg_color": "#eef3fa",
    "show_recent": "1",
    "show_popular": "1",
    "ai_enabled": "0",
    "ai_daily_limit": "200",
}


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    if conn.execute("SELECT count(*) FROM categories").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO categories(slug, name, description, icon, sort_order) VALUES (?, ?, ?, ?, ?)",
            [(s, n, d, i, idx) for idx, (s, n, d, i) in enumerate(DEFAULT_CATEGORIES)])


def get_settings(conn: sqlite3.Connection) -> dict:
    values = dict(DEFAULT_SETTINGS)
    values.update({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")
                   if r["key"] in DEFAULT_SETTINGS})
    return values


def tags_of(row: sqlite3.Row) -> list[str]:
    try:
        return list(json.loads(row["tags"]))
    except (ValueError, TypeError):
        return []
