"""Tests for feed API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestCreateFeed:
    async def test_returns_201(self, client: AsyncClient):
        resp = await client.post(
            "/api/feeds",
            json={"name": "Test RSS", "feed_type": "rss", "url": "https://example.com/feed"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test RSS"
        assert data["feed_type"] == "rss"
        assert data["active"] is True

    async def test_invalid_type_returns_400(self, client: AsyncClient):
        resp = await client.post(
            "/api/feeds",
            json={"name": "Bad", "feed_type": "invalid", "url": "https://example.com"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestListFeeds:
    async def test_empty(self, client: AsyncClient):
        resp = await client.get("/api/feeds")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_with_data(self, client: AsyncClient):
        await client.post(
            "/api/feeds",
            json={"name": "Feed 1", "feed_type": "rss", "url": "https://example.com/1"},
        )
        await client.post(
            "/api/feeds",
            json={"name": "Feed 2", "feed_type": "rss", "url": "https://example.com/2"},
        )

        resp = await client.get("/api/feeds")
        assert len(resp.json()) == 2


@pytest.mark.asyncio
class TestUpdateFeed:
    async def test_partial_update(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/feeds",
            json={"name": "Original", "feed_type": "rss", "url": "https://example.com"},
        )
        feed_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/feeds/{feed_id}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    async def test_not_found_returns_404(self, client: AsyncClient):
        resp = await client.patch("/api/feeds/nonexistent", json={"name": "X"})
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestDeleteFeed:
    async def test_returns_204(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/feeds",
            json={"name": "ToDelete", "feed_type": "rss", "url": "https://example.com"},
        )
        feed_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/feeds/{feed_id}")
        assert resp.status_code == 204

    async def test_not_found_returns_404(self, client: AsyncClient):
        resp = await client.delete("/api/feeds/nonexistent")
        assert resp.status_code == 404
