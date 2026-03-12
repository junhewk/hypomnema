"""Ontology extraction pipeline: document -> entities -> engrams."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

    from hypomnema.embeddings.base import EmbeddingModel
    from hypomnema.llm.base import LLMClient

from hypomnema.db.models import Document, Engram
from hypomnema.ontology.engram import get_or_create_engram, link_document_engram
from hypomnema.ontology.extractor import extract_entities
from hypomnema.ontology.normalizer import normalize, resolve_synonyms


async def process_document(
    db: aiosqlite.Connection,
    document_id: str,
    llm: LLMClient,
    embeddings: EmbeddingModel,
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
    # Fetch document
    cursor = await db.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise ValueError(f"Document {document_id} not found")
    doc = Document.from_row(row)

    if doc.processed >= 1:
        return []

    # Extract entities
    extracted = await extract_entities(llm, doc.text)
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
        "SELECT id FROM documents WHERE processed = 0 ORDER BY created_at LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    results: dict[str, list[Engram]] = {}
    for row in rows:
        results[row["id"]] = await process_document(db, row["id"], llm, embeddings)
    return results
