"""Tests for visualization stub endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestVizEndpoints:
    async def test_projections_returns_empty(self, client: AsyncClient):
        resp = await client.get("/api/viz/projections")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_clusters_returns_empty(self, client: AsyncClient):
        resp = await client.get("/api/viz/clusters")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_gaps_returns_empty(self, client: AsyncClient):
        resp = await client.get("/api/viz/gaps")
        assert resp.status_code == 200
        assert resp.json() == []
