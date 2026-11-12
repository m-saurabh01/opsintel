import asyncio
import json

import httpx
import pytest

from opsintel.config import Settings
from opsintel.db import connect, migrate
from opsintel.indexing import LocalIndexer, register_local_repo
from opsintel.jobs import get
from tests.conftest import authenticated_client, write


async def ready_status(*_args, **_kwargs):
    return {"reachable": True, "version": "0.10.0", "version_ok": True,
            "model_present": True, "model": "test-local-model"}


async def idle_runner(_self):
    await asyncio.sleep(0)


def test_ai_ask_is_disabled_when_configured_off(client):
    response = client.post("/api/ai/ask", json={"question": "Where is logout handled?"})
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]


def test_ai_queue_is_bounded_and_cancelable(tmp_path, monkeypatch):
    from opsintel import main
    from opsintel.ai_queue import AIQueueRunner

    monkeypatch.setattr(main.ollama, "status", ready_status)
    monkeypatch.setattr(AIQueueRunner, "run", idle_runner)
    settings = Settings(_env_file=None, opsintel_data_dir=tmp_path / "data", ai_enabled=True, ai_max_queue=1)
    source = tmp_path / "repo"
    source.mkdir()
    conn = connect(settings)
    migrate(conn)
    register_local_repo(conn, "sample", source)
    conn.close()
    with authenticated_client(settings) as client:
        first = client.post("/api/ai/ask", json={"question": "Where is logout handled?"})
        assert first.status_code == 202
        job_id = first.json()["job_id"]

        full = client.post("/api/ai/ask", json={"question": "How is the auth token validated?"})
        assert full.status_code == 429

        cancelled = client.delete(f"/api/ai/ask/{job_id}")
        assert cancelled.json()["status"] == "cancelled"
        events = client.get(f"/api/ai/ask/{job_id}/events")
        assert "event: cancelled" in events.text

        conn = connect(settings)
        try:
            assert get(conn, job_id)["status"] == "cancelled"
        finally:
            conn.close()


def test_ai_rejects_non_loopback_before_auth_exists(tmp_path, monkeypatch):
    from opsintel import main
    from opsintel.ai_queue import AIQueueRunner

    monkeypatch.setattr(main.ollama, "status", ready_status)
    monkeypatch.setattr(AIQueueRunner, "run", idle_runner)
    settings = Settings(_env_file=None, opsintel_data_dir=tmp_path / "data", ai_enabled=True, api_host="0.0.0.0")
    with authenticated_client(settings) as client:
        response = client.post("/api/ai/ask", json={"question": "Where is logout handled?"})
        assert response.status_code == 503
        assert "non-local" in response.json()["detail"]


def test_ai_question_validation(client):
    assert client.post("/api/ai/ask", json={"question": "x"}).status_code == 422


def test_ai_can_be_disabled_per_user(tmp_path, monkeypatch):
    from opsintel import main
    from opsintel.ai_queue import AIQueueRunner

    monkeypatch.setattr(main.ollama, "status", ready_status)
    monkeypatch.setattr(AIQueueRunner, "run", idle_runner)
    settings = Settings(_env_file=None, opsintel_data_dir=tmp_path / "data", ai_enabled=True)
    source = tmp_path / "repo"
    source.mkdir()
    conn = connect(settings)
    migrate(conn)
    repo_id = register_local_repo(conn, "sample", source)
    conn.close()
    with authenticated_client(settings) as client:
        client.post("/api/admin/users", json={
            "username": "no-ai", "password": "another-password-123", "repo_ids": [repo_id],
            "ai_enabled": False,
        })
        client.post("/api/auth/logout")
        login = client.post("/api/auth/login", json={"username": "no-ai", "password": "another-password-123"})
        assert login.json()["user"]["ai_enabled"] is False
        client.headers["X-CSRF-Token"] = client.cookies.get("opsintel_csrf", "")

        response = client.post("/api/ai/ask", json={"question": "Where is logout handled?"})

        assert response.status_code == 403
        assert response.json()["detail"] == "AI assistance is disabled for this account"


def test_ai_daily_request_limit_is_enforced(tmp_path, monkeypatch):
    from opsintel import main
    from opsintel.ai_queue import AIQueueRunner

    monkeypatch.setattr(main.ollama, "status", ready_status)
    monkeypatch.setattr(AIQueueRunner, "run", idle_runner)
    settings = Settings(_env_file=None, opsintel_data_dir=tmp_path / "data", ai_enabled=True,
                        ai_daily_request_limit=1)
    source = tmp_path / "repo"
    source.mkdir()
    conn = connect(settings)
    migrate(conn)
    register_local_repo(conn, "sample", source)
    conn.close()
    with authenticated_client(settings) as client:
        first = client.post("/api/ai/ask", json={"question": "Where is logout handled?"})
        second = client.post("/api/ai/ask", json={"question": "How is logout implemented?"})

        assert first.status_code == 202
        assert second.status_code == 429
        assert "daily AI request limit reached (1)" in second.json()["detail"]


def test_ai_rejects_unknown_repository_scope(tmp_path, monkeypatch):
    from opsintel import main
    from opsintel.ai_queue import AIQueueRunner

    monkeypatch.setattr(main.ollama, "status", ready_status)
    monkeypatch.setattr(AIQueueRunner, "run", idle_runner)
    settings = Settings(_env_file=None, opsintel_data_dir=tmp_path / "data", ai_enabled=True)
    with authenticated_client(settings) as client:
        response = client.post("/api/ai/ask", json={"question": "A valid question", "repo_ids": [999]})
        assert response.status_code == 404


def test_serve_rejects_non_loopback_before_m5(monkeypatch):
    from opsintel import cli

    with pytest.raises(cli.typer.Exit) as exc:
        cli.serve(host="0.0.0.0")  # noqa: S104
    assert exc.value.exit_code == 2


def test_ai_queue_streams_validated_citations_and_reuses_cache(tmp_path, monkeypatch):
    from opsintel import ai_queue, jobs, main
    from opsintel.ai_queue import AIQueueRunner

    settings = Settings(_env_file=None, opsintel_data_dir=tmp_path / "data", ai_enabled=True)
    source = tmp_path / "repo"
    source.mkdir()
    write(source / "Auth.java", "class Auth {\n  validateAuthHeader(token);\n}\n")
    conn = connect(settings)
    migrate(conn)
    repo_id = register_local_repo(conn, "sample", source)
    LocalIndexer(conn, settings).index_repo(repo_id)
    conn.close()

    async def ready(*_args, **_kwargs):
        return {"reachable": True, "version": "0.10.0", "version_ok": True,
                "model_present": True, "model": settings.ollama_chat_model}

    monkeypatch.setattr(main.ollama, "status", ready)
    monkeypatch.setattr(AIQueueRunner, "run", idle_runner)
    runner = AIQueueRunner(settings)
    original_client = httpx.AsyncClient

    def fake_client(*, base_url, timeout):
        async def handler(request):
            prompt = json.loads(request.content)["messages"][-1]["content"]
            if "truncate this answer" in prompt:
                records = [
                    {"message": {"content": "Partial generated answer [E1]."}, "done": False},
                    {"done_reason": "length", "done": True},
                ]
            elif "truncate without citation" in prompt:
                records = [
                    {"message": {"content": "Partial uncited answer."}, "done": False},
                    {"done_reason": "length", "done": True},
                ]
            else:
                records = [
                    {"message": {"content": "The validation call is in Auth.java [E1]. "}, "done": False},
                    {"message": {"content": "An unverified claim [E99]."}, "done": True},
                ]
            content = "\n".join(json.dumps(record) for record in records)
            return httpx.Response(200, content=content, headers={"Content-Type": "application/x-ndjson"})

        return original_client(base_url=base_url, timeout=timeout, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai_queue.httpx, "AsyncClient", fake_client)

    def run_queued_job():
        worker_conn = connect(settings)
        try:
            job = jobs.lease(worker_conn, [ai_queue.AI_QUEUE], "test-ai-worker", settings.worker_lease_s)
            assert job is not None
            asyncio.run(runner._execute(worker_conn, "test-ai-worker", job))
            return jobs.get(worker_conn, job.id)
        finally:
            worker_conn.close()

    with authenticated_client(settings) as client:
        first = client.post("/api/ai/ask", json={"question": "Where is validateAuthHeader?", "repo_ids": [repo_id]})
        assert first.status_code == 202
        first_job = run_queued_job()
        assert first_job["status"] == "done"
        stream = client.get(first.json()["events_url"])
        assert stream.status_code == 200 and "event: token" in stream.text and "event: done" in stream.text
        assert "[E99]" not in stream.text
        done = next(
            line[6:] for line in stream.text.splitlines()
            if line.startswith("data: ") and '"citations"' in line
        )
        result = json.loads(done)
        assert result["citations"][0]["path"] == "Auth.java"
        assert result["citations"][0]["location"]["line"] == 2
        assert result["citation_warning"] == "Unknown citation IDs were removed."

        second = client.post("/api/ai/ask", json={"question": "Where is validateAuthHeader?", "repo_ids": [repo_id]})
        second_job = run_queued_job()
        assert second_job["status"] == "done"
        cached_stream = client.get(second.json()["events_url"])
        cached_done = next(line[6:] for line in cached_stream.text.splitlines()
                           if line.startswith("data: ") and '"cached"' in line)
        assert json.loads(cached_done)["cached"] is True

        third = client.post("/api/ai/ask", json={
            "question": "Where is validateAuthHeader? truncate this answer deliberately",
            "repo_ids": [repo_id],
        })
        truncated_job = run_queued_job()
        assert truncated_job["status"] == "done"
        truncated_result = json.loads(truncated_job["result"])
        assert truncated_result["answer"] == "Partial generated answer [E1]."
        assert [citation["path"] for citation in truncated_result["citations"]] == ["Auth.java"]
        assert "may be incomplete" in truncated_result["citation_warning"]
        truncated_stream = client.get(third.json()["events_url"])
        assert "Partial generated answer [E1]." in truncated_stream.text

        fourth = client.post("/api/ai/ask", json={
            "question": "Where is validateAuthHeader? truncate without citation",
            "repo_ids": [repo_id],
        })
        uncited_job = run_queued_job()
        uncited_result = json.loads(uncited_job["result"])
        assert uncited_result["answer"] == "Partial uncited answer."
        assert [citation["path"] for citation in uncited_result["citations"]] == ["Auth.java"]
        assert "not individually cited" in uncited_result["citation_warning"]
        assert "may be incomplete" in uncited_result["citation_warning"]
        uncited_stream = client.get(fourth.json()["events_url"])
        assert "Partial uncited answer" in uncited_stream.text
