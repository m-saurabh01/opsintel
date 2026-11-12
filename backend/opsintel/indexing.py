import hashlib
import json
import logging
import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from opsintel.config import Settings
from opsintel.db import transaction
from opsintel.discovery import FileKind, classify, is_excluded
from opsintel.parsers.base import Chunk, ParseError, Parser, ParseResult
from opsintel.parsers.cache import ParseCache
from opsintel.parsers.registry import ParserRegistry
from opsintel.parsers.sandbox import ParserSandbox
from opsintel.search_metadata import build_search_metadata

log = logging.getLogger(__name__)


@dataclass
class IndexStats:
    scanned: int = 0
    indexed: int = 0
    unchanged: int = 0
    skipped: int = 0
    unsupported: int = 0
    failed: int = 0
    dead_lettered: int = 0
    deleted: int = 0
    chunks_written: int = 0
    duration_s: float = 0.0


class RepoNotFound(LookupError):
    pass


def register_local_repo(conn: sqlite3.Connection, name: str, path: Path) -> int:
    root = path.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    row = conn.execute("SELECT id, kind, location FROM repositories WHERE name = ?", (name,)).fetchone()
    if row:
        if row["kind"] != "local" or row["location"] != str(root):
            raise ValueError(f"repository '{name}' already exists with a different location")
        return row["id"]
    cur = conn.execute(
        "INSERT INTO repositories(name, kind, location) VALUES (?, 'local', ?)", (name, str(root))
    )
    return cur.lastrowid


def get_repo(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM repositories WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise RepoNotFound(name)
    return row


class FileWriter:
    """Decides whether a file needs (re)parsing and writes its chunks atomically."""

    def __init__(self, conn: sqlite3.Connection, settings: Settings):
        self.conn = conn
        self.settings = settings
        self.registry = ParserRegistry(settings)
        self.cache = ParseCache(conn, settings.parse_cache_max_mb * 1024 * 1024)
        self._sandbox: ParserSandbox | None = None

    def close(self) -> None:
        if self._sandbox is not None:
            self._sandbox.close()
            self._sandbox = None

    def parser_signature(self, kind: FileKind) -> str | None:
        parser = self.registry.for_kind(kind)
        return parser.signature if parser else None

    def load_known(self, repo_id: int, branch: str) -> dict[str, sqlite3.Row]:
        return {
            r["path"]: r
            for r in self.conn.execute(
                "SELECT id, path, size, mtime_ns, content_hash, parser_version, status, attempts FROM files "
                "WHERE repo_id = ? AND branch = ?",
                (repo_id, branch),
            )
        }

    def precheck(self, repo_id, branch, rel: PurePosixPath, kind: FileKind, size: int, mtime_ns, content_hash,
                 commit_sha, stats: IndexStats) -> bool:
        """Record files that will not be parsed. Returns True if the content should be read and parsed."""
        sig = self.parser_signature(kind)
        if size > self.settings.max_file_size_bytes:
            self.record(repo_id, branch, rel, kind, size, mtime_ns, content_hash, commit_sha, "skipped",
                        f"exceeds max_file_size_mb ({self.settings.max_file_size_mb})", parser_sig=sig)
            stats.skipped += 1
            return False
        if kind.file_type == "binary":
            self.record(repo_id, branch, rel, kind, size, mtime_ns, content_hash, commit_sha, "skipped",
                        "binary file type")
            stats.skipped += 1
            return False
        if sig is None:
            self.record(repo_id, branch, rel, kind, size, mtime_ns, content_hash, commit_sha, "unsupported",
                        self.registry.unsupported_reason(kind))
            stats.unsupported += 1
            return False
        return True

    def _parse(self, parser: Parser, data: bytes, content_hash: str) -> tuple[list[Chunk], ParseResult]:
        if not parser.isolated:
            result = ParseResult()
            return list(parser.parse(data, result)), result
        cached = self.cache.get(content_hash, parser.signature)
        if cached is not None:
            return cached
        if self._sandbox is None:
            self._sandbox = ParserSandbox(self.settings.parse_timeout_s)
        chunks, result = self._sandbox.run(parser, data)
        self.cache.put(content_hash, parser.signature, chunks, result)
        return chunks, result

    def index_bytes(self, repo_id, branch, rel: PurePosixPath, kind: FileKind, data: bytes, mtime_ns,
                    content_hash: str, commit_sha: str | None, prev, stats: IndexStats) -> None:
        parser = self.registry.for_kind(kind)
        if parser is None:
            raise ValueError(f"no parser for {rel}; precheck() must be called first")
        parser_sig = parser.signature
        try:
            chunks, result = self._parse(parser, data, content_hash)
        except ParseError as exc:
            status = "unsupported" if kind.file_type == "unknown" else "skipped"
            self.record(repo_id, branch, rel, kind, len(data), mtime_ns, content_hash, commit_sha, status,
                        str(exc)[:500], parser_sig=parser_sig)
            setattr(stats, status, getattr(stats, status) + 1)
            return
        except Exception as exc:  # parser bugs, timeouts and crashes must not abort the whole run
            log.warning("parser %s failed on %s: %s", parser.name, rel, exc)
            same_content = prev is not None and prev["content_hash"] == content_hash
            attempts = (prev["attempts"] if same_content else 0) + 1
            self.record(repo_id, branch, rel, kind, len(data), mtime_ns, content_hash, commit_sha, "failed",
                        f"{type(exc).__name__}: {exc}"[:500], attempts=attempts)
            stats.failed += 1
            return

        file_type = "text" if kind.file_type == "unknown" else kind.file_type
        reason = "; ".join(result.warnings)[:500] or None
        with transaction(self.conn):
            file_id = self._upsert(repo_id, branch, rel, file_type, kind.language, len(data), mtime_ns,
                                   content_hash, commit_sha, "indexed", reason, parser_sig, result, 0)
            self.conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
            chunk_rows = []
            for chunk in chunks:
                extra_json = json.dumps(chunk.extra) if chunk.extra else None
                search_metadata = build_search_metadata(
                    chunk.text, chunk.sheet, chunk.section_path, chunk.key_path, extra_json,
                )
                chunk_rows.append((file_id, chunk.ordinal, chunk.text, chunk.coord_kind, chunk.start_line,
                                   chunk.end_line, chunk.page, chunk.sheet, chunk.cell_ref, chunk.row_num,
                                   chunk.section_path, chunk.key_path, extra_json, search_metadata))
            self.conn.executemany(
                "INSERT INTO chunks(file_id, ordinal, text, coord_kind, start_line, end_line, page, sheet, cell_ref, "
                "row_num, section_path, key_path, extra_json, search_metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                chunk_rows,
            )
        stats.indexed += 1
        stats.chunks_written += len(chunks)

    def record(self, repo_id, branch, rel, kind: FileKind, size, mtime_ns, content_hash, commit_sha, status, reason,
               parser_sig=None, attempts=0) -> None:
        with transaction(self.conn):
            file_id = self._upsert(repo_id, branch, rel, kind.file_type, kind.language, size, mtime_ns,
                                   content_hash, commit_sha, status, reason, parser_sig, ParseResult(), attempts)
            self.conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

    def delete_files(self, file_ids: list[int]) -> None:
        for i in range(0, len(file_ids), 500):
            batch = file_ids[i: i + 500]
            marks = ",".join("?" * len(batch))
            with transaction(self.conn):
                self.conn.execute(f"DELETE FROM chunks WHERE file_id IN ({marks})", batch)  # noqa: S608
                self.conn.execute(f"DELETE FROM files WHERE id IN ({marks})", batch)  # noqa: S608

    def _upsert(self, repo_id, branch, rel, file_type, language, size, mtime_ns, content_hash, commit_sha, status,
                reason, parser_sig, result: ParseResult, attempts: int) -> int:
        row = self.conn.execute(
            """
            INSERT INTO files(repo_id, branch, path, file_type, language, size, mtime_ns, content_hash, commit_sha,
                              encoding, line_count, parser_name, parser_version, status, status_reason, attempts,
                              indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(repo_id, branch, path) DO UPDATE SET
                file_type = excluded.file_type, language = excluded.language, size = excluded.size,
                mtime_ns = excluded.mtime_ns, content_hash = excluded.content_hash,
                commit_sha = excluded.commit_sha, encoding = excluded.encoding, line_count = excluded.line_count,
                parser_name = excluded.parser_name, parser_version = excluded.parser_version,
                status = excluded.status, status_reason = excluded.status_reason, attempts = excluded.attempts,
                indexed_at = excluded.indexed_at
            RETURNING id
            """,
            (repo_id, branch, rel.as_posix(), file_type, language, size, mtime_ns, content_hash, commit_sha,
             result.encoding, result.line_count, parser_sig.split(":", 1)[0] if parser_sig else None, parser_sig,
             status, reason, attempts),
        ).fetchone()
        return row[0]


class LocalIndexer:
    """Incrementally indexes a directory tree. Only new or changed files are parsed."""

    def __init__(self, conn: sqlite3.Connection, settings: Settings,
                 checkpoint: Callable[[], None] | None = None, progress: Callable[[dict], None] | None = None):
        self.conn = conn
        self.settings = settings
        self.writer = FileWriter(conn, settings)
        self.excluded = set(settings.excluded_dirs)
        self.checkpoint = checkpoint or (lambda: None)
        self.progress = progress or (lambda _progress: None)

    def index_repo(self, repo_id: int, branch: str = "") -> IndexStats:
        try:
            return self._index_repo(repo_id, branch)
        finally:
            self.writer.close()

    def _index_repo(self, repo_id: int, branch: str) -> IndexStats:
        repo = self.conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
        if repo is None:
            raise RepoNotFound(str(repo_id))
        if repo["kind"] != "local":
            raise ValueError(f"repository '{repo['name']}' is not a local folder")
        root = Path(repo["location"])
        started = time.monotonic()
        stats = IndexStats()
        known = self.writer.load_known(repo_id, branch)
        seen: set[str] = set()
        self.progress({"phase": "counting", "current": 0, "total": 0, "percent": None})
        total = sum(1 for _ in self._walk(root))
        self.progress({"phase": "indexing", "current": 0, "total": total,
                       "percent": 100 if total == 0 else 0})
        completed = 0

        for abs_path, rel in self._walk(root):
            self.checkpoint()
            stats.scanned += 1
            seen.add(rel.as_posix())
            try:
                self._index_file(repo_id, branch, abs_path, rel, known.get(rel.as_posix()), stats)
            except OSError as exc:
                log.warning("cannot read %s: %s", rel, exc)
                self.writer.record(repo_id, branch, rel, FileKind("unknown", None), 0, None, None, None, "failed",
                                   f"read error: {exc}")
                stats.failed += 1
            finally:
                completed += 1
                self.progress({"phase": "indexing", "current": completed, "total": total,
                               "percent": round(completed * 100 / total) if total else 100})

        stale = [row["id"] for path, row in known.items() if path not in seen]
        self.writer.delete_files(stale)
        stats.deleted = len(stale)

        stats.duration_s = round(time.monotonic() - started, 3)
        self.progress({"phase": "done", "current": total, "total": total, "percent": 100})
        self.conn.execute(
            "UPDATE repositories SET last_indexed_at = datetime('now'), last_index_stats = ? WHERE id = ?",
            (str(asdict(stats)), repo_id),
        )
        return stats

    def _walk(self, root: Path):
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if d not in self.excluded)
            base = Path(dirpath)
            for fname in sorted(filenames):
                abs_path = base / fname
                if abs_path.is_symlink() or not abs_path.is_file():
                    continue  # symlinks may point outside the repository
                rel = PurePosixPath(abs_path.relative_to(root).as_posix())
                if is_excluded(rel, self.excluded):
                    continue
                yield abs_path, rel

    def _index_file(self, repo_id, branch, abs_path: Path, rel: PurePosixPath, prev, stats: IndexStats):
        st = abs_path.stat()
        kind = classify(rel)
        parser_sig = self.writer.parser_signature(kind)

        if (
            prev is not None
            and prev["size"] == st.st_size
            and prev["mtime_ns"] == st.st_mtime_ns
            and prev["parser_version"] == parser_sig
            and prev["status"] != "failed"
        ):
            stats.unchanged += 1
            return

        if not self.writer.precheck(repo_id, branch, rel, kind, st.st_size, st.st_mtime_ns, None, None, stats):
            return

        data = abs_path.read_bytes()
        content_hash = hashlib.sha256(data).hexdigest()
        if prev is not None and prev["content_hash"] == content_hash and prev["parser_version"] == parser_sig \
                and prev["status"] == "indexed":
            self.conn.execute("UPDATE files SET mtime_ns = ?, size = ? WHERE id = ?",
                              (st.st_mtime_ns, st.st_size, prev["id"]))
            stats.unchanged += 1
            return
        self.writer.index_bytes(repo_id, branch, rel, kind, data, st.st_mtime_ns, content_hash, None, prev, stats)
