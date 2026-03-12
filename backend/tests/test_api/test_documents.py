"""Tests for document API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestCreateScribble:
    async def test_returns_201_with_document(self, client: AsyncClient):
        resp = await client.post("/api/documents/scribbles", json={"text": "Hello world"})
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["text"] == "Hello world"
        assert data["source_type"] == "scribble"

    async def test_with_title(self, client: AsyncClient):
        resp = await client.post(
            "/api/documents/scribbles", json={"text": "Some text", "title": "My Title"}
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "My Title"

    async def test_empty_text_returns_400(self, client: AsyncClient):
        resp = await client.post("/api/documents/scribbles", json={"text": "   "})
        assert resp.status_code == 400

    async def test_metadata_is_json_object(self, client: AsyncClient):
        resp = await client.post("/api/documents/scribbles", json={"text": "Test"})
        assert resp.status_code == 201
        data = resp.json()
        # metadata should be null (not the string "null")
        assert data["metadata"] is None


@pytest.mark.asyncio
class TestUploadFile:
    async def test_upload_md_returns_201(self, client: AsyncClient):
        content = b"# Hello\n\nSome markdown content."
        resp = await client.post(
            "/api/documents/files",
            files={"file": ("test.md", content, "text/markdown")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["mime_type"] == "text/markdown"
        assert data["source_type"] == "file"

    async def test_unsupported_format_returns_400(self, client: AsyncClient):
        resp = await client.post(
            "/api/documents/files",
            files={"file": ("test.xyz", b"data", "application/octet-stream")},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestListDocuments:
    async def test_empty_returns_paginated(self, client: AsyncClient):
        resp = await client.get("/api/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"items": [], "total": 0, "offset": 0, "limit": 20}

    async def test_pagination(self, client: AsyncClient):
        # Create 3 documents
        for i in range(3):
            await client.post("/api/documents/scribbles", json={"text": f"Doc {i}"})

        resp = await client.get("/api/documents", params={"offset": 1, "limit": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["offset"] == 1
        assert data["limit"] == 1
        assert len(data["items"]) == 1

    async def test_default_limit(self, client: AsyncClient):
        resp = await client.get("/api/documents")
        assert resp.json()["limit"] == 20


@pytest.mark.asyncio
class TestGetDocument:
    async def test_returns_detail_with_engrams(self, client: AsyncClient):
        create_resp = await client.post("/api/documents/scribbles", json={"text": "Test doc"})
        doc_id = create_resp.json()["id"]

        resp = await client.get(f"/api/documents/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == doc_id
        assert "engrams" in data
        assert isinstance(data["engrams"], list)

    async def test_not_found_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/documents/nonexistent")
        assert resp.status_code == 404
