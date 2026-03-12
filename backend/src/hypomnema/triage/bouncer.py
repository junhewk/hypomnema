"""Triage bouncer: cheap embedding-based relevance filter for automated feeds."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

    from hypomnema.embeddings.base import EmbeddingModel

from hypomnema.ontology.engram import embedding_to_bytes, l2_to_cosine


async def triage_document(
    db: aiosqlite.Connection,
    document_id: str,
    embeddings: EmbeddingModel,
    *,
    threshold: float = 0.3,
) -> bool:
    """Evaluate document relevance via embedding similarity to existing engrams.

    Returns True if accepted, False if rejected.

    Logic:
        1. Skip if already triaged (return existing decision)
        2. If no engrams exist (bootstrap), auto-accept
        3. Embed document text, query top-1 nearest engram
        4. Accept if cosine_similarity >= threshold, reject otherwise
        5. Store document embedding in document_embeddings regardless

    Raises:
        ValueError: If document_id not found.
    """
    cursor = await db.execute(
        "SELECT id, text, triaged FROM documents WHERE id = ?", (document_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise ValueError(f"Document {document_id} not found")

    # Already triaged — return existing decision
    if row["triaged"] != 0:
        return bool(row["triaged"] == 1)

    text: str = row["text"]

    # Bootstrap: if no engrams exist, auto-accept
    cursor = await db.execute("SELECT COUNT(*) AS cnt FROM engrams")
    count_row = await cursor.fetchone()
    await cursor.close()
    assert count_row is not None  # COUNT(*) always returns a row
    engram_count: int = count_row["cnt"]

    # Embed document text
    vectors = embeddings.embed([text])
    emb_bytes = embedding_to_bytes(vectors[0])

    if engram_count == 0:
        accepted = True
    else:
        # Top-1 KNN against engram embeddings
        cursor = await db.execute(
            "SELECT engram_id, distance FROM engram_embeddings "
            "WHERE embedding MATCH ? AND k = 1 ORDER BY distance",
            (emb_bytes,),
        )
        knn_row = await cursor.fetchone()
        await cursor.close()
        if knn_row is None:
            accepted = True  # No embeddings stored yet
        else:
            cosine_sim = l2_to_cosine(knn_row["distance"])
            accepted = cosine_sim >= threshold

    # Update triaged flag
    triaged_value = 1 if accepted else -1
    await db.execute(
        "UPDATE documents SET triaged = ? WHERE id = ?",
        (triaged_value, document_id),
    )

    # Store document embedding
    await db.execute(
        "INSERT OR IGNORE INTO document_embeddings (document_id, embedding) "
        "VALUES (?, ?)",
        (document_id, emb_bytes),
    )

    await db.commit()
    return accepted


async def triage_pending_documents(
    db: aiosqlite.Connection,
    embeddings: EmbeddingModel,
    *,
    threshold: float = 0.3,
    source_type: str | None = "feed",
    limit: int = 50,
) -> dict[str, bool]:
    """Batch-triage documents with triaged=0.

    Args:
        source_type: If set, only triage docs with this source_type.
                     Default "feed" -- only triage automated feed docs.
                     Pass None to triage all untriaged docs.
        limit: Max documents to process.

    Returns dict mapping document_id -> accepted (bool).
    """
    query = "SELECT id FROM documents WHERE triaged = 0"
    params: list[str | int] = []
    if source_type is not None:
        query += " AND source_type = ?"
        params.append(source_type)
    query += " ORDER BY created_at LIMIT ?"
    params.append(limit)
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    await cursor.close()
    results: dict[str, bool] = {}
    for row in rows:
        results[row["id"]] = await triage_document(
            db, row["id"], embeddings, threshold=threshold
        )
    return results
