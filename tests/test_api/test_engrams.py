"""Tests for engram API endpoints."""

import pytest
from httpx import AsyncClient

from tests.test_api.conftest import insert_engram


@pytest.mark.asyncio
class TestListEngrams:
    async def test_empty_returns_paginated(self, client: AsyncClient):
        resp = await client.get("/api/engrams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_with_data(self, client: AsyncClient, app):
        db = app.state.db
        await insert_engram(db, "entity one")
        await insert_engram(db, "entity two")

        resp = await client.get("/api/engrams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    async def test_pagination(self, client: AsyncClient, app):
        db = app.state.db
        for i in range(3):
            await insert_engram(db, f"entity {i}")

        resp = await client.get("/api/engrams", params={"offset": 1, "limit": 1})
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 1


@pytest.mark.asyncio
class TestGetEngram:
    async def test_returns_detail(self, client: AsyncClient, app):
        engram_id = await insert_engram(app.state.db, "detail entity")

        resp = await client.get(f"/api/engrams/{engram_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == engram_id
        assert "edges" in data
        assert "documents" in data

    async def test_not_found_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/engrams/nonexistent")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestGetEngramCluster:
    async def test_returns_documents(self, client: AsyncClient, app):
        db = app.state.db
        create_resp = await client.post("/api/documents/scribbles", json={"text": "Cluster test"})
        doc_id = create_resp.json()["id"]
        engram_id = await insert_engram(db, "cluster entity")
        await db.execute(
            "INSERT INTO document_engrams (document_id, engram_id) VALUES (?, ?)",
            (doc_id, engram_id),
        )
        await db.commit()

        resp = await client.get(f"/api/engrams/{engram_id}/cluster")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == doc_id

    async def test_not_found_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/engrams/nonexistent/cluster")
        assert resp.status_code == 404

    async def test_empty_cluster(self, client: AsyncClient, app):
        engram_id = await insert_engram(app.state.db, "lonely entity")
        resp = await client.get(f"/api/engrams/{engram_id}/cluster")
        assert resp.status_code == 200
        assert resp.json() == []
