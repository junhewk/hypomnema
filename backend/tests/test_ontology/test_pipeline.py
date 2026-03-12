"""Tests for ontology pipeline."""

import pytest

from hypomnema.llm.mock import MockLLMClient
from hypomnema.ontology.pipeline import process_document, process_pending_documents

from .conftest import insert_test_doc


def _make_llm() -> MockLLMClient:
    return MockLLMClient(responses={
        "Actor-Network": {
            "entities": [
                {"name": "Actor-Network Theory", "description": "Sociological framework"},
                {"name": "Translation", "description": "Process of network building"},
            ]
        },
        "Normalize these entity names": {
            "mapping": {
                "actor-network theory": "actor-network theory",
                "translation": "translation",
            }
        },
    })


class TestProcessDocument:
    @pytest.mark.asyncio
    async def test_creates_engrams(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        engrams = await process_document(tmp_db, doc_id, _make_llm(), mock_embeddings)
        assert len(engrams) == 2
        names = {e.canonical_name for e in engrams}
        assert "actor-network theory" in names
        assert "translation" in names

    @pytest.mark.asyncio
    async def test_document_marked_processed(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        await process_document(tmp_db, doc_id, _make_llm(), mock_embeddings)
        cursor = await tmp_db.execute(
            "SELECT processed FROM documents WHERE id = ?", (doc_id,)
        )
        row = await cursor.fetchone()
        assert row["processed"] == 1

    @pytest.mark.asyncio
    async def test_engrams_linked_to_document(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        await process_document(tmp_db, doc_id, _make_llm(), mock_embeddings)
        cursor = await tmp_db.execute(
            "SELECT COUNT(*) as cnt FROM document_engrams WHERE document_id = ?",
            (doc_id,),
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 2

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        llm = _make_llm()
        engrams1 = await process_document(tmp_db, doc_id, llm, mock_embeddings)
        engrams2 = await process_document(tmp_db, doc_id, llm, mock_embeddings)
        assert len(engrams1) == 2
        assert engrams2 == []

    @pytest.mark.asyncio
    async def test_nonexistent_document_raises(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(ValueError, match="not found"):
            await process_document(tmp_db, "nonexistent", _make_llm(), mock_embeddings)

    @pytest.mark.asyncio
    async def test_empty_extraction_marks_processed(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc_id = await insert_test_doc(
            tmp_db, "trivial text with no entities", doc_id="emptydoc"
        )
        # Default MockLLMClient returns {"mock": True} which has no "entities" key
        engrams = await process_document(tmp_db, doc_id, MockLLMClient(), mock_embeddings)
        assert engrams == []
        cursor = await tmp_db.execute(
            "SELECT processed FROM documents WHERE id = ?", (doc_id,)
        )
        row = await cursor.fetchone()
        assert row["processed"] == 1

    @pytest.mark.asyncio
    async def test_dedup_across_documents(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc1 = await insert_test_doc(
            tmp_db, "Actor-Network Theory was proposed.", doc_id="doc1"
        )
        doc2 = await insert_test_doc(
            tmp_db, "Actor-Network Theory is widely used.", doc_id="doc2"
        )
        llm = _make_llm()
        engrams1 = await process_document(tmp_db, doc1, llm, mock_embeddings)
        engrams2 = await process_document(tmp_db, doc2, llm, mock_embeddings)
        # Same engrams returned (deduped)
        ids1 = {e.id for e in engrams1}
        ids2 = {e.id for e in engrams2}
        assert ids1 == ids2
        # But both documents are linked
        cursor = await tmp_db.execute("SELECT COUNT(*) as cnt FROM document_engrams")
        row = await cursor.fetchone()
        assert row["cnt"] == 4  # 2 engrams * 2 documents


class TestProcessPendingDocuments:
    @pytest.mark.asyncio
    async def test_processes_all_pending(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        for i in range(3):
            await insert_test_doc(
                tmp_db, "Actor-Network Theory discussion.", doc_id=f"pending{i}"
            )
        results = await process_pending_documents(
            tmp_db, _make_llm(), mock_embeddings
        )
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_respects_limit(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        for i in range(5):
            await insert_test_doc(
                tmp_db, "Actor-Network Theory discussion.", doc_id=f"limit{i}"
            )
        results = await process_pending_documents(
            tmp_db, _make_llm(), mock_embeddings, limit=2
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_skips_already_processed(self, tmp_db, mock_embeddings) -> None:  # type: ignore[no-untyped-def]
        doc1 = await insert_test_doc(
            tmp_db, "Actor-Network Theory discussion.", doc_id="skip1"
        )
        await insert_test_doc(
            tmp_db, "Actor-Network Theory discussion.", doc_id="skip2"
        )
        # Mark first as processed
        await tmp_db.execute(
            "UPDATE documents SET processed = 1 WHERE id = ?", (doc1,)
        )
        await tmp_db.commit()
        results = await process_pending_documents(
            tmp_db, _make_llm(), mock_embeddings
        )
        assert len(results) == 1
        assert "skip2" in results
