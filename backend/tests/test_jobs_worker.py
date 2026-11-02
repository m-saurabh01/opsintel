import time

import pytest

from opsintel import jobs
from opsintel.indexing import register_local_repo
from opsintel.tasks import enqueue_repo_sync, set_setting
from opsintel.worker import Interrupted, Worker
from tests.conftest import write

BACKOFF = {"backoff_base_s": 30, "backoff_max_s": 3600}


def test_enqueue_dedupes_queued_jobs_and_raises_priority(conn):
    a, created_a = jobs.enqueue(conn, "sync", "k1", {"x": 1}, priority=200)
    b, created_b = jobs.enqueue(conn, "sync", "k1", {"x": 1}, priority=50)
    assert a == b and created_a and not created_b
    assert conn.execute("SELECT priority FROM jobs WHERE id = ?", (a,)).fetchone()[0] == 50


def test_new_request_cancels_backoff_of_queued_retry(conn):
    job_id, _ = jobs.enqueue(conn, "sync", "k", {}, priority=200)
    jobs.lease(conn, ["sync"], "w", 60)
    jobs.fail(conn, job_id, "gitea down", **BACKOFF)
    assert jobs.lease(conn, ["sync"], "w", 60) is None  # backing off

    again, created = jobs.enqueue(conn, "sync", "k", {}, priority=50)  # e.g. webhook after Gitea is back
    assert (again, created) == (job_id, False)
    job = jobs.lease(conn, ["sync"], "w", 60)
    assert job is not None and job.id == job_id and job.attempts == 1


def test_new_job_allowed_while_same_key_running(conn):
    a, _ = jobs.enqueue(conn, "sync", "k1", {})
    assert jobs.lease(conn, ["sync"], "w1", 60).id == a
    b, created = jobs.enqueue(conn, "sync", "k1", {})
    assert created and b != a
    assert jobs.lease(conn, ["sync"], "w2", 60) is None  # same key must not run concurrently
    jobs.complete(conn, a)
    assert jobs.lease(conn, ["sync"], "w2", 60).id == b


def test_queue_capacity(conn):
    jobs.enqueue(conn, "sync", "k1", {}, max_queued=1)
    with pytest.raises(jobs.QueueFull):
        jobs.enqueue(conn, "sync", "k2", {}, max_queued=1)


def test_failure_backoff_then_dead_then_retry(conn):
    job_id, _ = jobs.enqueue(conn, "sync", "k", {}, max_attempts=2)
    jobs.lease(conn, ["sync"], "w", 60)
    assert jobs.fail(conn, job_id, "boom", **BACKOFF) == "queued"
    row = conn.execute("SELECT run_after, attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["attempts"] == 1 and row["run_after"] > time.time() + 20
    assert jobs.lease(conn, ["sync"], "w", 60) is None  # backing off

    conn.execute("UPDATE jobs SET run_after = 0 WHERE id = ?", (job_id,))
    jobs.lease(conn, ["sync"], "w", 60)
    assert jobs.fail(conn, job_id, "boom again", **BACKOFF) == "dead"
    assert jobs.retry(conn) == 1
    assert jobs.lease(conn, ["sync"], "w", 60).attempts == 1


def test_expired_lease_is_recovered(conn):
    job_id, _ = jobs.enqueue(conn, "sync", "k", {})
    jobs.lease(conn, ["sync"], "dead-worker", lease_s=-1)
    assert jobs.recover_expired(conn, **BACKOFF) == 1
    row = conn.execute("SELECT status, attempts, last_error FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == "queued" and row["attempts"] == 1 and "lease expired" in row["last_error"]


def test_worker_runs_local_job_and_persists_result(settings, conn, repo_dir):
    write(repo_dir / "x.py", "worker_token = 1\n")
    repo_id = register_local_repo(conn, "demo", repo_dir)
    [(job_id, _)] = enqueue_repo_sync(conn, settings, conn.execute(
        "SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone())
    settings.worker_min_free_ram_mb = 0
    w = Worker(settings, "test-worker")
    try:
        assert w.run_once() is True
        assert w.run_once() is False
    finally:
        w.close()
    row = conn.execute("SELECT status, result FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == "done" and '"indexed": 1' in row["result"]


def test_worker_pause_and_stop_release_job(settings, conn, repo_dir):
    for i in range(3):
        write(repo_dir / f"{i}.txt", "x\n")
    repo_id = register_local_repo(conn, "demo", repo_dir)
    repo = conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
    settings.worker_min_free_ram_mb = 0
    w = Worker(settings, "w")
    try:
        set_setting(conn, "indexing_paused", "1")
        enqueue_repo_sync(conn, settings, repo)
        assert w.run_once() is False  # paused: nothing leased
        set_setting(conn, "indexing_paused", "0")

        w.request_stop()
        assert w.run_once() is True
        row = conn.execute("SELECT status, attempts FROM jobs").fetchone()
        assert (row["status"], row["attempts"]) == ("queued", 0)
    finally:
        w.close()


def test_worker_failed_job_is_retried_later(settings, conn):
    settings.worker_min_free_ram_mb = 0
    job_id, _ = jobs.enqueue(conn, "sync", "gitea:999:main", {"type": "gitea", "repo_id": 999, "branch": "main"})
    w = Worker(settings, "w")
    try:
        assert w.run_once() is True
    finally:
        w.close()
    row = conn.execute("SELECT status, last_error FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == "queued" and "RepoNotFound" in row["last_error"]


def test_interrupted_is_not_an_exception_subclass_of_runtime():
    assert not issubclass(Interrupted, RuntimeError)
