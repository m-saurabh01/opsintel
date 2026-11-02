"""Integration tests against a real Gitea. Run with: OPSINTEL_LIVE_GITEA_REPO=owner/name uv run pytest -m live"""

import os

import pytest

from opsintel.config import Settings
from opsintel.gitea import GiteaClient
from opsintel.search import SearchRequest, search
from opsintel.sync import GiteaSyncer, register_gitea_repo

LIVE_REPO = os.environ.get("OPSINTEL_LIVE_GITEA_REPO")
pytestmark = [pytest.mark.live, pytest.mark.skipif(not LIVE_REPO, reason="OPSINTEL_LIVE_GITEA_REPO not set")]


def test_sync_real_gitea_repository(tmp_path, conn):
    env = Settings()  # reads GITEA_URL / GITEA_TOKEN from .env
    settings = Settings(_env_file=None, opsintel_data_dir=tmp_path / "data", ai_enabled=False,
                        gitea_url=env.gitea_url, gitea_token=env.gitea_token)
    with GiteaClient(settings) as g:
        repo = g.get_repo(LIVE_REPO)
    repo_id = register_gitea_repo(conn, repo)
    stats = GiteaSyncer(conn, settings).sync(repo_id, repo.default_branch)
    assert stats.indexed > 0 and stats.failed == 0
    assert GiteaSyncer(conn, settings).sync(repo_id, repo.default_branch).indexed == 0
    assert search(conn, SearchRequest(q="README"))["total"] >= 0
