from opsintel.db import connect
from opsintel.indexing import LocalIndexer, register_local_repo
from tests.conftest import write


def seed(settings, repo_dir):
    write(repo_dir / "app" / "logout.py", "\n".join(f"# line {i}" for i in range(1, 40)) + "\ndef handle_logout():\n")
    conn = connect(settings)
    LocalIndexer(conn, settings).index_repo(register_local_repo(conn, "demo", repo_dir))
    conn.close()


def test_health_without_ai(client):
    body = client.get("/api/health").json()
    assert body["db"]["ok"] and body["search_available"] and body["ai"] == {"enabled": False}


def test_search_and_view_lines(client, settings, repo_dir):
    seed(settings, repo_dir)
    res = client.get("/api/search", params={"q": "handle_logout"}).json()
    assert res["total"] == 1
    r = res["results"][0]
    assert r["location"]["line"] == 40

    view = client.get(f"/api/files/{r['file_id']}/lines", params={"start": 38, "end": 45}).json()
    assert view["line_count"] == 40
    assert [ln["line"] for ln in view["lines"]] == [38, 39, 40]
    assert view["lines"][-1]["text"] == "def handle_logout():"
    assert view["lines"][0]["text"] == "# line 38"


def test_search_validation(client, settings, repo_dir):
    seed(settings, repo_dir)
    assert client.get("/api/search", params={"q": "ab", "mode": "exact"}).status_code == 400
    assert client.get("/api/search", params={"q": "!!!"}).status_code == 400
    assert client.get("/api/search", params={"q": "x", "mode": "regex"}).status_code == 422
    assert client.get("/api/files/9999").status_code == 404


def test_repos_and_facets(client, settings, repo_dir):
    seed(settings, repo_dir)
    [repo] = client.get("/api/repos").json()
    assert repo["name"] == "demo" and repo["indexed"] == 1
    facets = client.get("/api/facets").json()
    assert facets["file_types"] == [{"file_type": "code", "n": 1}]
