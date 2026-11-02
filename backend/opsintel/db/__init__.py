import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from opsintel.config import Settings
from opsintel.db.migrations import MIGRATIONS


def connect(settings: Settings) -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return open_db(settings.db_path, settings.sqlite_cache_mb, settings.sqlite_busy_timeout_ms)


def open_db(path: Path | str, cache_mb: int = 64, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    # Autocommit mode; transactions are explicit via `transaction()`.
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    conn.execute(f"PRAGMA cache_size=-{int(cache_mb) * 1024}")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection) -> list[int]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)")
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    newly = []
    for version, sql in MIGRATIONS:
        if version in applied:
            continue
        with transaction(conn):
            for stmt in _split_sql(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))", (version,)
            )
        newly.append(version)
    return newly


def _split_sql(sql: str) -> list[str]:
    # Triggers contain ';' inside BEGIN...END, so split only on complete statements.
    stmts, buf = [], ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                stmts.append(buf.strip())
            buf = ""
    if buf.strip():
        stmts.append(buf.strip())
    return stmts
