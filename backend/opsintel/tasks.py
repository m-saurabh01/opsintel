import sqlite3

from opsintel.config import Settings
from opsintel.jobs import enqueue

SYNC_QUEUE = "sync"
PRIORITY_MANUAL = 10
PRIORITY_WEBHOOK = 50
PRIORITY_POLL = 200


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, value))


def indexing_paused(conn: sqlite3.Connection) -> bool:
    return get_setting(conn, "indexing_paused", "0") == "1"


def enqueue_repo_sync(conn: sqlite3.Connection, settings: Settings, repo: sqlite3.Row, *, branch: str | None = None,
                      priority: int = PRIORITY_MANUAL) -> list[tuple[int, bool]]:
    """Queue synchronisation for one repository (all tracked branches unless `branch` is given)."""
    common = {"priority": priority, "max_attempts": settings.job_max_attempts,
              "max_queued": settings.queue_max_queued}
    if repo["kind"] == "local":
        return [enqueue(conn, SYNC_QUEUE, f"local:{repo['id']}", {"type": "local", "repo_id": repo["id"]}, **common)]
    branches = [branch] if branch else [r[0] for r in conn.execute(
        "SELECT branch FROM repo_branches WHERE repo_id = ? ORDER BY branch", (repo["id"],))]
    return [
        enqueue(conn, SYNC_QUEUE, f"gitea:{repo['id']}:{b}", {"type": "gitea", "repo_id": repo["id"], "branch": b},
                **common)
        for b in branches
    ]
