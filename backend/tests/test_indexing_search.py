import os

from opsintel.indexing import LocalIndexer, register_local_repo
from opsintel.search import SearchRequest, search
from tests.conftest import write


def index(conn, settings, repo_dir):
    repo_id = register_local_repo(conn, "demo", repo_dir)
    return LocalIndexer(conn, settings).index_repo(repo_id)


def hits(conn, q, mode="fulltext", **kw):
    return search(conn, SearchRequest(q=q, mode=mode, **kw))["results"]


def bump_mtime(path):
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def test_index_and_locate_exact_line(conn, settings, repo_dir):
    body = "\r\n".join(["package a;", *[f"// filler {i}" for i in range(30)], "class AuthHeaderValidator {}"])
    write(repo_dir / "src" / "Auth.java", body)
    stats = index(conn, settings, repo_dir)
    assert stats.indexed == 1

    [r] = hits(conn, "AuthHeaderValidator")
    assert r["path"] == "src/Auth.java"
    assert r["location"]["line"] == 32
    assert r["language"] == "java"
    line = next(p for p in r["preview"] if p["line"] == 32)
    s, e = line["highlights"][0]
    assert line["text"][s:e] == "AuthHeaderValidator"


def test_incremental_unchanged_modified_deleted_renamed(conn, settings, repo_dir):
    a = write(repo_dir / "a.py", "alpha_token = 1\n")
    write(repo_dir / "b.py", "beta_token = 2\n")
    assert index(conn, settings, repo_dir).indexed == 2

    stats = index(conn, settings, repo_dir)
    assert (stats.indexed, stats.unchanged) == (0, 2)

    bump_mtime(a)  # touched but same content: hash check avoids re-parse
    stats = index(conn, settings, repo_dir)
    assert (stats.indexed, stats.unchanged) == (0, 2)

    write(a, "gamma_token = 3\n")
    bump_mtime(a)
    stats = index(conn, settings, repo_dir)
    assert stats.indexed == 1
    assert hits(conn, "alpha_token") == []
    assert len(hits(conn, "gamma_token")) == 1

    (repo_dir / "b.py").rename(repo_dir / "c.py")
    stats = index(conn, settings, repo_dir)
    assert (stats.indexed, stats.deleted) == (1, 1)
    assert [r["path"] for r in hits(conn, "beta_token")] == ["c.py"]

    (repo_dir / "c.py").unlink()
    index(conn, settings, repo_dir)
    assert hits(conn, "beta_token") == []
    assert hits(conn, "beta_tok", mode="exact") == []
    assert conn.execute("SELECT count(*) FROM chunks c LEFT JOIN files f ON f.id=c.file_id "
                        "WHERE f.id IS NULL").fetchone()[0] == 0


def test_exclusions_binary_unsupported_and_large(conn, settings, repo_dir):
    write(repo_dir / "node_modules" / "x.js", "hidden_dep_symbol\n")
    write(repo_dir / "img.png", b"\x89PNG\x00\x00")
    write(repo_dir / "doc.pdf", b"%PDF-1.4")
    write(repo_dir / "mystery.dat2", b"\x00\x00binary")
    write(repo_dir / "notes.custom", "visible_custom_text\n")
    settings.max_file_size_mb = 0.0001
    write(repo_dir / "big.txt", "x" * 1000)
    stats = index(conn, settings, repo_dir)

    status = {r["path"]: r["status"] for r in conn.execute("SELECT path, status FROM files")}
    assert "node_modules/x.js" not in status
    assert status == {
        "img.png": "skipped", "doc.pdf": "skipped", "mystery.dat2": "unsupported",
        "notes.custom": "indexed", "big.txt": "skipped",
    }
    reason = conn.execute("SELECT status_reason FROM files WHERE path = 'doc.pdf'").fetchone()[0]
    assert reason.startswith("cannot open PDF")
    assert stats.failed == 0
    assert hits(conn, "visible_custom_text")[0]["file_type"] == "text"


def test_search_modes_and_filters(conn, settings, repo_dir):
    write(repo_dir / "conf" / "db.properties", "db2.connection.timeout=30\n")
    write(repo_dir / "src" / "Db.java", "int connectionTimeout = 30; // connection timeout\n")
    index(conn, settings, repo_dir)

    assert {r["path"] for r in hits(conn, "connection timeout")} == {"conf/db.properties", "src/Db.java"}
    assert {r["path"] for r in hits(conn, "connection timeout", mode="phrase")} == \
        {"conf/db.properties", "src/Db.java"}
    assert hits(conn, "timeout connection", mode="phrase") == []
    assert {r["path"] for r in hits(conn, "connectionTim", mode="exact")} == {"src/Db.java"}
    assert hits(conn, "CONNECTIONTIM", mode="exact", case_sensitive=True) == []
    assert {r["path"] for r in hits(conn, "connection", file_types=["structured"])} == {"conf/db.properties"}
    assert {r["path"] for r in hits(conn, "connection", path_prefix="src/")} == {"src/Db.java"}
    assert {r["path"] for r in hits(conn, "conn*")} == {"conf/db.properties", "src/Db.java"}


def test_query_injection_is_neutralised(conn, settings, repo_dir):
    write(repo_dir / "a.txt", 'say "hello" NEAR world\n')
    index(conn, settings, repo_dir)
    assert len(hits(conn, 'hello" OR "x')) == 0  # quotes cannot break out of terms
    assert len(hits(conn, '"hello"')) == 1
    assert len(hits(conn, 'say "hel', mode="exact")) == 1
