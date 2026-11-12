import json
import logging
import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import PurePosixPath

from opsintel.config import Settings
from opsintel.db import transaction
from opsintel.discovery import FileKind, classify, is_excluded
from opsintel.gitea import GiteaRepo
from opsintel.gitops import GitError, Mirror
from opsintel.indexing import FileWriter, IndexStats, RepoNotFound

log = logging.getLogger(__name__)

SYMLINK_MODE = "120000"


def register_gitea_repo(conn: sqlite3.Connection, repo: GiteaRepo) -> int:
    with transaction(conn):
        row = conn.execute("SELECT id FROM repositories WHERE gitea_id = ?", (repo.id,)).fetchone()
        if row is None:
            clash = conn.execute("SELECT id FROM repositories WHERE name = ?", (repo.full_name,)).fetchone()
            if clash:
                raise ValueError(f"a repository named '{repo.full_name}' already exists")
            repo_id = conn.execute(
                "INSERT INTO repositories(name, kind, location, default_branch, gitea_id, is_private) "
                "VALUES (?, 'gitea', ?, ?, ?, ?)",
                (repo.full_name, repo.clone_url, repo.default_branch, repo.id, int(repo.private)),
            ).lastrowid
        else:
            repo_id = row["id"]
            conn.execute(
                "UPDATE repositories SET name = ?, location = ?, default_branch = ?, is_private = ? WHERE id = ?",
                (repo.full_name, repo.clone_url, repo.default_branch, int(repo.private), repo_id),
            )
        if repo.default_branch:
            conn.execute("INSERT OR IGNORE INTO repo_branches(repo_id, branch) VALUES (?, ?)",
                         (repo_id, repo.default_branch))
    return repo_id


def track_branch(conn: sqlite3.Connection, repo_id: int, branch: str) -> None:
    if not branch or branch.startswith("-") or ".." in branch or any(c in branch for c in " ~^:?*[\\"):
        raise ValueError(f"invalid branch name '{branch}'")
    conn.execute("INSERT OR IGNORE INTO repo_branches(repo_id, branch) VALUES (?, ?)", (repo_id, branch))


def tracked_branches(conn: sqlite3.Connection, repo_id: int) -> list[str]:
    return [r[0] for r in conn.execute("SELECT branch FROM repo_branches WHERE repo_id = ? ORDER BY branch",
                                       (repo_id,))]


def remove_repository(conn: sqlite3.Connection, settings: Settings, repo_id: int) -> dict:
    """Delete a repository's index, branches, pending jobs and mirror. Source data in Gitea is untouched."""
    repo = conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
    if repo is None:
        raise RepoNotFound(str(repo_id))
    file_ids = [r[0] for r in conn.execute("SELECT id FROM files WHERE repo_id = ?", (repo_id,))]
    FileWriter(conn, settings).delete_files(file_ids)
    prefix = f"gitea:{repo_id}:" if repo["kind"] == "gitea" else f"local:{repo_id}"
    with transaction(conn):
        cancelled = conn.execute(
            "UPDATE jobs SET status = 'cancelled', finished_at = ?, last_error = 'repository removed' "
            "WHERE status = 'queued' AND (dedupe_key = ? OR dedupe_key LIKE ?)",
            (time.time(), prefix, prefix + "%"),
        ).rowcount
        conn.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
    mirror = settings.mirrors_dir / f"{repo_id}.git"
    if mirror.is_dir():
        shutil.rmtree(mirror)
    return {"name": repo["name"], "files": len(file_ids), "cancelled_jobs": cancelled,
            "mirror_removed": not mirror.exists()}


class GiteaSyncer:
    """Synchronises one branch of a Gitea repository into the index.

    The branch tree is compared against stored git blob SHAs, so the operation is idempotent:
    re-running after a crash, a missed webhook or a force-push converges on the branch head.
    """

    def __init__(self, conn: sqlite3.Connection, settings: Settings,
                 checkpoint: Callable[[], None] | None = None,
                 progress: Callable[[dict], None] | None = None):
        self.conn = conn
        self.settings = settings
        self.writer = FileWriter(conn, settings)
        self.excluded = set(settings.excluded_dirs)
        self.checkpoint = checkpoint or (lambda: None)
        self.progress = progress or (lambda _progress: None)

    def mirror(self, repo_id: int) -> Mirror:
        token = self.settings.gitea_token.get_secret_value()
        return Mirror(self.settings.mirrors_dir / f"{repo_id}.git",
                      auth_header=f"Authorization: token {token}" if token else None,
                      timeout_s=self.settings.git_timeout_s)

    def sync(self, repo_id: int, branch: str) -> IndexStats:
        try:
            return self._sync(repo_id, branch)
        finally:
            self.writer.close()

    def _sync(self, repo_id: int, branch: str) -> IndexStats:
        repo = self.conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
        if repo is None:
            raise RepoNotFound(str(repo_id))
        if repo["kind"] != "gitea":
            raise ValueError(f"repository '{repo['name']}' is not a Gitea repository")
        started = time.monotonic()
        stats = IndexStats()
        mirror = self.mirror(repo_id)
        try:
            mirror.ensure(repo["location"])
            mirror.fetch()
            head = mirror.resolve_branch(branch)
        except GitError as exc:
            self._branch_state(repo_id, branch, last_error=str(exc))
            raise
        self._branch_state(repo_id, branch, head_sha=head)

        known = self.writer.load_known(repo_id, branch)
        if head is None:
            log.info("branch %s of %s does not exist; removing its files", branch, repo["name"])
            self.writer.delete_files([r["id"] for r in known.values()])
            stats.deleted = len(known)
            self._finish(repo_id, branch, None, stats, started)
            self.progress({"phase": "done", "current": 0, "total": 0, "percent": 100})
            return stats

        work: list[tuple[PurePosixPath, FileKind, str, int, sqlite3.Row | None]] = []
        seen: set[str] = set()
        for entry in mirror.ls_tree(head):
            if entry.obj_type != "blob":
                continue  # submodule commits have no content in this repository
            rel = PurePosixPath(entry.path)
            if is_excluded(rel, self.excluded):
                continue
            stats.scanned += 1
            self.progress({"phase": "scanning", "current": stats.scanned, "total": None, "percent": None})
            seen.add(entry.path)
            kind = classify(rel)
            prev = known.get(entry.path)
            size = entry.size or 0
            if entry.mode == SYMLINK_MODE:
                if prev and prev["content_hash"] == entry.sha and prev["status"] == "skipped":
                    stats.unchanged += 1
                else:
                    self.writer.record(repo_id, branch, rel, kind, size, None, entry.sha, head, "skipped",
                                       "symbolic link")
                    stats.skipped += 1
                continue
            if prev is not None and prev["content_hash"] == entry.sha:
                if prev["status"] == "failed":
                    if prev["attempts"] >= self.settings.file_max_attempts:
                        stats.dead_lettered += 1
                        continue
                elif prev["parser_version"] == self.writer.parser_signature(kind):
                    stats.unchanged += 1
                    continue
            work.append((rel, kind, entry.sha, size, prev))

        stale = [row["id"] for path, row in known.items() if path not in seen]
        self.writer.delete_files(stale)
        stats.deleted = len(stale)
        total = len(work)
        self.progress({"phase": "indexing", "current": 0, "total": total,
                       "percent": 100 if total == 0 else 0})

        with mirror.cat_blobs() as blobs:
            for current, (rel, kind, sha, size, prev) in enumerate(work, start=1):
                self.checkpoint()
                if not self.writer.precheck(repo_id, branch, rel, kind, size, None, sha, head, stats):
                    self.progress({"phase": "indexing", "current": current, "total": total,
                                   "percent": round(current * 100 / total) if total else 100})
                    continue
                data = blobs.read(sha)
                self.writer.index_bytes(repo_id, branch, rel, kind, data, None, sha, head, prev, stats)
                self.progress({"phase": "indexing", "current": current, "total": total,
                               "percent": round(current * 100 / total) if total else 100})

        self._finish(repo_id, branch, head, stats, started)
        self.progress({"phase": "done", "current": total, "total": total, "percent": 100})
        return stats

    def _finish(self, repo_id: int, branch: str, head: str | None, stats: IndexStats, started: float) -> None:
        stats.duration_s = round(time.monotonic() - started, 3)
        with transaction(self.conn):
            if head:
                # Every remaining file on the branch now reflects the head commit.
                self.conn.execute("UPDATE files SET commit_sha = ? WHERE repo_id = ? AND branch = ?",
                                  (head, repo_id, branch))
            self.conn.execute(
                "UPDATE repo_branches SET indexed_sha = ?, indexed_at = datetime('now'), last_error = NULL, "
                "last_stats = ? WHERE repo_id = ? AND branch = ?",
                (head, json.dumps(asdict(stats)), repo_id, branch),
            )
            self.conn.execute(
                "UPDATE repositories SET last_indexed_at = datetime('now'), last_index_stats = ? WHERE id = ?",
                (json.dumps(asdict(stats)), repo_id),
            )

    def _branch_state(self, repo_id: int, branch: str, head_sha: str | None = None,
                      last_error: str | None = None) -> None:
        self.conn.execute("INSERT OR IGNORE INTO repo_branches(repo_id, branch) VALUES (?, ?)", (repo_id, branch))
        if last_error is not None:
            self.conn.execute(
                "UPDATE repo_branches SET last_sync_at = datetime('now'), last_error = ? WHERE repo_id = ? "
                "AND branch = ?", (last_error[:1000], repo_id, branch))
        else:
            self.conn.execute(
                "UPDATE repo_branches SET last_sync_at = datetime('now'), head_sha = ? WHERE repo_id = ? "
                "AND branch = ?", (head_sha, repo_id, branch))
