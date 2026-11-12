import asyncio
import json
import logging
import os
import signal
import socket
import threading
import time
from collections.abc import Callable

import psutil

from opsintel import jobs
from opsintel.config import Settings
from opsintel.db import connect, migrate
from opsintel.embeddings import index_embeddings
from opsintel.hybrid import semantic_available
from opsintel.indexing import LocalIndexer
from opsintel.sync import GiteaSyncer
from opsintel.tasks import PRIORITY_POLL, SYNC_QUEUE, enqueue_repo_sync, get_setting, indexing_paused, set_setting

log = logging.getLogger(__name__)

HEARTBEAT_EVERY_S = 10.0
PURGE_DONE_AFTER_S = 7 * 24 * 3600


class Interrupted(Exception):
    """Raised inside a job when the worker is asked to stop."""


class Worker:
    def __init__(self, settings: Settings, worker_id: str | None = None):
        self.settings = settings
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.conn = connect(settings)
        migrate(self.conn)
        self._stop = threading.Event()
        self._last_heartbeat = 0.0
        self._resources_were_ok = True
        self.current_job: jobs.Job | None = None

    def request_stop(self, *_args) -> None:
        log.info("stop requested; finishing current file")
        self._stop.set()

    def install_signal_handlers(self) -> None:
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):  # SIGBREAK = Ctrl+Break on Windows
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), self.request_stop)

    def run_forever(self) -> None:
        log.info("worker %s started", self.worker_id)
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                log.exception("worker loop error")
                worked = False
            if not worked:
                self._stop.wait(self.settings.worker_idle_sleep_s)
        log.info("worker %s stopped", self.worker_id)

    def run_once(self) -> bool:
        s = self.settings
        set_setting(self.conn, "worker_seen_at", f"{time.time():.0f}")
        jobs.recover_expired(self.conn, backoff_base_s=s.job_backoff_base_s, backoff_max_s=s.job_backoff_max_s)
        self._maybe_schedule_poll()
        if indexing_paused(self.conn) or not self._resources_ok():
            return False
        job = jobs.lease(self.conn, [SYNC_QUEUE], self.worker_id, s.worker_lease_s)
        if job is None:
            return False
        self._execute(job)
        return True

    def _execute(self, job: jobs.Job) -> None:
        s = self.settings
        self.current_job = job
        self._last_heartbeat = time.monotonic()
        log.info("job %s %s attempt %s/%s", job.id, json.dumps(job.payload), job.attempts, job.max_attempts)
        try:
            stats = self._handle(job)
        except Interrupted:
            jobs.release(self.conn, job.id)
            log.info("job %s released for later", job.id)
        except Exception as exc:
            status = jobs.fail(self.conn, job.id, f"{type(exc).__name__}: {exc}",
                               backoff_base_s=s.job_backoff_base_s, backoff_max_s=s.job_backoff_max_s)
            log.warning("job %s failed (%s): %s", job.id, status, exc)
        else:
            jobs.complete(self.conn, job.id, stats)
            log.info("job %s done: %s", job.id, stats)
        finally:
            self.current_job = None

    def _handle(self, job: jobs.Job) -> dict:
        p = job.payload
        progress = self._progress_callback(job.id)
        if p.get("type") == "gitea":
            stats = GiteaSyncer(self.conn, self.settings, self._checkpoint, progress).sync(
                p["repo_id"], p["branch"]).__dict__
        elif p.get("type") == "local":
            stats = LocalIndexer(self.conn, self.settings, self._checkpoint, progress).index_repo(
                p["repo_id"]).__dict__
        else:
            raise ValueError(f"unknown job type {p.get('type')!r}")
        self._embed_new_chunks(p["repo_id"], stats)
        return stats

    def _progress_callback(self, job_id: int) -> Callable[[dict], None]:
        last_update = 0.0

        def update(progress: dict) -> None:
            nonlocal last_update
            now = time.monotonic()
            if progress.get("phase") == "done" or now - last_update >= 0.5:
                jobs.set_progress(self.conn, job_id, progress)
                last_update = now

        return update

    def _embed_new_chunks(self, repo_id: int, stats: dict) -> None:
        if not semantic_available(self.settings) or not stats.get("chunks_written"):
            return
        try:
            result = asyncio.run(index_embeddings(
                self.conn, self.settings.ollama_base_url, self.settings.ollama_embed_model, [repo_id],
                timeout_s=self.settings.ai_timeout_s,
            ))
            stats["embedded"] = result["embedded"]
        except Exception as exc:  # embeddings are optional; a failure must not fail indexing
            log.warning("embedding new chunks for repo %s failed: %s", repo_id, exc)

    def _checkpoint(self) -> None:
        """Called between files: honours stop/pause requests, memory pressure and keeps the lease alive."""
        if self._stop.is_set():
            raise Interrupted
        self._heartbeat()
        while indexing_paused(self.conn) or not self._resources_ok():
            if self._stop.wait(self.settings.worker_resource_wait_s):
                raise Interrupted
            self._heartbeat(force=True)

    def _heartbeat(self, force: bool = False) -> None:
        if self.current_job is None:
            return
        if force or time.monotonic() - self._last_heartbeat >= HEARTBEAT_EVERY_S:
            if not jobs.heartbeat(self.conn, self.current_job.id, self.worker_id, self.settings.worker_lease_s):
                raise Interrupted  # lease lost to another worker
            self._last_heartbeat = time.monotonic()

    def _resources_ok(self) -> bool:
        available_mb = psutil.virtual_memory().available / 1024**2
        ok = available_mb >= self.settings.worker_min_free_ram_mb
        if ok != self._resources_were_ok:
            if ok:
                log.info("resuming: %.0f MB available", available_mb)
            else:
                log.warning("throttling: %.0f MB available < WORKER_MIN_FREE_RAM_MB=%s", available_mb,
                            self.settings.worker_min_free_ram_mb)
            self._resources_were_ok = ok
        return ok

    def _maybe_schedule_poll(self) -> None:
        s = self.settings
        if not s.gitea_url or s.gitea_poll_interval_s <= 0:
            return
        now = time.time()
        last = float(get_setting(self.conn, "last_poll_at", "0") or 0)
        if now - last < s.gitea_poll_interval_s:
            return
        set_setting(self.conn, "last_poll_at", str(now))
        for repo in self.conn.execute("SELECT * FROM repositories WHERE kind = 'gitea' AND enabled = 1").fetchall():
            try:
                enqueue_repo_sync(self.conn, s, repo, priority=PRIORITY_POLL)
            except jobs.QueueFull as exc:
                log.warning("poll skipped for %s: %s", repo["name"], exc)
        jobs.purge_finished(self.conn, PURGE_DONE_AFTER_S)

    def close(self) -> None:
        self.conn.close()
