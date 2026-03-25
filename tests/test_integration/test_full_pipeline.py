"""Integration tests — full pipeline from ingestion to visualization."""

from pathlib import Path

import aiosqlite
import pytest

from hypomnema.embeddings.mock import MockEmbeddingModel
from hypomnema.ingestion.file_parser import ingest_file
from hypomnema.ingestion.scribble import create_scribble
from hypomnema.llm.mock import MockLLMClient
from hypomnema.ontology.pipeline import link_document, process_document
from hypomnema.search.doc_search import search_documents
from hypomnema.visualization.projection import compute_projections

_has_projection_deps = True
try:
    import sklearn  # noqa: F401
    import umap  # noqa: F401
except ImportError:
    _has_projection_deps = False


async def test_scribble_to_engrams_to_edges(
    tmp_db: aiosqlite.Connection,
    int_llm: MockLLMClient,
    mock_embeddings: MockEmbeddingModel,
) -> None:
    doc = await create_scribble(tmp_db, "Quantum computing uses qubits for parallel computation")
    engrams = await process_document(tmp_db, doc.id, int_llm, mock_embeddings)
    assert len(engrams) > 0

    edges = await link_document(tmp_db, doc.id, int_llm)
    assert isinstance(edges, list)

    cursor = await tmp_db.execute("SELECT processed FROM documents WHERE id = ?", (doc.id,))
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    assert row[0] == 2


async def test_two_related_docs_create_engrams(
    tmp_db: aiosqlite.Connection,
    int_llm: MockLLMClient,
    mock_embeddings: MockEmbeddingModel,
) -> None:
    doc1 = await create_scribble(tmp_db, "Quantum computing leverages quantum mechanics")
    doc2 = await create_scribble(tmp_db, "Neural networks learn via backpropagation through layers")

    engrams1 = await process_document(tmp_db, doc1.id, int_llm, mock_embeddings)
    engrams2 = await process_document(tmp_db, doc2.id, int_llm, mock_embeddings)
    assert len(engrams1) > 0
    assert len(engrams2) > 0

    await link_document(tmp_db, doc1.id, int_llm)
    await link_document(tmp_db, doc2.id, int_llm)

    for doc_id in (doc1.id, doc2.id):
        cursor = await tmp_db.execute("SELECT processed FROM documents WHERE id = ?", (doc_id,))
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        assert row[0] == 2

    cursor = await tmp_db.execute("SELECT COUNT(*) FROM engrams")
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    assert row[0] > 0


async def test_file_upload_to_engrams(
    tmp_db: aiosqlite.Connection,
    int_llm: MockLLMClient,
    mock_embeddings: MockEmbeddingModel,
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "graph_theory.md"
    md_path.write_text("# Graph Theory\n\nGraph theory studies vertex and edge structures.")

    doc = await ingest_file(tmp_db, md_path)
    assert doc.source_type == "file"
    assert doc.mime_type == "text/markdown"

    engrams = await process_document(tmp_db, doc.id, int_llm, mock_embeddings)
    assert len(engrams) > 0


async def test_search_after_ingestion(
    tmp_db: aiosqlite.Connection,
    int_llm: MockLLMClient,
    mock_embeddings: MockEmbeddingModel,
) -> None:
    doc = await create_scribble(tmp_db, "Quantum computing uses qubits for computation")
    await process_document(tmp_db, doc.id, int_llm, mock_embeddings)

    results = await search_documents(tmp_db, "quantum", mock_embeddings)
    assert len(results) > 0
    assert any(r.document.id == doc.id for r in results)


@pytest.mark.skipif(not _has_projection_deps, reason="umap-learn / scikit-learn not installed")
async def test_projections_computed(
    tmp_db: aiosqlite.Connection,
    int_llm: MockLLMClient,
    mock_embeddings: MockEmbeddingModel,
) -> None:
    texts = [
        "Quantum computing uses qubits for parallel computation",
        "Neural networks learn via backpropagation through layers",
        "Graph theory studies vertex and edge structures",
        "Cryptography enables secure communication protocols",
        "Database systems store and retrieve structured data",
    ]
    for text in texts:
        doc = await create_scribble(tmp_db, text)
        await process_document(tmp_db, doc.id, int_llm, mock_embeddings)

    points, clusters, gaps = await compute_projections(tmp_db)
    assert len(points) > 0
    for p in points:
        assert hasattr(p, "x")
        assert hasattr(p, "y")
        assert hasattr(p, "z")
