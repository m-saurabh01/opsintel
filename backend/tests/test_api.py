from opsintel.db import connect, migrate
from opsintel.indexing import LocalIndexer, register_local_repo
from opsintel.main import create_app
from tests.conftest import write


def seed(settings, repo_dir):
    write(repo_dir / "app" / "logout.py", "\n".join(f"# line {i}" for i in range(1, 40)) + "\ndef handle_logout():\n")
    conn = connect(settings)
    LocalIndexer(conn, settings).index_repo(register_local_repo(conn, "demo", repo_dir))
    conn.close()


def test_health_without_ai(client):
    body = client.get("/api/health").json()
    assert body["db"]["ok"] and body["search_available"] and body["ai"] == {"enabled": False}


def test_authentication_bootstrap_and_csrf(settings):
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings), client=("127.0.0.1", 49153)) as unauthenticated:
        assert unauthenticated.get("/api/auth/status").json() == {"setup_required": True}
        assert unauthenticated.get("/api/search", params={"q": "secret"}).status_code == 401
        created = unauthenticated.post(
            "/api/auth/bootstrap", json={"username": "administrator", "password": "strong-password-123"})
        assert created.status_code == 201
        assert unauthenticated.get("/api/auth/me").json()["user"]["role"] == "admin"
        assert unauthenticated.post(
            "/api/auth/bootstrap", json={"username": "second-admin", "password": "strong-password-456"}
        ).status_code == 409
        assert unauthenticated.post("/api/auth/logout").status_code == 403
        unauthenticated.headers["X-CSRF-Token"] = unauthenticated.cookies.get("opsintel_csrf", "")
        assert unauthenticated.post("/api/auth/logout").status_code == 200
        assert unauthenticated.get("/api/auth/me").status_code == 401


def test_origin_check_allows_loopback_aliases_but_rejects_external_origin(settings):
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000",
                    client=("127.0.0.1", 49156)) as client:
        invalid_username = client.post("/api/auth/bootstrap", headers={"Origin": "http://localhost:8000"},
                                       json={"username": "x", "password": "strong-password-123"})
        assert invalid_username.status_code == 400
        external_origin = client.post("/api/auth/bootstrap", headers={"Origin": "https://attacker.example"},
                                      json={"username": "x", "password": "strong-password-123"})
        assert external_origin.status_code == 403


def test_origin_check_allows_vite_dev_origin(settings):
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings), base_url="http://127.0.0.1:8000",
                    client=("127.0.0.1", 49157)) as client:
        response = client.post("/api/auth/bootstrap", headers={"Origin": "http://127.0.0.1:5173"},
                               json={"username": "x", "password": "strong-password-123"})
        assert response.status_code == 400


def test_ungranted_user_cannot_discover_or_fetch_repository(settings, repo_dir):
    from fastapi.testclient import TestClient

    write(repo_dir / "private.txt", "private_document_marker\n")
    conn = connect(settings)
    migrate(conn)
    repo_id = register_local_repo(conn, "private-repo", repo_dir)
    LocalIndexer(conn, settings).index_repo(repo_id)
    conn.close()
    with TestClient(create_app(settings), client=("127.0.0.1", 49154)) as client:
        client.post("/api/auth/bootstrap", json={"username": "admin-user", "password": "strong-password-123"})
        client.headers["X-CSRF-Token"] = client.cookies.get("opsintel_csrf", "")
        created = client.post("/api/admin/users", json={
            "username": "limited-user", "password": "another-password-123", "repo_ids": [],
        })
        assert created.status_code == 201
        conn = connect(settings)
        file_id = conn.execute("SELECT id FROM files WHERE repo_id = ?", (repo_id,)).fetchone()[0]
        conn.close()
        client.post("/api/auth/logout")
        client.post("/api/auth/login", json={"username": "limited-user", "password": "another-password-123"})
        client.headers["X-CSRF-Token"] = client.cookies.get("opsintel_csrf", "")

        assert client.get("/api/repos").json() == []
        assert client.get("/api/search", params={"q": "private_document_marker"}).json()["total"] == 0
        assert client.get(f"/api/files/{file_id}").status_code == 404
        assert client.get("/api/admin/status").status_code == 403


def test_admin_local_repository_action_is_scoped_and_audited(settings, tmp_path):
    from fastapi.testclient import TestClient

    root = tmp_path / "allowed"
    repository = root / "checkout"
    repository.mkdir(parents=True)
    settings.local_repo_allowed_roots = [root]
    with TestClient(create_app(settings), client=("127.0.0.1", 49155)) as client:
        client.post("/api/auth/bootstrap", json={"username": "admin-user", "password": "strong-password-123"})
        client.headers["X-CSRF-Token"] = client.cookies.get("opsintel_csrf", "")

        result = client.post("/api/admin/repos/local", json={"path": str(repository)})

        assert result.status_code == 202
        conn = connect(settings)
        try:
            repo = conn.execute("SELECT id, name FROM repositories").fetchone()
            assert repo["name"] == "checkout"
            queued = conn.execute(
                "SELECT count(*) FROM jobs WHERE queue = 'sync' AND status = 'queued'"
            ).fetchone()[0]
            assert queued == 1
            assert conn.execute("SELECT action FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()[0] == \
                "repository.add_local"
        finally:
            conn.close()


def test_admin_status_exposes_active_repository_index_progress(client, settings, repo_dir):
    from opsintel import jobs

    registration_conn = connect(settings)
    repo_id = register_local_repo(registration_conn, "progress-demo", repo_dir)
    registration_conn.close()
    conn = connect(settings)
    try:
        job_id, _ = jobs.enqueue(
            conn, "sync", f"local:{repo_id}", {"type": "local", "repo_id": repo_id},
        )
        assert jobs.lease(conn, ["sync"], "test-worker", settings.worker_lease_s).id == job_id
        jobs.set_progress(conn, job_id, {"phase": "indexing", "current": 3, "total": 8, "percent": 38})
        response = client.get("/api/admin/status")
    finally:
        conn.close()

    assert response.status_code == 200
    assert response.json()["indexing"][str(repo_id)] == [{
        "id": job_id,
        "status": "running",
        "branch": None,
        "progress": {"phase": "indexing", "current": 3, "total": 8, "percent": 38},
    }]


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


def test_search_result_links_to_gitea_commit(client, settings, repo_dir):
    seed(settings, repo_dir)
    conn = connect(settings)
    conn.execute("UPDATE repositories SET kind = 'gitea', name = 'acme/my-app'")
    conn.execute("UPDATE files SET commit_sha = 'abc123'")
    conn.close()
    settings.gitea_url = "https://gitea.example.test/api-prefix"
    settings.gitea_web_url = "https://gitea.example.test/gitea"

    [result] = client.get("/api/search", params={"q": "handle_logout"}).json()["results"]

    assert result["source_url"] == (
        "https://gitea.example.test/gitea/acme/my-app/src/commit/abc123/app/logout.py#L40"
    )
    assert "token" not in result["source_url"]


def test_local_search_result_has_no_gitea_link(client, settings, repo_dir):
    seed(settings, repo_dir)
    settings.gitea_web_url = "https://gitea.example.test/gitea"

    [result] = client.get("/api/search", params={"q": "handle_logout"}).json()["results"]

    assert result["source_url"] is None


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
