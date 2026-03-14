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
    async def test_empty_returns_list(self, client: AsyncClient):
        resp = await client.get("/api/documents")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_recent_documents(self, client: AsyncClient):
        for i in range(3):
            await client.post("/api/documents/scribbles", json={"text": f"Doc {i}"})

        resp = await client.get("/api/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        # Each doc should have engrams list
        assert "engrams" in data[0]

    async def test_excludes_drafts(self, client: AsyncClient):
        await client.post("/api/documents/scribbles", json={"text": "Normal doc"})
        await client.post("/api/documents/scribbles", json={"text": "Draft doc", "draft": True})

        resp = await client.get("/api/documents")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["text"] == "Normal doc"

    async def test_days_param(self, client: AsyncClient):
        await client.post("/api/documents/scribbles", json={"text": "Recent doc"})
        resp = await client.get("/api/documents", params={"days": 1})
        assert resp.status_code == 200
        assert len(resp.json()) == 1


@pytest.mark.asyncio
class TestDrafts:
    async def test_create_draft(self, client: AsyncClient):
        resp = await client.post(
            "/api/documents/scribbles", json={"text": "My draft", "draft": True}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["processed"] == 0

    async def test_list_drafts(self, client: AsyncClient):
        await client.post("/api/documents/scribbles", json={"text": "Draft 1", "draft": True})
        await client.post("/api/documents/scribbles", json={"text": "Draft 2", "draft": True})
        await client.post("/api/documents/scribbles", json={"text": "Normal"})

        resp = await client.get("/api/documents/drafts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2


@pytest.mark.asyncio
class TestDocumentCount:
    async def test_count_excludes_drafts(self, client: AsyncClient):
        await client.post("/api/documents/scribbles", json={"text": "Normal"})
        await client.post("/api/documents/scribbles", json={"text": "Draft", "draft": True})

        resp = await client.get("/api/documents/count")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


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


@pytest.mark.asyncio
class TestUpdateDocument:
    async def test_update_text(self, client: AsyncClient):
        create_resp = await client.post("/api/documents/scribbles", json={"text": "Original text"})
        doc_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/documents/{doc_id}", json={"text": "Updated text"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Updated text"
        assert data["processed"] == 0

    async def test_update_title(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/documents/scribbles", json={"text": "Some text", "title": "Old"}
        )
        doc_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/documents/{doc_id}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    async def test_update_not_found(self, client: AsyncClient):
        resp = await client.patch("/api/documents/nonexistent", json={"text": "new"})
        assert resp.status_code == 404

    async def test_update_empty_body(self, client: AsyncClient):
        create_resp = await client.post("/api/documents/scribbles", json={"text": "text"})
        doc_id = create_resp.json()["id"]

        resp = await client.patch(f"/api/documents/{doc_id}", json={})
        assert resp.status_code == 400

    async def test_new_document_has_revision_1(self, client: AsyncClient):
        create_resp = await client.post("/api/documents/scribbles", json={"text": "Test"})
        assert create_resp.status_code == 201
        assert create_resp.json()["revision"] == 1

    async def test_update_increments_revision(self, client: AsyncClient):
        create_resp = await client.post("/api/documents/scribbles", json={"text": "Original"})
        doc_id = create_resp.json()["id"]

        resp1 = await client.patch(f"/api/documents/{doc_id}", json={"text": "Update 1"})
        assert resp1.json()["revision"] == 2

        resp2 = await client.patch(f"/api/documents/{doc_id}", json={"text": "Update 2"})
        assert resp2.json()["revision"] == 3

    async def test_update_clears_associations(self, client: AsyncClient, app):
        """Verify document_engrams and document_embeddings are cleared on update."""
        create_resp = await client.post("/api/documents/scribbles", json={"text": "Test"})
        doc_id = create_resp.json()["id"]

        # Insert fake associations
        db = app.state.db
        await db.execute(
            "INSERT OR IGNORE INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
            ("fake-engram-id", "fake", "fakehash"),
        )
        await db.execute(
            "INSERT OR IGNORE INTO document_engrams (document_id, engram_id) VALUES (?, ?)",
            (doc_id, "fake-engram-id"),
        )
        await db.commit()

        # Update should clear them
        resp = await client.patch(f"/api/documents/{doc_id}", json={"text": "Updated"})
        assert resp.status_code == 200

        cursor = await db.execute(
            "SELECT COUNT(*) FROM document_engrams WHERE document_id = ?", (doc_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == 0
