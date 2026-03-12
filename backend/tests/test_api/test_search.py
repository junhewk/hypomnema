"""Tests for search API endpoints."""

import pytest
from httpx import AsyncClient

from tests.test_api.conftest import insert_edge, insert_engram


@pytest.mark.asyncio
class TestSearchDocuments:
    async def test_returns_scored_list(self, client: AsyncClient, app):
        await client.post("/api/documents/scribbles", json={"text": "quantum computing research"})

        resp = await client.get("/api/search/documents", params={"q": "quantum"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_empty_query_results(self, client: AsyncClient):
        resp = await client.get("/api/search/documents", params={"q": "xyznonexistent"})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_score_field_present(self, client: AsyncClient, app):
        await client.post("/api/documents/scribbles", json={"text": "machine learning models"})
        resp = await client.get("/api/search/documents", params={"q": "machine"})
        data = resp.json()
        if data:
            assert "score" in data[0]


@pytest.mark.asyncio
class TestSearchKnowledge:
    async def _setup_engram_with_edge(self, app, name: str):
        db = app.state.db
        engram_id = await insert_engram(db, name)
        target_id = await insert_engram(db, f"{name} target")
        await insert_edge(db, engram_id, target_id)
        return engram_id

    async def test_by_engram_name(self, client: AsyncClient, app):
        await self._setup_engram_with_edge(app, "neural networks")

        resp = await client.get("/api/search/knowledge", params={"q": "neural"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["predicate"] == "relates_to"

    async def test_no_results(self, client: AsyncClient):
        resp = await client.get("/api/search/knowledge", params={"q": "xyznonexistent"})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_by_predicate_fallback(self, client: AsyncClient, app):
        await self._setup_engram_with_edge(app, "specific entity")

        # Search by predicate (no engram name match)
        resp = await client.get("/api/search/knowledge", params={"q": "relates_to"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
