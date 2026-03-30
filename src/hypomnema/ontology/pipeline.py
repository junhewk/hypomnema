"""Ontology extraction pipeline: document -> entities -> engrams."""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import aiosqlite
    import numpy as np
    from numpy.typing import NDArray

    from hypomnema.embeddings.base import EmbeddingModel
    from hypomnema.llm.base import LLMClient

from hypomnema.db.models import Document, Edge, Engram
from hypomnema.db.transactions import immediate_transaction
from hypomnema.ontology.engram import get_or_create_engram, link_document_engram
from hypomnema.ontology.extractor import ExtractedEntity, extract_entities, render_tidy_text
from hypomnema.ontology.linker import (
    ProposedEdge,
    assign_predicates,
    create_edge,
    find_neighbors,
)
from hypomnema.ontology.normalizer import normalize, resolve_synonyms
from hypomnema.tidy import DEFAULT_TIDY_LEVEL, TidyLevel

logger = logging.getLogger(__name__)
_PDF_DEFAULT_TIDY_LEVEL: TidyLevel = "light_cleanup"
_INCREMENTAL_FALLBACK_THRESHOLD = 0.5  # Fall back to full rebuild if >50% engrams changed


@dataclasses.dataclass(frozen=True)
class PreparedEngram:
    canonical_name: str
    description: str | None
    embedding: NDArray[np.float32]


async def _fetch_document(db: aiosqlite.Connection, document_id: str) -> Document:
    """Fetch a document by ID, raise ValueError if not found."""
    cursor = await db.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise ValueError(f"Document {document_id} not found")
    return Document.from_row(row)


async def _check_revision(db: aiosqlite.Connection, document_id: str, expected_revision: int | None) -> bool:
    """Return True if current revision matches expected. None = always True (batch mode)."""
    if expected_revision is None:
        return True
    cursor = await db.execute("SELECT revision FROM documents WHERE id = ?", (document_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return False
    return bool(row["revision"] == expected_revision)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _resolve_document_tidy_level(doc: Document, tidy_level: TidyLevel) -> TidyLevel:
    if doc.mime_type == "application/pdf" and tidy_level == DEFAULT_TIDY_LEVEL:
        return _PDF_DEFAULT_TIDY_LEVEL
    return tidy_level


async def remove_document_associations(db: aiosqlite.Connection, document_id: str) -> None:
    """Delete engram links, embeddings, and edges tied to a document."""
    await db.execute("DELETE FROM document_engrams WHERE document_id = ?", (document_id,))
    await db.execute("DELETE FROM document_embeddings WHERE document_id = ?", (document_id,))
    await db.execute("DELETE FROM edges WHERE source_document_id = ?", (document_id,))


def _build_extraction_text(doc: Document) -> str:
    """Build text for entity extraction, incorporating annotations for non-scribbles."""
    if doc.source_type != "scribble" and doc.annotation:
        return f"{doc.text}\n\n---\nUser notes:\n{doc.annotation}"
    return doc.text


async def _prepare_engrams(
    llm: LLMClient,
    embeddings: EmbeddingModel,
    entities: list[ExtractedEntity],
) -> list[PreparedEngram]:
    """Normalize, resolve synonyms, and embed candidate engrams before DB writes."""
    normalized_names = [normalize(e.name) for e in entities]
    canonical_map = await resolve_synonyms(llm, list(set(normalized_names)))
    canonical_entities: dict[str, str | None] = {}
    for entity, norm_name in zip(entities, normalized_names, strict=True):
        canonical = canonical_map.get(norm_name, norm_name)
        if canonical not in canonical_entities:
            canonical_entities[canonical] = entity.description
    canonical_names = list(canonical_entities.keys())
    vectors = embeddings.embed(canonical_names)
    return [
        PreparedEngram(
            canonical_name=name,
            description=canonical_entities[name],
            embedding=vectors[i],
        )
        for i, name in enumerate(canonical_names)
    ]


async def _materialize_engrams(
    db: aiosqlite.Connection,
    prepared_engrams: list[PreparedEngram],
) -> dict[str, Engram]:
    """Resolve prepared engrams against the DB and create missing rows."""
    result: dict[str, Engram] = {}
    for item in prepared_engrams:
        engram, _created = await get_or_create_engram(
            db,
            item.canonical_name,
            item.description,
            item.embedding,
        )
        result[engram.id] = engram
    return result


async def _collect_edge_proposals(
    db: aiosqlite.Connection,
    llm: LLMClient,
    document_id: str,
    document_text: str,
    engrams: list[Engram],
    *,
    log_context: str,
) -> list[tuple[Engram, list[ProposedEdge]]]:
    """Gather edge proposals before opening a write transaction."""
    proposals: list[tuple[Engram, list[ProposedEdge]]] = []
    for engram in engrams:
        try:
            neighbor_pairs = await find_neighbors(db, engram.id)
            if not neighbor_pairs:
                continue
            neighbors = [n for n, _sim in neighbor_pairs]
            proposed = await assign_predicates(llm, engram, neighbors, document_text=document_text)
            proposals.append(
                (
                    engram,
                    [dataclasses.replace(edge, source_document_id=document_id) for edge in proposed],
                )
            )
        except Exception:
            logger.exception("%s: failed to link engram %s (%s)", log_context, engram.id, engram.canonical_name)
    return proposals


async def update_processing_metadata(
    db: aiosqlite.Connection,
    document_id: str,
    metadata: dict[str, object],
    **updates: object,
) -> dict[str, object]:
    processing = metadata.get("processing")
    processing_dict = dict(processing) if isinstance(processing, dict) else {}
    filtered_updates = {key: value for key, value in updates.items() if value is not None}
    if all(processing_dict.get(key) == value for key, value in filtered_updates.items()):
        return metadata
    processing_dict.update(filtered_updates)
    processing_dict["updated_at"] = _now_iso()
    metadata["processing"] = processing_dict
    async with immediate_transaction(db):
        await db.execute(
            "UPDATE documents SET metadata = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (json.dumps(metadata, ensure_ascii=False), document_id),
        )
    return metadata


async def process_document(
    db: aiosqlite.Connection,
    document_id: str,
    llm: LLMClient,
    embeddings: EmbeddingModel,
    *,
    expected_revision: int | None = None,
    tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL,
    progress_callback: Callable[[dict[str, object]], Awaitable[None] | None] | None = None,
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

    effective_tidy_level = _resolve_document_tidy_level(doc, tidy_level)

    # Extract entities + tidy memo
    extraction_text = _build_extraction_text(doc)
    summary_only = doc.source_type in ("file", "url")
    result = await extract_entities(
        llm,
        extraction_text,
        tidy_level=effective_tidy_level,
        source_mime_type=doc.mime_type,
        summary_only=summary_only,
        progress_callback=progress_callback,
    )

    extracted = result.entities
    prepared_engrams = await _prepare_engrams(llm, embeddings, extracted) if extracted else []

    # Post-LLM revision check — before any DB writes
    if not await _check_revision(db, document_id, expected_revision):
        logger.warning(
            "process_document: stale revision after LLM work for %s (expected %s)", document_id, expected_revision
        )
        return []

    async with immediate_transaction(db):
        if result.tidy_title or result.tidy_text:
            await db.execute(
                "UPDATE documents SET tidy_title = ?, tidy_text = ?, tidy_level = ? WHERE id = ?",
                (result.tidy_title, result.tidy_text, effective_tidy_level, document_id),
            )

        if not prepared_engrams:
            await db.execute("UPDATE documents SET processed = 1 WHERE id = ?", (document_id,))
            return []

        engram_map = await _materialize_engrams(db, prepared_engrams)
        engrams = list(engram_map.values())
        for engram in engrams:
            await link_document_engram(db, document_id, engram.id)

        await db.execute("UPDATE documents SET processed = 1 WHERE id = ?", (document_id,))
    return engrams


async def process_pending_documents(
    db: aiosqlite.Connection,
    llm: LLMClient,
    embeddings: EmbeddingModel,
    *,
    limit: int = 50,
    tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL,
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
        results[row["id"]] = await process_document(
            db,
            row["id"],
            llm,
            embeddings,
            tidy_level=tidy_level,
        )
    return results


async def retidy_document(
    db: aiosqlite.Connection,
    document_id: str,
    llm: LLMClient,
    *,
    expected_revision: int | None = None,
    tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL,
) -> bool:
    """Recompute tidy fields without touching ontology state."""
    doc = await _fetch_document(db, document_id)

    if expected_revision is not None and doc.revision != expected_revision:
        logger.warning("retidy_document: stale revision for %s (expected %s)", document_id, expected_revision)
        return False

    effective_tidy_level = _resolve_document_tidy_level(doc, tidy_level)
    result = await render_tidy_text(
        llm,
        doc.text,
        tidy_level=effective_tidy_level,
        source_mime_type=doc.mime_type,
    )

    if not await _check_revision(db, document_id, expected_revision):
        logger.warning(
            "retidy_document: stale revision after LLM work for %s (expected %s)", document_id, expected_revision
        )
        return False

    async with immediate_transaction(db):
        await db.execute(
            "UPDATE documents SET tidy_title = ?, tidy_text = ?, tidy_level = ? WHERE id = ?",
            (result.tidy_title, result.tidy_text, effective_tidy_level, document_id),
        )
    return True


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
        "SELECT e.* FROM engrams e JOIN document_engrams de ON e.id = de.engram_id WHERE de.document_id = ?",
        (document_id,),
    )
    engram_rows = await cursor.fetchall()
    await cursor.close()
    engrams = [Engram.from_row(r) for r in engram_rows]

    if not engrams:
        async with immediate_transaction(db):
            await db.execute("UPDATE documents SET processed = 2 WHERE id = ?", (document_id,))
        return []

    edge_proposals = await _collect_edge_proposals(
        db,
        llm,
        document_id,
        doc.text,
        engrams,
        log_context="link_document",
    )

    # Post-LLM revision check — before committing edges
    if not await _check_revision(db, document_id, expected_revision):
        logger.warning(
            "link_document: stale revision after LLM work for %s (expected %s)", document_id, expected_revision
        )
        return []

    all_edges: list[Edge] = []
    async with immediate_transaction(db):
        for _engram, proposals in edge_proposals:
            for proposal in proposals:
                edge = await create_edge(db, proposal)
                if edge is not None:
                    all_edges.append(edge)
        await db.execute("UPDATE documents SET processed = 2 WHERE id = ?", (document_id,))
    return all_edges


async def revise_document(
    db: aiosqlite.Connection,
    document_id: str,
    llm: LLMClient,
    embeddings: EmbeddingModel,
    *,
    expected_revision: int | None = None,
    tidy_level: TidyLevel = DEFAULT_TIDY_LEVEL,
    progress_callback: Callable[[dict[str, object]], Awaitable[None] | None] | None = None,
) -> tuple[list[Engram], list[Edge]]:
    """Incremental re-extraction after a document revision.

    Re-extracts entities from the current text, diffs the engram set against
    existing document_engrams, and only adds/removes the delta.  If the churn
    exceeds 50% of existing engrams, falls back to a full nuke-and-rebuild to
    maintain edge correctness.

    For unprocessed documents (no existing engrams), delegates to the full
    process_document → link_document path.
    """
    doc = await _fetch_document(db, document_id)

    # Pre-flight revision check
    if expected_revision is not None and doc.revision != expected_revision:
        logger.warning("revise_document: stale revision for %s (expected %s)", document_id, expected_revision)
        return [], []

    # Fetch existing engram IDs for this document
    cursor = await db.execute(
        "SELECT engram_id FROM document_engrams WHERE document_id = ?",
        (document_id,),
    )
    existing_ids = {row["engram_id"] for row in await cursor.fetchall()}
    await cursor.close()

    # No existing engrams — fall through to full extraction
    if not existing_ids:
        logger.info("revise_document: no existing engrams for %s, using full pipeline", document_id)
        async with immediate_transaction(db):
            await db.execute("UPDATE documents SET processed = 0 WHERE id = ?", (document_id,))
        engrams = await process_document(
            db, document_id, llm, embeddings,
            expected_revision=expected_revision,
            tidy_level=tidy_level,
            progress_callback=progress_callback,
        )
        edges = await link_document(db, document_id, llm, expected_revision=expected_revision)
        return engrams, edges

    # Build extraction text (includes annotation for non-scribbles)
    extraction_text = _build_extraction_text(doc)
    effective_tidy_level = _resolve_document_tidy_level(doc, tidy_level)
    summary_only = doc.source_type in ("file", "url")

    result = await extract_entities(
        llm,
        extraction_text,
        tidy_level=effective_tidy_level,
        source_mime_type=doc.mime_type,
        summary_only=summary_only,
        progress_callback=progress_callback,
    )

    prepared_engrams = await _prepare_engrams(llm, embeddings, result.entities) if result.entities else []

    # Post-LLM revision check
    if not await _check_revision(db, document_id, expected_revision):
        logger.warning("revise_document: stale revision after LLM for %s", document_id)
        return [], []

    new_engrams: dict[str, Engram] = {}
    if prepared_engrams:
        async with immediate_transaction(db):
            new_engrams = await _materialize_engrams(db, prepared_engrams)

    new_ids = set(new_engrams.keys())

    # Compute diff
    added_ids = new_ids - existing_ids
    removed_ids = existing_ids - new_ids
    churn = len(added_ids) + len(removed_ids)

    # Fallback check: high churn → full nuke-and-rebuild
    if churn > _INCREMENTAL_FALLBACK_THRESHOLD * max(len(existing_ids), 1):
        logger.info(
            "revise_document: high engram churn (%d/%d) for %s, falling back to full rebuild",
            churn, len(existing_ids), document_id,
        )
        async with immediate_transaction(db):
            await remove_document_associations(db, document_id)
            await db.execute("UPDATE documents SET processed = 0 WHERE id = ?", (document_id,))
        engrams = await process_document(
            db, document_id, llm, embeddings,
            expected_revision=expected_revision,
            tidy_level=tidy_level,
            progress_callback=progress_callback,
        )
        edges = await link_document(db, document_id, llm, expected_revision=expected_revision)
        return engrams, edges

    async with immediate_transaction(db):
        if removed_ids:
            placeholders = ",".join("?" for _ in removed_ids)
            removed_list = list(removed_ids)
            await db.execute(
                f"DELETE FROM document_engrams WHERE document_id = ? AND engram_id IN ({placeholders})",  # noqa: S608
                (document_id, *removed_list),
            )
            await db.execute(
                f"DELETE FROM edges WHERE source_document_id = ? "  # noqa: S608
                f"AND (source_engram_id IN ({placeholders}) OR target_engram_id IN ({placeholders}))",
                (document_id, *removed_list, *removed_list),
            )
        for eid in added_ids:
            await link_document_engram(db, document_id, eid)

        if result.tidy_title or result.tidy_text:
            await db.execute(
                "UPDATE documents SET tidy_title = ?, tidy_text = ?, tidy_level = ? WHERE id = ?",
                (result.tidy_title, result.tidy_text, effective_tidy_level, document_id),
            )

        await db.execute("UPDATE documents SET processed = 1 WHERE id = ?", (document_id,))

    edge_proposals = await _collect_edge_proposals(
        db,
        llm,
        document_id,
        extraction_text,
        [new_engrams[eid] for eid in added_ids],
        log_context="revise_document",
    )

    # Final revision check
    if not await _check_revision(db, document_id, expected_revision):
        logger.warning("revise_document: stale revision after incremental update for %s", document_id)
        return [], []

    all_edges: list[Edge] = []
    async with immediate_transaction(db):
        for _engram, proposals in edge_proposals:
            for proposal in proposals:
                edge = await create_edge(db, proposal)
                if edge is not None:
                    all_edges.append(edge)
        await db.execute("UPDATE documents SET processed = 2 WHERE id = ?", (document_id,))
    return list(new_engrams.values()), all_edges


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
