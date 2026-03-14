"""Ontology extraction pipeline: document -> entities -> engrams."""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

    from hypomnema.embeddings.base import EmbeddingModel
    from hypomnema.llm.base import LLMClient

from hypomnema.db.models import Document, Edge, Engram
from hypomnema.ontology.engram import get_or_create_engram, link_document_engram
from hypomnema.ontology.extractor import extract_entities
from hypomnema.ontology.linker import (
    assign_predicates,
    create_edge,
    find_neighbors,
)
from hypomnema.ontology.normalizer import normalize, resolve_synonyms

logger = logging.getLogger(__name__)


async def _fetch_document(db: aiosqlite.Connection, document_id: str) -> Document:
    """Fetch a document by ID, raise ValueError if not found."""
    cursor = await db.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise ValueError(f"Document {document_id} not found")
    return Document.from_row(row)


async def _check_revision(
    db: aiosqlite.Connection, document_id: str, expected_revision: int | None
) -> bool:
    """Return True if current revision matches expected. None = always True (batch mode)."""
    if expected_revision is None:
        return True
    cursor = await db.execute(
        "SELECT revision FROM documents WHERE id = ?", (document_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return False
    return row["revision"] == expected_revision


async def process_document(
    db: aiosqlite.Connection,
    document_id: str,
    llm: LLMClient,
    embeddings: EmbeddingModel,
    *,
    expected_revision: int | None = None,
) -> list[Engram]:
    """Run entity extraction pipeline on a single document.

    1. Fetch document; skip if already processed >= 1
    2. Extract entities via LLM
    3. Normalize + resolve synonyms
    4. Batch embed all canonical names
    5. get_or_create_engram + link for each
    6. Mark document processed=1, commit

    Raises:
        ValueError: If document_id not found.
    """
    doc = await _fetch_document(db, document_id)

    if doc.processed >= 1:
        return []

    # Pre-flight revision check (use already-fetched doc)
    if expected_revision is not None and doc.revision != expected_revision:
        logger.warning("process_document: stale revision for %s (expected %s)", document_id, expected_revision)
        return []

    # Extract entities + tidy memo
    result = await extract_entities(llm, doc.text)

    extracted = result.entities

    # Post-LLM revision check — before any DB writes
    if not await _check_revision(db, document_id, expected_revision):
        logger.warning("process_document: stale revision after LLM work for %s (expected %s)", document_id, expected_revision)
        return []

    # Store tidy memo fields
    if result.tidy_title or result.tidy_text:
        await db.execute(
            "UPDATE documents SET tidy_title = ?, tidy_text = ? WHERE id = ?",
            (result.tidy_title, result.tidy_text, document_id),
        )

    if not extracted:
        await db.execute(
            "UPDATE documents SET processed = 1 WHERE id = ?", (document_id,)
        )
        await db.commit()
        return []

    # Normalize names
    normalized_names = [normalize(e.name) for e in extracted]

    # Resolve synonyms (merges within batch)
    canonical_map = await resolve_synonyms(llm, list(set(normalized_names)))

    # Build unique canonical -> description mapping
    canonical_entities: dict[str, str | None] = {}
    for entity, norm_name in zip(extracted, normalized_names, strict=True):
        canonical = canonical_map.get(norm_name, norm_name)
        if canonical not in canonical_entities:
            canonical_entities[canonical] = entity.description

    # Batch embed all canonical names
    canonical_names = list(canonical_entities.keys())
    vectors = embeddings.embed(canonical_names)

    # Create engrams and link to document
    engrams: list[Engram] = []
    for i, name in enumerate(canonical_names):
        engram, _created = await get_or_create_engram(
            db,
            name,
            canonical_entities[name],
            vectors[i],
        )
        await link_document_engram(db, document_id, engram.id)
        engrams.append(engram)

    # Mark processed
    await db.execute(
        "UPDATE documents SET processed = 1 WHERE id = ?", (document_id,)
    )
    await db.commit()
    return engrams


async def process_pending_documents(
    db: aiosqlite.Connection,
    llm: LLMClient,
    embeddings: EmbeddingModel,
    *,
    limit: int = 50,
) -> dict[str, list[Engram]]:
    """Process all documents with processed=0, up to limit."""
    cursor = await db.execute(
        "SELECT id FROM documents WHERE processed = 0 AND triaged != -1 ORDER BY created_at LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    results: dict[str, list[Engram]] = {}
    for row in rows:
        results[row["id"]] = await process_document(db, row["id"], llm, embeddings)
    return results


async def link_document(
    db: aiosqlite.Connection,
    document_id: str,
    llm: LLMClient,
    *,
    expected_revision: int | None = None,
) -> list[Edge]:
    """Generate edges for engrams in a processed document.

    Only processes documents with processed=1 (engrams extracted, not yet linked).
    Sets processed=2 after edge generation.

    Raises:
        ValueError: If document_id not found.
    """
    doc = await _fetch_document(db, document_id)

    if doc.processed != 1:
        return []

    # Pre-flight revision check (use already-fetched doc)
    if expected_revision is not None and doc.revision != expected_revision:
        logger.warning("link_document: stale revision for %s (expected %s)", document_id, expected_revision)
        return []

    # Get engrams linked to this document
    cursor = await db.execute(
        "SELECT e.* FROM engrams e "
        "JOIN document_engrams de ON e.id = de.engram_id "
        "WHERE de.document_id = ?",
        (document_id,),
    )
    engram_rows = await cursor.fetchall()
    await cursor.close()
    engrams = [Engram.from_row(r) for r in engram_rows]

    if not engrams:
        await db.execute(
            "UPDATE documents SET processed = 2 WHERE id = ?", (document_id,)
        )
        await db.commit()
        return []

    # For each engram, find neighbors and assign predicates
    all_edges: list[Edge] = []
    for engram in engrams:
        neighbor_pairs = await find_neighbors(db, engram.id)
        if not neighbor_pairs:
            continue
        neighbors = [n for n, _sim in neighbor_pairs]
        proposed = await assign_predicates(
            llm, engram, neighbors, document_text=doc.text
        )
        for p in proposed:
            p_with_doc = dataclasses.replace(p, source_document_id=document_id)
            edge = await create_edge(db, p_with_doc)
            if edge is not None:
                all_edges.append(edge)

    # Post-LLM revision check — before committing edges
    if not await _check_revision(db, document_id, expected_revision):
        logger.warning("link_document: stale revision after LLM work for %s (expected %s)", document_id, expected_revision)
        await db.rollback()
        return []

    # Mark processed=2
    await db.execute(
        "UPDATE documents SET processed = 2 WHERE id = ?", (document_id,)
    )
    await db.commit()
    return all_edges


async def link_pending_documents(
    db: aiosqlite.Connection,
    llm: LLMClient,
    *,
    limit: int = 50,
) -> dict[str, list[Edge]]:
    """Generate edges for all documents with processed=1, up to limit."""
    cursor = await db.execute(
        "SELECT id FROM documents WHERE processed = 1 ORDER BY created_at LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    results: dict[str, list[Edge]] = {}
    for row in rows:
        results[row["id"]] = await link_document(db, row["id"], llm)
    return results
