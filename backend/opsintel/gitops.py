import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

MIN_GIT_VERSION = (2, 31)  # GIT_CONFIG_COUNT support


class GitError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TreeEntry:
    path: str
    mode: str
    obj_type: str
    sha: str
    size: int | None


def git_executable() -> str:
    exe = shutil.which("git")
    if not exe:
        raise GitError("git executable not found on PATH")
    return exe


class Mirror:
    """A bare mirror clone used as the read-only source of file content. No worktree is checked out."""

    def __init__(self, git_dir: Path, auth_header: str | None = None, timeout_s: int = 900):
        self.git_dir = git_dir
        self.timeout_s = timeout_s
        self._exe = git_executable()
        self._env = os.environ.copy()
        self._env["GIT_TERMINAL_PROMPT"] = "0"
        self._env["GCM_INTERACTIVE"] = "never"
        if auth_header:
            # Passed via environment so the token never appears in argv or the mirror's config file.
            self._env["GIT_CONFIG_COUNT"] = "1"
            self._env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
            self._env["GIT_CONFIG_VALUE_0"] = auth_header

    def _run(self, *args: str, git_dir: bool = True) -> str:
        cmd = [self._exe, *(["--git-dir", str(self.git_dir)] if git_dir else []), *args]
        try:
            proc = subprocess.run(cmd, env=self._env, capture_output=True, timeout=self.timeout_s, check=False)
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git {args[0]} timed out after {self.timeout_s}s") from exc
        if proc.returncode != 0:
            raise GitError(f"git {args[0]} failed ({proc.returncode}): {proc.stderr.decode(errors='replace')[:500]}")
        return proc.stdout.decode("utf-8", errors="replace")

    def exists(self) -> bool:
        return (self.git_dir / "HEAD").is_file()

    def ensure(self, clone_url: str) -> None:
        if self.exists():
            self._run("remote", "set-url", "origin", clone_url)
            return
        self.git_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.git_dir.with_name(self.git_dir.name + ".partial")
        if tmp.exists():
            shutil.rmtree(tmp)
        self._run("clone", "--mirror", "--quiet", "--", clone_url, str(tmp), git_dir=False)
        tmp.rename(self.git_dir)

    def fetch(self) -> None:
        self._run("fetch", "--prune", "--quiet", "origin", "+refs/heads/*:refs/heads/*")

    def resolve_branch(self, branch: str) -> str | None:
        try:
            return self._run("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}").strip() or None
        except GitError:
            return None

    def ls_tree(self, commit: str) -> Iterator[TreeEntry]:
        """Stream every tree entry of a commit without buffering the whole listing."""
        proc = subprocess.Popen(
            [self._exe, "--git-dir", str(self.git_dir), "ls-tree", "-r", "-z", "--long", "--full-tree", commit],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self._env,
        )
        assert proc.stdout and proc.stderr
        buf = b""
        completed = False
        try:
            while block := proc.stdout.read(65536):
                buf += block
                *records, buf = buf.split(b"\0")
                for record in records:
                    yield self._entry(record)
            if buf:
                yield self._entry(buf)
            completed = True
        finally:
            proc.stdout.close()
            if not completed:
                proc.kill()
            err = proc.stderr.read()
            proc.stderr.close()
            code = proc.wait(timeout=self.timeout_s)
            if completed and code != 0:
                raise GitError(f"git ls-tree failed: {err.decode(errors='replace')[:500]}")

    @staticmethod
    def _entry(record: bytes) -> TreeEntry:
        meta, path = record.split(b"\t", 1)
        mode, obj_type, sha, size = meta.decode("ascii").split()
        return TreeEntry(path.decode("utf-8", errors="replace"), mode, obj_type, sha,
                         None if size == "-" else int(size))

    def cat_blobs(self) -> "BlobReader":
        return BlobReader(self._exe, self.git_dir, self._env)


class BlobReader:
    """Streams blob contents through a single long-lived `git cat-file --batch` process."""

    def __init__(self, exe: str, git_dir: Path, env: dict):
        self._proc = subprocess.Popen(
            [exe, "--git-dir", str(git_dir), "cat-file", "--batch"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
        )

    def read(self, sha: str) -> bytes:
        assert self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(sha.encode("ascii") + b"\n")
        self._proc.stdin.flush()
        header = self._proc.stdout.readline().decode("ascii", errors="replace").split()
        if len(header) != 3:
            raise GitError(f"object {sha} missing: {' '.join(header)}")
        size = int(header[2])
        data = self._proc.stdout.read(size)
        self._proc.stdout.read(1)  # trailing LF
        return data

    def close(self) -> None:
        if self._proc.stdin:
            self._proc.stdin.close()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()

    def __enter__(self) -> "BlobReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def git_version() -> tuple[int, ...]:
    out = subprocess.run([git_executable(), "--version"], capture_output=True, text=True, timeout=10).stdout
    digits = out.strip().split()[-1].split(".")
    return tuple(int("".join(c for c in d if c.isdigit()) or 0) for d in digits[:3])
