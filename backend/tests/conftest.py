from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opsintel.config import Settings
from opsintel.db import connect, migrate
from opsintel.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, opsintel_data_dir=tmp_path / "data", ai_enabled=False, chunk_lines=10)


@pytest.fixture
def conn(settings: Settings):
    c = connect(settings)
    migrate(c)
    yield c
    c.close()


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    return d


@pytest.fixture
def client(settings: Settings):
    with authenticated_client(settings) as c:
        yield c


@contextmanager
def authenticated_client(settings: Settings):
    with TestClient(create_app(settings), client=("127.0.0.1", 49152)) as c:
        response = c.post("/api/auth/bootstrap", json={"username": "test-admin", "password": "test-password-123"})
        assert response.status_code == 201
        c.headers.update({"X-CSRF-Token": c.cookies.get("opsintel_csrf", "")})
        yield c


def write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode("utf-8")
    path.write_bytes(content)
    return path
