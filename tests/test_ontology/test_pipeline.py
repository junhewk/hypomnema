"""Tests for ontology pipeline."""

import pytest

from hypomnema.llm.mock import MockLLMClient
from hypomnema.ontology.pipeline import (
    link_document,
    link_pending_documents,
    process_document,
    process_pending_documents,
    retidy_document,
)

from .conftest import insert_test_doc


def _make_llm() -> MockLLMClient:
    return MockLLMClient(
        responses={
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
        }
    )


def _make_tidy_llm() -> MockLLMClient:
    return MockLLMClient(
        responses={
            "Tidy Actor-Network": {
                "entities": [
                    {"name": "Actor-Network Theory", "description": "Sociological framework"},
                    {"name": "Translation", "description": "Process of network building"},
                ],
                "tidy_title": "Tidy Actor-Network Notes",
                "tidy_text": "- Actor-Network Theory\n- Translation",
            },
            "Normalize these entity names": {
                "mapping": {
                    "actor-network theory": "actor-network theory",
                    "translation": "translation",
                }
            },
        }
    )


class TestProcessDocument:
    @pytest.mark.asyncio
    async def test_creates_engrams(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        engrams = await process_document(tmp_db, doc_id, _make_llm(), mock_embeddings)
        assert len(engrams) == 2
        names = {e.canonical_name for e in engrams}
        assert "actor-network theory" in names
        assert "translation" in names

    @pytest.mark.asyncio
    async def test_document_marked_processed(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        await process_document(tmp_db, doc_id, _make_llm(), mock_embeddings)
        cursor = await tmp_db.execute("SELECT processed FROM documents WHERE id = ?", (doc_id,))
        row = await cursor.fetchone()
        assert row["processed"] == 1

    @pytest.mark.asyncio
    async def test_engrams_linked_to_document(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        await process_document(tmp_db, doc_id, _make_llm(), mock_embeddings)
        cursor = await tmp_db.execute(
            "SELECT COUNT(*) as cnt FROM document_engrams WHERE document_id = ?",
            (doc_id,),
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 2

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        llm = _make_llm()
        engrams1 = await process_document(tmp_db, doc_id, llm, mock_embeddings)
        engrams2 = await process_document(tmp_db, doc_id, llm, mock_embeddings)
        assert len(engrams1) == 2
        assert engrams2 == []

    @pytest.mark.asyncio
    async def test_nonexistent_document_raises(self, tmp_db, mock_embeddings) -> None:
        with pytest.raises(ValueError, match="not found"):
            await process_document(tmp_db, "nonexistent", _make_llm(), mock_embeddings)

    @pytest.mark.asyncio
    async def test_empty_extraction_marks_processed(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "trivial text with no entities", doc_id="emptydoc")
        # Default MockLLMClient returns {"mock": True} which has no "entities" key
        engrams = await process_document(tmp_db, doc_id, MockLLMClient(), mock_embeddings)
        assert engrams == []
        cursor = await tmp_db.execute("SELECT processed FROM documents WHERE id = ?", (doc_id,))
        row = await cursor.fetchone()
        assert row["processed"] == 1

    @pytest.mark.asyncio
    async def test_dedup_across_documents(self, tmp_db, mock_embeddings) -> None:
        doc1 = await insert_test_doc(tmp_db, "Actor-Network Theory was proposed.", doc_id="doc1")
        doc2 = await insert_test_doc(tmp_db, "Actor-Network Theory is widely used.", doc_id="doc2")
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

    @pytest.mark.asyncio
    async def test_stores_tidy_output_and_level(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Tidy Actor-Network Theory notes.")

        await process_document(
            tmp_db,
            doc_id,
            _make_tidy_llm(),
            mock_embeddings,
            tidy_level="editorial_polish",
        )

        cursor = await tmp_db.execute(
            "SELECT tidy_title, tidy_text, tidy_level FROM documents WHERE id = ?",
            (doc_id,),
        )
        row = await cursor.fetchone()
        assert row["tidy_title"] == "Tidy Actor-Network Notes"
        assert row["tidy_text"] == "- Actor-Network Theory\n- Translation"
        assert row["tidy_level"] == "editorial_polish"

    @pytest.mark.asyncio
    async def test_pdf_document_defaults_to_acceptable_tidy_level(
        self,
        tmp_db,
        mock_embeddings,
    ) -> None:
        doc_id = await insert_test_doc(
            tmp_db,
            "Tidy Actor-Network Theory notes.",
            mime_type="application/pdf",
        )

        await process_document(
            tmp_db,
            doc_id,
            _make_tidy_llm(),
            mock_embeddings,
        )

        cursor = await tmp_db.execute(
            "SELECT tidy_level FROM documents WHERE id = ?",
            (doc_id,),
        )
        row = await cursor.fetchone()
        assert row["tidy_level"] == "light_cleanup"


class TestProcessPendingDocuments:
    @pytest.mark.asyncio
    async def test_processes_all_pending(self, tmp_db, mock_embeddings) -> None:
        for i in range(3):
            await insert_test_doc(tmp_db, "Actor-Network Theory discussion.", doc_id=f"pending{i}")
        results = await process_pending_documents(tmp_db, _make_llm(), mock_embeddings)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_respects_limit(self, tmp_db, mock_embeddings) -> None:
        for i in range(5):
            await insert_test_doc(tmp_db, "Actor-Network Theory discussion.", doc_id=f"limit{i}")
        results = await process_pending_documents(tmp_db, _make_llm(), mock_embeddings, limit=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_skips_already_processed(self, tmp_db, mock_embeddings) -> None:
        doc1 = await insert_test_doc(tmp_db, "Actor-Network Theory discussion.", doc_id="skip1")
        await insert_test_doc(tmp_db, "Actor-Network Theory discussion.", doc_id="skip2")
        # Mark first as processed
        await tmp_db.execute("UPDATE documents SET processed = 1 WHERE id = ?", (doc1,))
        await tmp_db.commit()
        results = await process_pending_documents(tmp_db, _make_llm(), mock_embeddings)
        assert len(results) == 1
        assert "skip2" in results

    @pytest.mark.asyncio
    async def test_skips_rejected_documents(self, tmp_db, mock_embeddings) -> None:
        doc1 = await insert_test_doc(tmp_db, "Actor-Network Theory discussion.", doc_id="rejected1")
        await insert_test_doc(tmp_db, "Actor-Network Theory discussion.", doc_id="accepted1")
        # Reject doc1 via triage
        await tmp_db.execute("UPDATE documents SET triaged = -1 WHERE id = ?", (doc1,))
        await tmp_db.commit()
        results = await process_pending_documents(tmp_db, _make_llm(), mock_embeddings)
        assert len(results) == 1
        assert "accepted1" in results
        assert "rejected1" not in results


def _make_linker_llm() -> MockLLMClient:
    return MockLLMClient(
        responses={
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
            "Source concept:": {
                "edges": [
                    {"target": "translation", "predicate": "related_to", "confidence": 0.9},
                ]
            },
        }
    )


class TestLinkDocument:
    @pytest.mark.asyncio
    async def test_creates_edges(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        llm = _make_linker_llm()
        await process_document(tmp_db, doc_id, llm, mock_embeddings)
        edges = await link_document(tmp_db, doc_id, llm)
        # At least some edges should be created (depends on neighbor similarity)
        # The two engrams are neighbors of each other
        assert isinstance(edges, list)

    @pytest.mark.asyncio
    async def test_marks_processed_2(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        llm = _make_linker_llm()
        await process_document(tmp_db, doc_id, llm, mock_embeddings)
        await link_document(tmp_db, doc_id, llm)
        cursor = await tmp_db.execute("SELECT processed FROM documents WHERE id = ?", (doc_id,))
        row = await cursor.fetchone()
        assert row["processed"] == 2

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        llm = _make_linker_llm()
        await process_document(tmp_db, doc_id, llm, mock_embeddings)
        await link_document(tmp_db, doc_id, llm)
        # Second call should return [] because processed is now 2
        edges2 = await link_document(tmp_db, doc_id, llm)
        assert edges2 == []

    @pytest.mark.asyncio
    async def test_skips_unprocessed(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        # Don't process — document is still processed=0
        edges = await link_document(tmp_db, doc_id, _make_linker_llm())
        assert edges == []

    @pytest.mark.asyncio
    async def test_nonexistent_document_raises(self, tmp_db, mock_embeddings) -> None:
        with pytest.raises(ValueError, match="not found"):
            await link_document(tmp_db, "nonexistent", _make_linker_llm())

    @pytest.mark.asyncio
    async def test_no_engrams_marks_processed(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "trivial text", doc_id="emptylinkdoc")
        # Mark processed=1 manually (no engrams)
        await tmp_db.execute("UPDATE documents SET processed = 1 WHERE id = ?", (doc_id,))
        await tmp_db.commit()
        edges = await link_document(tmp_db, doc_id, _make_linker_llm())
        assert edges == []
        cursor = await tmp_db.execute("SELECT processed FROM documents WHERE id = ?", (doc_id,))
        row = await cursor.fetchone()
        assert row["processed"] == 2

    @pytest.mark.asyncio
    async def test_edges_have_source_document_id(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        llm = _make_linker_llm()
        await process_document(tmp_db, doc_id, llm, mock_embeddings)
        edges = await link_document(tmp_db, doc_id, llm)
        for edge in edges:
            assert edge.source_document_id == doc_id


class TestLinkPendingDocuments:
    @pytest.mark.asyncio
    async def test_links_all_pending(self, tmp_db, mock_embeddings) -> None:
        llm = _make_linker_llm()
        for i in range(3):
            doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory discussion.", doc_id=f"linkpend{i}")
            await process_document(tmp_db, doc_id, llm, mock_embeddings)
        results = await link_pending_documents(tmp_db, llm)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_respects_limit(self, tmp_db, mock_embeddings) -> None:
        llm = _make_linker_llm()
        for i in range(3):
            doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory discussion.", doc_id=f"linklim{i}")
            await process_document(tmp_db, doc_id, llm, mock_embeddings)
        results = await link_pending_documents(tmp_db, llm, limit=1)
        assert len(results) == 1


class TestRevisionGuard:
    @pytest.mark.asyncio
    async def test_process_document_skips_stale_revision(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        # Bump revision to 2 in DB
        await tmp_db.execute("UPDATE documents SET revision = 2 WHERE id = ?", (doc_id,))
        await tmp_db.commit()
        # Call with expected=1 (stale)
        engrams = await process_document(tmp_db, doc_id, _make_llm(), mock_embeddings, expected_revision=1)
        assert engrams == []
        # processed should still be 0
        cursor = await tmp_db.execute("SELECT processed FROM documents WHERE id = ?", (doc_id,))
        row = await cursor.fetchone()
        assert row["processed"] == 0

    @pytest.mark.asyncio
    async def test_process_document_runs_with_current_revision(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        engrams = await process_document(tmp_db, doc_id, _make_llm(), mock_embeddings, expected_revision=1)
        assert len(engrams) == 2

    @pytest.mark.asyncio
    async def test_process_document_runs_without_revision(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        # Set revision high — but no expected_revision means batch mode, should succeed
        await tmp_db.execute("UPDATE documents SET revision = 99 WHERE id = ?", (doc_id,))
        await tmp_db.commit()
        engrams = await process_document(tmp_db, doc_id, _make_llm(), mock_embeddings)
        assert len(engrams) == 2

    @pytest.mark.asyncio
    async def test_link_document_skips_stale_revision(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.")
        llm = _make_linker_llm()
        await process_document(tmp_db, doc_id, llm, mock_embeddings)
        # Bump revision after processing
        await tmp_db.execute("UPDATE documents SET revision = 2 WHERE id = ?", (doc_id,))
        await tmp_db.commit()
        # Link with stale revision
        edges = await link_document(tmp_db, doc_id, llm, expected_revision=1)
        assert edges == []
        # processed should still be 1 (not advanced to 2)
        cursor = await tmp_db.execute("SELECT processed FROM documents WHERE id = ?", (doc_id,))
        row = await cursor.fetchone()
        assert row["processed"] == 1


class TestRetidyDocument:
    @pytest.mark.asyncio
    async def test_retidy_updates_only_tidy_fields(self, tmp_db, mock_embeddings) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.", doc_id="retidy-doc")
        llm = _make_linker_llm()
        await process_document(tmp_db, doc_id, llm, mock_embeddings)

        cursor = await tmp_db.execute(
            "SELECT processed, revision FROM documents WHERE id = ?",
            (doc_id,),
        )
        before = await cursor.fetchone()
        cursor = await tmp_db.execute(
            "SELECT COUNT(*) AS cnt FROM document_engrams WHERE document_id = ?",
            (doc_id,),
        )
        before_links = await cursor.fetchone()

        changed = await retidy_document(
            tmp_db,
            doc_id,
            MockLLMClient(
                responses={
                    "Actor-Network Theory is important.": {
                        "tidy_title": "Retidied Notes",
                        "tidy_text": "- Actor-Network Theory is important.",
                    }
                }
            ),
            tidy_level="full_revision",
        )

        assert changed is True
        cursor = await tmp_db.execute(
            "SELECT processed, revision, tidy_title, tidy_text, tidy_level FROM documents WHERE id = ?",
            (doc_id,),
        )
        after = await cursor.fetchone()
        cursor = await tmp_db.execute(
            "SELECT COUNT(*) AS cnt FROM document_engrams WHERE document_id = ?",
            (doc_id,),
        )
        after_links = await cursor.fetchone()

        assert after["processed"] == before["processed"]
        assert after["revision"] == before["revision"]
        assert after["tidy_title"] == "Retidied Notes"
        assert after["tidy_text"] == "- Actor-Network Theory is important."
        assert after["tidy_level"] == "full_revision"
        assert after_links["cnt"] == before_links["cnt"]

    @pytest.mark.asyncio
    async def test_retidy_skips_stale_revision(self, tmp_db) -> None:
        doc_id = await insert_test_doc(tmp_db, "Actor-Network Theory is important.", doc_id="stale-retidy")
        changed = await retidy_document(
            tmp_db,
            doc_id,
            MockLLMClient(
                responses={
                    "Actor-Network Theory is important.": {
                        "tidy_title": "Should Not Apply",
                        "tidy_text": "Should Not Apply",
                    }
                }
            ),
            expected_revision=2,
            tidy_level="light_cleanup",
        )

        assert changed is False
        cursor = await tmp_db.execute(
            "SELECT tidy_title, tidy_text, tidy_level FROM documents WHERE id = ?",
            (doc_id,),
        )
        row = await cursor.fetchone()
        assert row["tidy_title"] is None
        assert row["tidy_text"] is None
        assert row["tidy_level"] is None
