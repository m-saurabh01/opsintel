import asyncio

import pytest

from opsintel import embeddings, hybrid
from opsintel.embeddings import embedding_prefixes, index_embeddings
from opsintel.hybrid import SemanticUnavailable, fuse, hybrid_search, vector_candidates
from opsintel.indexing import LocalIndexer, register_local_repo
from opsintel.search import SearchRequest
from tests.conftest import write


def keyword_vector(text):
    return [1.0, 0.0] if "tail" in text else [0.0, 1.0]


@pytest.fixture
def semantic(conn, settings, repo_dir, monkeypatch):
    write(repo_dir / "fleet.csv", "tail_number,model\nVT-ABC,A320neo\n")
    write(repo_dir / "styles.css", "button:hover { color: red; }\n")
    write(repo_dir / "notes.txt", "file with tail number noted in the handbook\n")
    repo_id = register_local_repo(conn, "sem", repo_dir)
    LocalIndexer(conn, settings).index_repo(repo_id)
    settings.semantic_search_enabled = True
    settings.ollama_embed_model = "test-embed"

    async def fake_embed(_url, _model, texts, _timeout):
        return [keyword_vector(text) for text in texts]

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)
    monkeypatch.setattr(hybrid, "embed_query", lambda _url, _model, query, *_: tuple(keyword_vector(query)))
    asyncio.run(index_embeddings(conn, settings.ollama_base_url, "test-embed"))
    return repo_id


def test_fuse_rewards_agreement_between_rankings():
    scores = fuse({"lexical": [1, 2], "semantic": [2, 3]})
    assert max(scores, key=scores.get) == 2


def test_query_term_highlighting_respects_word_and_identifier_boundaries():
    from opsintel.terms import terms_pattern

    pattern = terms_pattern(["port", "maintenance", "forecast"])
    assert [match.group() for match in pattern.finditer("port and import")] == ["port"]
    assert [match.group() for match in pattern.finditer("maintenanceForecast")] == [
        "maintenance", "Forecast",
    ]
    assert pattern.search("tail_number") is None


def test_smart_search_orders_word_matches_before_substrings(conn, settings, repo_dir):
    write(repo_dir / "port_config.py", "port = 8080\n")
    write(repo_dir / "imports.py", "import csv\n")
    repo_id = register_local_repo(conn, "ports", repo_dir)
    LocalIndexer(conn, settings).index_repo(repo_id)
    settings.semantic_search_enabled = False

    result = hybrid_search(conn, SearchRequest(q="port"), settings)

    assert [hit["path"] for hit in result["results"][:2]] == ["port_config.py", "imports.py"]
    assert result["results"][0]["match_type"] == "match"
    assert result["results"][1]["match_type"] == "substring"
    assert result["results"][1]["preview"][0]["highlights"]


def test_metadata_backfill_restores_identifier_projection(conn, settings, repo_dir):
    from opsintel.search_metadata import backfill_search_metadata

    write(repo_dir / "fleet.csv", "tail_number,model\nVT-ABC,A320neo\n")
    repo_id = register_local_repo(conn, "metadata-backfill", repo_dir)
    LocalIndexer(conn, settings).index_repo(repo_id)
    conn.execute("UPDATE chunks SET search_metadata = ''")

    assert backfill_search_metadata(conn) == 1
    result = hybrid_search(conn, SearchRequest(q="tail number", repo_ids=[repo_id]), settings)
    assert result["results"][0]["path"] == "fleet.csv"


def test_semantic_search_ranks_by_similarity(conn, settings, semantic):
    result = hybrid_search(conn, SearchRequest(q="aircraft tail"), settings, semantic_only=True)
    assert result["mode"] == "semantic"
    assert {hit["path"] for hit in result["results"][:2]} == {"fleet.csv", "notes.txt"}
    assert all(hit["sources"] == ["semantic"] for hit in result["results"])


def test_hybrid_combines_lexical_and_semantic_hits(conn, settings, semantic):
    result = hybrid_search(conn, SearchRequest(q="file with tail number"), settings)
    paths = [hit["path"] for hit in result["results"]]
    assert paths[0] == "notes.txt" and set(result["results"][0]["sources"]) == \
        {"lexical", "metadata", "semantic"}
    by_path = {hit["path"]: hit for hit in result["results"]}
    assert by_path["fleet.csv"]["sources"] == ["metadata", "semantic"]
    assert by_path["fleet.csv"]["location"]["kind"] == "row"


def test_semantic_candidates_respect_filters(conn, settings, semantic):
    only_css = vector_candidates(conn, SearchRequest(q="tail", path_prefix="styles"), settings)
    assert len(only_css) == 1


def test_semantic_requires_cached_embeddings_for_the_model(conn, settings, semantic):
    settings.ollama_embed_model = "another-model"
    with pytest.raises(SemanticUnavailable, match="embedding-index"):
        vector_candidates(conn, SearchRequest(q="tail"), settings)


def test_nomic_models_get_task_prefixes(conn, settings, repo_dir, monkeypatch):
    assert embedding_prefixes("nomic-embed-text") == ("search_query: ", "search_document: ")
    assert embedding_prefixes("opsintel-embed") == ("", "")
    write(repo_dir / "a.txt", "prefix check")
    LocalIndexer(conn, settings).index_repo(register_local_repo(conn, "prefix", repo_dir))
    sent = []

    async def capture(_url, _model, texts, _timeout):
        sent.extend(texts)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(embeddings, "embed_texts", capture)
    asyncio.run(index_embeddings(conn, "http://localhost:11434", "nomic-embed-text"))
    assert sent == ["search_document: prefix check"]


def test_semantic_modes_are_disabled_by_default(client):
    assert client.get("/api/health").json()["features"]["semantic_search"] is False
    assert client.get("/api/search", params={"q": "tail number", "mode": "hybrid"}).status_code == 503
    assert client.get("/api/search", params={"q": "tail number", "mode": "semantic"}).status_code == 503
    assert client.get("/api/search", params={"q": "tail number"}).status_code == 200


def test_smart_search_falls_back_when_embeddings_are_not_indexed(client, conn, settings, repo_dir):
    write(repo_dir / "auth.py", "validate_token()\n")
    repo_id = register_local_repo(conn, "fallback", repo_dir)
    LocalIndexer(conn, settings).index_repo(repo_id)
    settings.semantic_search_enabled = True
    settings.ollama_embed_model = "missing-model"

    response = client.get("/api/search", params={"q": "validate_token", "repo": repo_id})

    assert response.status_code == 200
    assert response.json()["results"][0]["path"] == "auth.py"


def test_hybrid_api_returns_the_standard_result_contract(client, semantic):
    assert client.get("/api/health").json()["features"]["semantic_search"] is True
    body = client.get("/api/search", params={"q": "file with tail number", "mode": "hybrid"}).json()
    assert body["mode"] == "hybrid"
    first = body["results"][0]
    assert first["path"] == "notes.txt"
    assert {"chunk_id", "file_id", "repo", "location", "preview", "score", "sources"} <= set(first)
    assert client.get("/api/search", params={"q": "!!!", "mode": "hybrid"}).status_code == 400
    unified = client.get("/api/search", params={"q": "file with tail number"}).json()
    assert unified["mode"] == "smart"
    assert {"match_total", "related_total", "substring_total"} <= set(unified)


def test_assistant_retrieval_uses_integrated_metadata_without_shadow_index(conn, settings, semantic):
    from opsintel.ai_queue import retrieve

    settings.semantic_search_enabled = False
    settings.metadata_search_enabled = True
    evidence = retrieve(conn, "csv column listing the aircraft tail", [semantic], settings)

    assert "fleet.csv" in {item["path"] for item in evidence}


def test_evaluation_reports_rank_metrics_per_mode(conn, settings, semantic):
    from opsintel.evaluation import evaluate

    queries = [{"q": "file with tail number", "expect": ["notes.txt"]}]
    summary = evaluate(conn, settings, queries, [semantic], modes=("fulltext", "hybrid"))

    assert summary["hybrid"]["mrr"] == 1.0 and summary["hybrid"]["hit@1"] == 1.0
    assert summary["fulltext"]["queries"] == 1


def test_worker_embeds_new_chunks_without_failing_the_job(settings, monkeypatch):
    from opsintel import worker as worker_module
    from opsintel.worker import Worker

    settings.semantic_search_enabled = True
    settings.ollama_embed_model = "test-embed"
    calls = []

    async def fake_index(_conn, _url, model, repo_ids, **_kwargs):
        calls.append((model, repo_ids))
        return {"embedded": 3}

    monkeypatch.setattr(worker_module, "index_embeddings", fake_index)
    w = Worker(settings)
    try:
        stats = {"chunks_written": 5}
        w._embed_new_chunks(7, stats)
        assert calls == [("test-embed", [7])] and stats["embedded"] == 3

        w._embed_new_chunks(7, {"chunks_written": 0})
        assert len(calls) == 1

        async def failing(*_args, **_kwargs):
            raise RuntimeError("ollama down")

        monkeypatch.setattr(worker_module, "index_embeddings", failing)
        w._embed_new_chunks(7, {"chunks_written": 1})
    finally:
        w.close()
