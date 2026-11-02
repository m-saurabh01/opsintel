import json
import sqlite3
import time
from dataclasses import dataclass

from opsintel.db import transaction


class QueueFull(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Job:
    id: int
    queue: str
    payload: dict
    attempts: int
    max_attempts: int


def enqueue(conn: sqlite3.Connection, queue: str, dedupe_key: str, payload: dict, *, priority: int = 100,
            max_attempts: int = 5, max_queued: int = 1000, delay_s: float = 0.0) -> tuple[int, bool]:
    """Queue a job. Returns (job_id, created); an identical queued job is reused instead of duplicated."""
    now = time.time()
    with transaction(conn):
        existing = conn.execute("SELECT id, priority FROM jobs WHERE dedupe_key = ? AND status = 'queued'",
                                (dedupe_key,)).fetchone()
        if existing:
            # A new request is a fresh signal: run it promptly with a full retry budget, not the old backoff.
            conn.execute(
                "UPDATE jobs SET priority = min(priority, ?), run_after = min(run_after, ?), attempts = 0 "
                "WHERE id = ?",
                (priority, now + delay_s, existing["id"]),
            )
            return existing["id"], False
        depth = conn.execute("SELECT count(*) FROM jobs WHERE queue = ? AND status = 'queued'", (queue,)).fetchone()[0]
        if depth >= max_queued:
            raise QueueFull(f"queue '{queue}' has {depth} queued jobs (limit {max_queued})")
        job_id = conn.execute(
            "INSERT INTO jobs(queue, dedupe_key, payload, status, priority, max_attempts, run_after, created_at) "
            "VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)",
            (queue, dedupe_key, json.dumps(payload), priority, max_attempts, now + delay_s, now),
        ).lastrowid
    return job_id, True


def lease(conn: sqlite3.Connection, queues: list[str], worker_id: str, lease_s: float) -> Job | None:
    now = time.time()
    marks = ",".join("?" * len(queues))
    with transaction(conn):
        # Jobs whose key is already running wait, so work on the same repo/branch is never concurrent.
        row = conn.execute(
            f"SELECT * FROM jobs WHERE status = 'queued' AND queue IN ({marks}) AND run_after <= ? "  # noqa: S608
            "AND dedupe_key NOT IN (SELECT dedupe_key FROM jobs WHERE status = 'running') "
            "ORDER BY priority, run_after, id LIMIT 1",
            (*queues, now),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET status = 'running', worker_id = ?, leased_until = ?, started_at = ?, "
            "attempts = attempts + 1 WHERE id = ?",
            (worker_id, now + lease_s, now, row["id"]),
        )
    return Job(row["id"], row["queue"], json.loads(row["payload"]), row["attempts"] + 1, row["max_attempts"])


def heartbeat(conn: sqlite3.Connection, job_id: int, worker_id: str, lease_s: float) -> bool:
    cur = conn.execute(
        "UPDATE jobs SET leased_until = ? WHERE id = ? AND worker_id = ? AND status = 'running'",
        (time.time() + lease_s, job_id, worker_id),
    )
    return cur.rowcount == 1


def complete(conn: sqlite3.Connection, job_id: int, result: dict | None = None) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'done', finished_at = ?, leased_until = NULL, last_error = NULL, result = ? "
        "WHERE id = ?",
        (time.time(), json.dumps(result) if result is not None else None, job_id),
    )


def get(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def set_progress(conn: sqlite3.Connection, job_id: int, progress: dict) -> None:
    conn.execute("UPDATE jobs SET progress = ? WHERE id = ? AND status = 'running'",
                 (json.dumps(progress, ensure_ascii=False), job_id))


def is_cancel_requested(conn: sqlite3.Connection, job_id: int) -> bool:
    row = conn.execute("SELECT cancel_requested FROM jobs WHERE id = ? AND status = 'running'", (job_id,)).fetchone()
    return row is None or bool(row[0])


def cancel(conn: sqlite3.Connection, job_id: int) -> str:
    with transaction(conn):
        row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return "missing"
        if row["status"] == "queued":
            conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ?, last_error = 'cancelled by user' "
                         "WHERE id = ?", (time.time(), job_id))
            return "cancelled"
        if row["status"] == "running":
            conn.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))
            return "cancelling"
        return row["status"]


def mark_cancelled(conn: sqlite3.Connection, job_id: int, reason: str = "cancelled by user") -> None:
    conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ?, leased_until = NULL, last_error = ? "
                 "WHERE id = ?", (time.time(), reason[:500], job_id))


def fail(conn: sqlite3.Connection, job_id: int, error: str, *, backoff_base_s: float, backoff_max_s: float) -> str:
    """Record a failure; retry with exponential backoff or move to the dead-letter state. Returns new status."""
    with transaction(conn):
        row = conn.execute("SELECT attempts, max_attempts, dedupe_key FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return "missing"
        now = time.time()
        if row["attempts"] >= row["max_attempts"]:
            conn.execute("UPDATE jobs SET status = 'dead', finished_at = ?, leased_until = NULL, last_error = ? "
                         "WHERE id = ?", (now, error[:2000], job_id))
            return "dead"
        newer = conn.execute("SELECT id FROM jobs WHERE dedupe_key = ? AND status = 'queued'",
                             (row["dedupe_key"],)).fetchone()
        if newer:
            # A fresh request for the same work is already queued; it supersedes this retry.
            conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ?, leased_until = NULL, "
                         "last_error = ? WHERE id = ?", (now, error[:2000], job_id))
            return "cancelled"
        delay = min(backoff_max_s, backoff_base_s * 2 ** (row["attempts"] - 1))
        conn.execute("UPDATE jobs SET status = 'queued', run_after = ?, leased_until = NULL, worker_id = NULL, "
                     "last_error = ? WHERE id = ?", (now + delay, error[:2000], job_id))
        return "queued"


def release(conn: sqlite3.Connection, job_id: int) -> None:
    """Return a job to the queue without counting the attempt (graceful shutdown)."""
    with transaction(conn):
        row = conn.execute("SELECT dedupe_key FROM jobs WHERE id = ?", (job_id,)).fetchone()
        newer = row and conn.execute("SELECT 1 FROM jobs WHERE dedupe_key = ? AND status = 'queued'",
                                     (row["dedupe_key"],)).fetchone()
        if newer:
            conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ?, leased_until = NULL WHERE id = ?",
                         (time.time(), job_id))
        else:
            conn.execute("UPDATE jobs SET status = 'queued', attempts = max(attempts - 1, 0), leased_until = NULL, "
                         "worker_id = NULL WHERE id = ?", (job_id,))


def recover_expired(conn: sqlite3.Connection, *, backoff_base_s: float, backoff_max_s: float,
                    queue: str | None = None) -> int:
    """Requeue jobs whose worker died (lease expired). Counts as a failed attempt."""
    if queue is None:
        expired = [r[0] for r in conn.execute(
            "SELECT id FROM jobs WHERE status = 'running' AND leased_until < ?", (time.time(),))]
    else:
        expired = [r[0] for r in conn.execute(
            "SELECT id FROM jobs WHERE status = 'running' AND leased_until < ? AND queue = ?",
            (time.time(), queue))]
    for job_id in expired:
        fail(conn, job_id, "lease expired (worker stopped or crashed)",
             backoff_base_s=backoff_base_s, backoff_max_s=backoff_max_s)
    return len(expired)


def retry(conn: sqlite3.Connection, job_id: int | None = None) -> int:
    """Requeue dead jobs (all, or one) with a fresh attempt budget."""
    where, args = ("AND id = ?", (job_id,)) if job_id is not None else ("", ())
    dead = conn.execute(f"SELECT id, dedupe_key FROM jobs WHERE status = 'dead' {where} ORDER BY id DESC",  # noqa: S608
                        args).fetchall()
    count = 0
    for row in dead:
        with transaction(conn):
            if conn.execute("SELECT 1 FROM jobs WHERE dedupe_key = ? AND status = 'queued'",
                            (row["dedupe_key"],)).fetchone():
                continue
            conn.execute("UPDATE jobs SET status = 'queued', attempts = 0, run_after = ?, last_error = NULL, "
                         "finished_at = NULL, cancel_requested = 0, progress = NULL WHERE id = ?",
                         (time.time(), row["id"]))
            count += 1
    return count


def stats(conn: sqlite3.Connection) -> dict:
    now = time.time()
    by_status = {}
    for r in conn.execute("SELECT queue, status, count(*) n FROM jobs GROUP BY queue, status"):
        by_status.setdefault(r["queue"], {})[r["status"]] = r["n"]
    oldest = {r["queue"]: round(now - r["t"], 1) for r in conn.execute(
        "SELECT queue, min(created_at) t FROM jobs WHERE status = 'queued' GROUP BY queue")}
    durations = {r["queue"]: round(r["d"], 2) for r in conn.execute(
        "SELECT queue, avg(finished_at - started_at) d FROM (SELECT * FROM jobs WHERE status = 'done' "
        "ORDER BY finished_at DESC LIMIT 200) GROUP BY queue")}
    return {"queues": by_status, "oldest_queued_age_s": oldest, "avg_duration_s": durations}


def recent(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, queue, dedupe_key, status, priority, attempts, max_attempts, last_error, created_at, "
        "started_at, finished_at FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def purge_finished(conn: sqlite3.Connection, older_than_s: float) -> int:
    cur = conn.execute("DELETE FROM jobs WHERE status IN ('done', 'cancelled') AND finished_at < ?",
                       (time.time() - older_than_s,))
    return cur.rowcount
