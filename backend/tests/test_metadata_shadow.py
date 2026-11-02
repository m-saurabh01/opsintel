from pathlib import Path

from fastapi.testclient import TestClient

from opsintel.ai_queue import retrieve
from opsintel.config import Settings
from opsintel.db import connect, migrate
from opsintel.experiments.metadata_search import MetadataShadowIndex
from opsintel.indexing import LocalIndexer, register_local_repo
from opsintel.main import create_app
from opsintel.search import SearchRequest, search
from tests import doc_fixtures as fx
from tests.conftest import write


def test_shadow_metadata_search_finds_csv_and_xlsx_headers_without_changing_live_fts(
    conn, settings, repo_dir: Path, tmp_path: Path,
):
    write(repo_dir / "data" / "aircraft.csv", "tail_number,model\nVT-ABC,A320neo\n")
    write(repo_dir / "data" / "fleet.xlsx", fx.make_xlsx())
    repo_id = register_local_repo(conn, "metadata-demo", repo_dir)
    LocalIndexer(conn, settings).index_repo(repo_id)

    live_before = search(conn, SearchRequest(q="File with tail number", repo_ids=[repo_id]))
    shadow = MetadataShadowIndex(tmp_path / "experimental" / "metadata-shadow.db")
    try:
        stats = shadow.refresh(conn, repo_id)
        result = shadow.search("File with tail number", repo_id=repo_id)
    finally:
        shadow.close()

    assert stats["chunks_refreshed"] > 0
    assert {item["path"] for item in result["results"]} == {
        "data/aircraft.csv", "data/fleet.xlsx",
    }
    by_path = {item["path"]: item for item in result["results"]}
    assert by_path["data/aircraft.csv"]["location"]["column"] == "tail_number"
    assert by_path["data/fleet.xlsx"]["location"]["cell"] == "A1"
    assert by_path["data/fleet.xlsx"]["location"]["header"] == "tail_number"

    live_after = search(conn, SearchRequest(q="File with tail number", repo_ids=[repo_id]))
    assert live_after == live_before


def test_opt_in_metadata_api_and_ai_retrieval(tmp_path: Path):
    settings = Settings(_env_file=None, opsintel_data_dir=tmp_path / "app-data", ai_enabled=False)
    source = tmp_path / "repo"
    source.mkdir()
    write(source / "aircraft.csv", "tail_number,model\nVT-ABC,A320neo\n")
    write(source / "fleet.xlsx", fx.make_xlsx())
    conn = connect(settings)
    migrate(conn)
    repo_id = register_local_repo(conn, "metadata-demo", source)
    LocalIndexer(conn, settings).index_repo(repo_id)
    shadow = MetadataShadowIndex(settings.metadata_search_path)
    try:
        shadow.refresh(conn, repo_id)
    finally:
        shadow.close()

    with TestClient(create_app(settings)) as client:
        disabled = client.get("/api/search", params={"q": "File with tail number", "mode": "metadata"})
        assert disabled.status_code == 503
        assert client.get("/api/search", params={"q": "File with tail number"}).json()["total"] == 0

        settings.metadata_search_enabled = True
        response = client.get("/api/search", params={
            "q": "File with tail number", "mode": "metadata", "repo": repo_id,
        })
        assert response.status_code == 200
        results = {item["path"]: item for item in response.json()["results"]}
        assert set(results) == {"aircraft.csv", "fleet.xlsx"}
        assert results["fleet.xlsx"]["location"]["cell"] == "A1"

        evidence = retrieve(conn, "File with tail number", [repo_id], settings)
        assert {item["path"] for item in evidence} == {"aircraft.csv", "fleet.xlsx"}
    conn.close()
