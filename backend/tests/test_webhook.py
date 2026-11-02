import hashlib
import hmac
import json

import pytest
from pydantic import SecretStr

from opsintel.db import connect, migrate
from opsintel.gitea import GiteaRepo
from opsintel.sync import register_gitea_repo

SECRET = "test-secret"


@pytest.fixture
def webhook_settings(settings):
    settings.gitea_webhook_secret = SecretStr(SECRET)
    conn = connect(settings)
    migrate(conn)
    register_gitea_repo(conn, GiteaRepo(id=7, full_name="acme/app", clone_url="http://x/acme/app.git",
                                        default_branch="main", private=False, empty=False, archived=False))
    conn.close()
    return settings


def post(client, payload, delivery="d1", secret=SECRET, event="push"):
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/webhooks/gitea", content=body, headers={
        "X-Gitea-Event": event, "X-Gitea-Delivery": delivery, "X-Gitea-Signature": sig,
        "Content-Type": "application/json",
    })


PUSH = {"ref": "refs/heads/main", "repository": {"id": 7, "full_name": "acme/app"}}


def test_push_enqueues_once_per_delivery(webhook_settings, client):
    first = post(client, PUSH).json()
    assert first["status"] == "queued"
    assert post(client, PUSH).json()["status"] == "duplicate"
    second = post(client, PUSH, delivery="d2").json()
    assert second == {"status": "already_queued", "job_id": first["job_id"]}


def test_rejects_bad_signature_and_missing_secret(webhook_settings, client):
    assert post(client, PUSH, secret="wrong").status_code == 401
    webhook_settings.gitea_webhook_secret = SecretStr("")
    assert post(client, PUSH).status_code == 503


def test_ignores_untracked_branch_unknown_repo_and_other_events(webhook_settings, client):
    assert post(client, {**PUSH, "ref": "refs/heads/dev"}).json()["status"] == "ignored"
    assert post(client, {**PUSH, "ref": "refs/tags/v1"}).json()["status"] == "ignored"
    assert post(client, {**PUSH, "repository": {"id": 99}}).json()["status"] == "ignored"
    assert post(client, PUSH, event="issues").json()["status"] == "ignored"
    assert client.get("/api/admin/status").json()["jobs"]["queues"] == {}
