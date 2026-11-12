import asyncio
import json

import httpx
import pytest

from opsintel import embeddings
from opsintel.embeddings import EmbeddingError, cache_embeddings, embed_texts, get_cached_embedding, index_embeddings
from opsintel.indexing import LocalIndexer, register_local_repo
from tests.conftest import write


def test_embedding_cache_uses_model_and_text_hash(conn):
    cache_embeddings(conn, "embed-model-a", ["first", "second"], [[1.0, 0.0], [0.0, 1.0]])

    assert get_cached_embedding(conn, "embed-model-a", "first") == [1.0, 0.0]
    assert get_cached_embedding(conn, "embed-model-a", "second") == [0.0, 1.0]
    assert get_cached_embedding(conn, "embed-model-b", "first") is None
    assert get_cached_embedding(conn, "embed-model-a", "changed") is None


def test_embed_texts_posts_batch_to_ollama(monkeypatch):
    original_client = httpx.AsyncClient

    def fake_client(*, base_url, timeout):
        async def handler(request):
            assert request.url.path == "/api/embed"
            assert json.loads(request.content) == {"model": "embed-model", "input": ["alpha", "beta"]}
            return httpx.Response(200, json={"embeddings": [[1, 0], [0, 1]]})

        return original_client(base_url=base_url, timeout=timeout, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    vectors = asyncio.run(embed_texts("http://localhost:11434/", "embed-model", ["alpha", "beta"]))

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


def test_embed_texts_rejects_bad_response(monkeypatch):
    original_client = httpx.AsyncClient

    def fake_client(*, base_url, timeout):
        async def handler(_request):
            return httpx.Response(200, json={"embeddings": [[1, 0], [0, 1, 2]]})

        return original_client(base_url=base_url, timeout=timeout, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    with pytest.raises(EmbeddingError, match="inconsistent dimensions"):
        asyncio.run(embed_texts("http://localhost:11434", "embed-model", ["alpha", "beta"]))


def test_embed_texts_requires_an_explicit_model():
    with pytest.raises(EmbeddingError, match="OLLAMA_EMBED_MODEL"):
        asyncio.run(embed_texts("http://localhost:11434", "", ["alpha"]))


def test_index_embeddings_batches_missing_text_and_reuses_cache(conn, settings, repo_dir, monkeypatch):
    write(repo_dir / "one.txt", "embedding marker one")
    write(repo_dir / "two.txt", "embedding marker two")
    LocalIndexer(conn, settings).index_repo(register_local_repo(conn, "embeddings", repo_dir))
    calls = []

    async def fake_embed(_base_url, model, texts, _timeout_s):
        calls.append((model, texts))
        return [[float(len(text)), 1.0] for text in texts]

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed)
    first = asyncio.run(index_embeddings(conn, "http://localhost:11434", "test-embed", batch_size=1))
    second = asyncio.run(index_embeddings(conn, "http://localhost:11434", "test-embed", batch_size=1))

    assert first["embedded"] == 2 and first["cached"] == 0
    assert second["embedded"] == 0 and second["cached"] == 2
    assert len(calls) == 2
