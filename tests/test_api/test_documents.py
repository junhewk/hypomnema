"""Tests for document API endpoints."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import hypomnema.ontology.linker as linker_mod
from hypomnema.ontology.extractor import DEFAULT_PROMPT_VARIANT, get_prompt_variant

if TYPE_CHECKING:
    from httpx import AsyncClient


class _FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        content: bytes,
    ) -> None:
        self.url = url
        self.headers = headers or {}
        self.content = content

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="ignore")

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        return self._response


class _LongPdfMapReduceLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    @property
    def map_call_count(self) -> int:
        variant = get_prompt_variant(DEFAULT_PROMPT_VARIANT)
        return sum(1 for _, system in self.calls if system.startswith(variant.map_system))

    async def complete(self, prompt: str, *, system: str = "") -> str:
        raise AssertionError("complete() should not be used in API document tests")

    async def complete_json(self, prompt: str, *, system: str = "") -> dict[str, Any]:
        self.calls.append((prompt, system))
        variant = get_prompt_variant(DEFAULT_PROMPT_VARIANT)
        if system.startswith(variant.map_system):
            return {
                "entities": [
                    {
                        "name": "Healthcare AI Ethics",
                        "description": "A repeated concept used to exercise PDF map-reduce.",
                    }
                ],
                "evidence_lines": [
                    "## 2. Background",
                    "Figure 1. Alignment pipeline",
                    "[12] Value alignment reference",
                    "doi:10.1000/example",
                ],
                "chunk_summary": "Healthcare AI Ethics covers alignment pipelines and value alignment.",
            }
        from hypomnema.ontology.extractor import _SUMMARY_FROM_CHUNKS_SYSTEM

        if system == _SUMMARY_FROM_CHUNKS_SYSTEM:
            return {
                "tidy_title": "Healthcare AI Ethics",
                "summary": "This paper discusses AI ethics in healthcare, focusing on alignment pipelines.",
            }
        if system.startswith(variant.reduce_system):
            return {
                "tidy_title": "Healthcare AI Ethics",
                "tidy_text": (
                    "## 2. Background\n\n"
                    "Figure 1. Alignment pipeline\n\n"
                    "[12] Value alignment reference\n\n"
                    "doi:10.1000/example"
                ),
            }
        if system == linker_mod._PREDICATE_SYSTEM:
            return {"edges": []}
        raise AssertionError(f"Unexpected system prompt: {system}")


def _make_pdf_bytes(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    escaped = text.replace("(", r"\(").replace(")", r"\)")
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 100 700 Td ({escaped}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)

    font_dict = DictionaryObject()
    font_dict[NameObject("/Type")] = NameObject("/Font")
    font_dict[NameObject("/Subtype")] = NameObject("/Type1")
    font_dict[NameObject("/BaseFont")] = NameObject("/Helvetica")
    resources = DictionaryObject()
    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = writer._add_object(font_dict)
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


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
        resp = await client.post("/api/documents/scribbles", json={"text": "Some text", "title": "My Title"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "My Title"

    async def test_empty_text_returns_400(self, client: AsyncClient):
        resp = await client.post("/api/documents/scribbles", json={"text": "   "})
        assert resp.status_code == 400

    async def test_metadata_is_json_object(self, client: AsyncClient):
        resp = await client.post("/api/documents/scribbles", json={"text": "Test"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["metadata"]["processing"]["status"] == "queued"
        assert data["metadata"]["processing"]["source_profile"] == "default"


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
class TestFetchUrl:
    async def test_fetch_pdf_url_returns_pdf_document(
        self,
        client: AsyncClient,
        monkeypatch: Any,
    ) -> None:
        pdf_bytes = _make_pdf_bytes("Healthcare AI ethics and value alignment")
        monkeypatch.setattr(
            "hypomnema.ingestion.url_fetch.httpx.Client",
            lambda *args, **kwargs: _FakeClient(
                _FakeResponse(
                    url="https://cdn.example.com/ethics-paper.pdf",
                    headers={"content-type": "application/pdf"},
                    content=pdf_bytes,
                )
            ),
        )

        resp = await client.post(
            "/api/documents/urls",
            json={"url": "https://example.com/ethics-paper.pdf"},
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["source_type"] == "url"
        assert data["mime_type"] == "application/pdf"
        assert data["title"] == "ethics-paper"
        assert data["metadata"]["fetch_mode"] == "pdf_url"
        assert data["metadata"]["page_count"] == 1
        assert data["metadata"]["final_url"] == "https://cdn.example.com/ethics-paper.pdf"
        assert data["metadata"]["processing"]["status"] == "queued"
        assert data["metadata"]["processing"]["source_profile"] == "pdf"

    async def test_fetch_pdf_url_runs_background_map_reduce_pipeline(
        self,
        client: AsyncClient,
        app: Any,
        monkeypatch: Any,
    ) -> None:
        async def _noop_compute_projections(_db: Any) -> tuple[list[Any], list[Any], list[Any]]:
            return [], [], []

        app.state.llm = _LongPdfMapReduceLLM()
        long_pdf_text = " ".join(
            f"SECTION_{index:04d} Figure_{index:04d} citation[{index:04d}] doi:10.1000/{index:04d}"
            for index in range(220)
        )
        pdf_bytes = _make_pdf_bytes(long_pdf_text)
        monkeypatch.setattr(
            "hypomnema.visualization.projection.compute_projections",
            _noop_compute_projections,
        )
        monkeypatch.setattr(
            "hypomnema.ingestion.url_fetch.httpx.Client",
            lambda *args, **kwargs: _FakeClient(
                _FakeResponse(
                    url="https://cdn.example.com/long-healthcare-ai-ethics.pdf",
                    headers={"content-type": "application/pdf"},
                    content=pdf_bytes,
                )
            ),
        )

        resp = await client.post(
            "/api/documents/urls",
            json={"url": "https://example.com/long-healthcare-ai-ethics.pdf"},
        )

        assert resp.status_code == 201
        data = resp.json()
        await app.state.ontology_queue.join()
        db = app.state.db
        cursor = await db.execute(
            "SELECT processed, mime_type, metadata, tidy_title, tidy_text, tidy_level FROM documents WHERE id = ?",
            (data["id"],),
        )
        row = await cursor.fetchone()
        await cursor.close()

        assert row is not None
        assert row["processed"] == 2
        assert row["mime_type"] == "application/pdf"
        metadata = json.loads(row["metadata"])
        assert metadata["fetch_mode"] == "pdf_url"
        assert row["tidy_title"] == "Healthcare AI Ethics"
        assert row["tidy_text"] is not None
        assert row["tidy_level"] == "light_cleanup"
        assert metadata["processing"]["status"] == "completed"
        assert metadata["processing"]["stage"] == "done"
        assert metadata["processing"]["source_profile"] == "pdf"
        assert metadata["processing"]["chunk_total"] > 1
        assert metadata["processing"]["chunk_completed"] == metadata["processing"]["chunk_total"]
        assert metadata["processing"]["chunk_failed"] == 0
        assert metadata["processing"]["fallback_used"] is False
        assert app.state.llm.map_call_count > 1
        assert not any(
            system.startswith(get_prompt_variant(DEFAULT_PROMPT_VARIANT).reduce_system)
            for _, system in app.state.llm.calls
        )


@pytest.mark.asyncio
class TestListDocuments:
    async def test_empty_returns_list(self, client: AsyncClient):
        resp = await client.get("/api/documents")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_returns_recent_documents(self, client: AsyncClient, app):
        for i in range(3):
            await client.post("/api/documents/scribbles", json={"text": f"Doc {i}"})
        await app.state.ontology_queue.join()

        resp = await client.get("/api/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        # Each doc should have engrams list
        assert "engrams" in data[0]

    async def test_excludes_drafts(self, client: AsyncClient, app):
        await client.post("/api/documents/scribbles", json={"text": "Normal doc"})
        await client.post("/api/documents/scribbles", json={"text": "Draft doc", "draft": True})
        await app.state.ontology_queue.join()

        resp = await client.get("/api/documents")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["text"] == "Normal doc"

    async def test_days_param(self, client: AsyncClient, app):
        await client.post("/api/documents/scribbles", json={"text": "Recent doc"})
        await app.state.ontology_queue.join()
        resp = await client.get("/api/documents", params={"days": 1})
        assert resp.status_code == 200
        assert len(resp.json()) == 1


@pytest.mark.asyncio
class TestDrafts:
    async def test_create_draft(self, client: AsyncClient):
        resp = await client.post("/api/documents/scribbles", json={"text": "My draft", "draft": True})
        assert resp.status_code == 201
        data = resp.json()
        assert data["processed"] == 0

    async def test_list_drafts(self, client: AsyncClient, app):
        await client.post("/api/documents/scribbles", json={"text": "Draft 1", "draft": True})
        await client.post("/api/documents/scribbles", json={"text": "Draft 2", "draft": True})
        await client.post("/api/documents/scribbles", json={"text": "Normal"})
        await app.state.ontology_queue.join()

        resp = await client.get("/api/documents/drafts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2


@pytest.mark.asyncio
class TestDocumentCount:
    async def test_count_excludes_drafts(self, client: AsyncClient, app):
        await client.post("/api/documents/scribbles", json={"text": "Normal"})
        await client.post("/api/documents/scribbles", json={"text": "Draft", "draft": True})
        await app.state.ontology_queue.join()

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
        create_resp = await client.post("/api/documents/scribbles", json={"text": "Some text", "title": "Old"})
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
        await db.execute(
            "UPDATE documents SET tidy_title = ?, tidy_text = ?, tidy_level = ? WHERE id = ?",
            ("Old tidy title", "Old tidy text", "structured_notes", doc_id),
        )
        await db.commit()

        # Update should clear them
        resp = await client.patch(f"/api/documents/{doc_id}", json={"text": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["tidy_level"] is None

        cursor = await db.execute("SELECT COUNT(*) FROM document_engrams WHERE document_id = ?", (doc_id,))
        row = await cursor.fetchone()
        assert row[0] == 0

        cursor = await db.execute(
            "SELECT tidy_title, tidy_text, tidy_level FROM documents WHERE id = ?",
            (doc_id,),
        )
        row = await cursor.fetchone()
        assert row["tidy_title"] is None
        assert row["tidy_text"] is None
        assert row["tidy_level"] is None
