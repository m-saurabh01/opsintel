import subprocess
from pathlib import Path

import pytest

from opsintel.gitea import GiteaRepo
from opsintel.parsers.text import TextParser
from opsintel.search import SearchRequest, search
from opsintel.sync import GiteaSyncer, register_gitea_repo, track_branch
from tests.conftest import write

GIT_CFG = ["-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
           "-c", "core.autocrlf=false"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *GIT_CFG, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit_all(src: Path, msg: str = "change") -> str:
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", msg)
    return git(src, "rev-parse", "HEAD")


@pytest.fixture
def src(tmp_path: Path) -> Path:
    d = tmp_path / "src"
    d.mkdir()
    git(d, "init", "-q", "-b", "main")
    return d


@pytest.fixture
def repo_id(conn, src):
    return register_gitea_repo(conn, GiteaRepo(id=42, full_name="acme/app", clone_url=str(src),
                                               default_branch="main", private=True, empty=False, archived=False))


def hits(conn, q, **kw):
    return search(conn, SearchRequest(q=q, **kw))["results"]


def files(conn, repo_id, branch="main"):
    return {r["path"]: dict(r) for r in conn.execute("SELECT * FROM files WHERE repo_id = ? AND branch = ?",
                                                     (repo_id, branch))}


def test_initial_and_noop_sync(conn, settings, src, repo_id):
    write(src / "src" / "Auth.java", "class A {}\r\n// validateAuthHeader here\r\n")
    write(src / "node_modules" / "dep.js", "excluded_symbol\n")
    write(src / "logo.png", b"\x89PNG\x00\x00")
    write(src / "README.md", "hello\n")
    head = commit_all(src)
    sha = git(src, "hash-object", "-w", "README.md")
    git(src, "update-index", "--add", "--cacheinfo", f"120000,{sha},link-to-readme")
    git(src, "commit", "-q", "-m", "symlink")
    head = git(src, "rev-parse", "HEAD")

    stats = GiteaSyncer(conn, settings).sync(repo_id, "main")
    assert (stats.indexed, stats.skipped, stats.scanned) == (2, 2, 4)
    f = files(conn, repo_id)
    assert set(f) == {"src/Auth.java", "logo.png", "README.md", "link-to-readme"}
    assert all(row["commit_sha"] == head for row in f.values())
    assert f["link-to-readme"]["status_reason"] == "symbolic link"
    [r] = hits(conn, "validateAuthHeader")
    assert (r["location"]["line"], r["commit_sha"], r["branch"]) == (2, head, "main")

    again = GiteaSyncer(conn, settings).sync(repo_id, "main")
    assert (again.indexed, again.unchanged, again.skipped, again.deleted) == (0, 4, 0, 0)


def test_modify_rename_delete(conn, settings, src, repo_id):
    write(src / "a.py", "alpha_symbol = 1\n")
    write(src / "b.py", "beta_symbol = 2\n")
    write(src / "c.py", "gamma_symbol = 3\n")
    commit_all(src)
    GiteaSyncer(conn, settings).sync(repo_id, "main")

    write(src / "a.py", "alpha_changed = 1\n")
    (src / "renamed").mkdir()
    git(src, "mv", "b.py", "renamed/b.py")
    (src / "c.py").unlink()
    head = commit_all(src)
    stats = GiteaSyncer(conn, settings).sync(repo_id, "main")
    assert (stats.indexed, stats.deleted) == (2, 2)
    assert hits(conn, "alpha_symbol") == [] and len(hits(conn, "alpha_changed")) == 1
    assert [r["path"] for r in hits(conn, "beta_symbol")] == ["renamed/b.py"]
    assert hits(conn, "gamma_symbol") == []
    assert {r["commit_sha"] for r in files(conn, repo_id).values()} == {head}


def test_history_rewrite_and_branch_deletion(conn, settings, src, repo_id):
    write(src / "a.txt", "first_version\n")
    commit_all(src)
    git(src, "checkout", "-q", "-b", "feature")
    write(src / "f.txt", "feature_only_text\n")
    commit_all(src)
    git(src, "checkout", "-q", "main")
    track_branch(conn, repo_id, "feature")
    GiteaSyncer(conn, settings).sync(repo_id, "main")
    GiteaSyncer(conn, settings).sync(repo_id, "feature")
    assert [r["branch"] for r in hits(conn, "feature_only_text")] == ["feature"]

    write(src / "a.txt", "rewritten_version\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "--amend", "-m", "rewritten")  # force-push equivalent
    git(src, "branch", "-q", "-D", "feature")
    GiteaSyncer(conn, settings).sync(repo_id, "main")
    stats = GiteaSyncer(conn, settings).sync(repo_id, "feature")
    assert stats.deleted == 2
    assert hits(conn, "feature_only_text") == []
    assert hits(conn, "first_version", branch="main") == []
    assert len(hits(conn, "rewritten_version")) == 1


def test_interrupted_sync_resumes_without_duplicates(conn, settings, src, repo_id):
    for i in range(6):
        write(src / f"f{i}.txt", f"token_{i} shared_word\n")
    commit_all(src)

    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError):
        GiteaSyncer(conn, settings, checkpoint=boom).sync(repo_id, "main")
    assert len(files(conn, repo_id)) == 3

    stats = GiteaSyncer(conn, settings).sync(repo_id, "main")
    assert (stats.indexed, stats.unchanged) == (3, 3)
    assert search(conn, SearchRequest(q="shared_word"))["total"] == 6
    dupes = conn.execute("SELECT count(*) FROM (SELECT file_id, ordinal, count(*) c FROM chunks "
                         "GROUP BY file_id, ordinal HAVING c > 1)").fetchone()[0]
    assert dupes == 0


def test_failing_file_is_dead_lettered_then_retried_on_change(conn, settings, src, repo_id, monkeypatch):
    write(src / "bad.txt", "explode\n")
    write(src / "good.txt", "fine\n")
    commit_all(src)
    original = TextParser.parse

    def flaky(self, data, result):
        if b"explode" in data:
            raise MemoryError("parser blew up")
        return original(self, data, result)

    monkeypatch.setattr("opsintel.parsers.text.TextParser.parse", flaky)
    settings.file_max_attempts = 2
    s1 = GiteaSyncer(conn, settings).sync(repo_id, "main")
    s2 = GiteaSyncer(conn, settings).sync(repo_id, "main")
    s3 = GiteaSyncer(conn, settings).sync(repo_id, "main")
    assert (s1.failed, s2.failed, s3.failed, s3.dead_lettered) == (1, 1, 0, 1)
    assert files(conn, repo_id)["bad.txt"]["attempts"] == 2

    write(src / "bad.txt", "now fine\n")
    commit_all(src)
    s4 = GiteaSyncer(conn, settings).sync(repo_id, "main")
    assert s4.indexed == 1
    assert files(conn, repo_id)["bad.txt"]["status"] == "indexed"


def test_remove_repository_drops_index_jobs_and_mirror(conn, settings, src, repo_id):
    from opsintel import jobs
    from opsintel.sync import remove_repository

    write(src / "a.txt", "removable_text\n")
    commit_all(src)
    GiteaSyncer(conn, settings).sync(repo_id, "main")
    jobs.enqueue(conn, "sync", f"gitea:{repo_id}:main", {})
    assert (settings.mirrors_dir / f"{repo_id}.git").is_dir()

    result = remove_repository(conn, settings, repo_id)
    assert result == {"name": "acme/app", "files": 1, "cancelled_jobs": 1, "mirror_removed": True}
    assert hits(conn, "removable_text") == []
    for table in ("files", "chunks", "repo_branches"):
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0  # noqa: S608
    assert conn.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'removable_text'").fetchone()[0] == 0


def test_register_is_idempotent(conn, src, repo_id):
    again = register_gitea_repo(conn, GiteaRepo(id=42, full_name="acme/renamed", clone_url=str(src),
                                                default_branch="main", private=False, empty=False, archived=False))
    assert again == repo_id
    row = conn.execute("SELECT name, is_private FROM repositories WHERE id = ?", (repo_id,)).fetchone()
    assert tuple(row) == ("acme/renamed", 0)
    with pytest.raises(ValueError):
        track_branch(conn, repo_id, "--upload-pack=evil")
