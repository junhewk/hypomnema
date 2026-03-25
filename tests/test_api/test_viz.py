"""Tests for visualization API endpoints."""

import pytest
from httpx import AsyncClient

from tests.conftest import insert_engram_with_embedding, make_embedding

_has_projection_deps = True
try:
    import sklearn  # noqa: F401
    import umap  # noqa: F401
except ImportError:
    _has_projection_deps = False

_skip_no_projection = pytest.mark.skipif(
    not _has_projection_deps, reason="umap-learn / scikit-learn not installed"
)


async def _seed_engrams(app: object, count: int = 20) -> list[str]:
    db = app.state.db  # type: ignore[attr-defined]
    ids = []
    for i in range(count):
        eid = await insert_engram_with_embedding(db, f"viz_entity_{i}", make_embedding(i))
        ids.append(eid)
    return ids


@pytest.mark.asyncio
class TestVizProjections:
    async def test_empty_returns_list(self, client: AsyncClient) -> None:
        resp = await client.get("/api/viz/projections")
        assert resp.status_code == 200
        assert resp.json() == []

    @_skip_no_projection
    async def test_after_recompute(self, client: AsyncClient, app: object) -> None:
        await _seed_engrams(app, 20)
        await client.post("/api/viz/recompute")
        resp = await client.get("/api/viz/projections")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 20
        assert "x" in data[0]
        assert "y" in data[0]
        assert "z" in data[0]


@pytest.mark.asyncio
class TestVizClusters:
    async def test_empty_returns_list(self, client: AsyncClient) -> None:
        resp = await client.get("/api/viz/clusters")
        assert resp.status_code == 200
        assert resp.json() == []

    @_skip_no_projection
    async def test_after_recompute(self, client: AsyncClient, app: object) -> None:
        await _seed_engrams(app, 20)
        await client.post("/api/viz/recompute")
        resp = await client.get("/api/viz/clusters")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
class TestVizGaps:
    async def test_empty_returns_list(self, client: AsyncClient) -> None:
        resp = await client.get("/api/viz/gaps")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.asyncio
class TestVizEdges:
    async def test_get_edges(self, client: AsyncClient) -> None:
        resp = await client.get("/api/viz/edges")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


@pytest.mark.asyncio
class TestRecompute:
    @_skip_no_projection
    async def test_returns_projections(self, client: AsyncClient, app: object) -> None:
        await _seed_engrams(app, 20)
        resp = await client.post("/api/viz/recompute")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 20

    async def test_too_few_engrams(self, client: AsyncClient, app: object) -> None:
        await _seed_engrams(app, 1)
        resp = await client.post("/api/viz/recompute")
        assert resp.status_code == 200
        assert resp.json() == []
