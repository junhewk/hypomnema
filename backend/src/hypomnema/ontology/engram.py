"""Concept hash, multi-tier engram dedup, and creation."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import aiosqlite
    from numpy.typing import NDArray

from hypomnema.db.models import Engram

# Cosine similarity threshold for auto-merge (tuned on unit-normalized embeddings).
_AUTO_MERGE_THRESHOLD = 0.92


def compute_concept_hash(embedding: NDArray[np.float32]) -> str:
    """Binarize embedding by sign -> SHA-256 hash the packed bits.

    Coarse LSH: embeddings with same sign pattern collide.
    Used as UNIQUE safeguard in DB, not primary dedup.
    """
    bits = (embedding >= 0).astype(np.uint8)
    packed = np.packbits(bits).tobytes()
    return hashlib.sha256(packed).hexdigest()


def embedding_to_bytes(embedding: NDArray[np.float32]) -> bytes:
    """Pack float32 array into little-endian binary for sqlite-vec."""
    return np.asarray(embedding, dtype="<f4").tobytes()


def l2_to_cosine(l2_distance: float) -> float:
    """Convert L2 distance to cosine similarity for unit-normalized vectors."""
    return 1.0 - (l2_distance**2 / 2.0)


async def get_or_create_engram(
    db: aiosqlite.Connection,
    canonical_name: str,
    description: str | None,
    embedding: NDArray[np.float32],
    *,
    similarity_threshold: float = _AUTO_MERGE_THRESHOLD,
) -> tuple[Engram, bool]:
    """Multi-tier entity dedup inspired by KGEngram pattern.

    Tiers:
        1. Exact canonical_name match (O(1) index lookup)
        2. Cosine similarity via sqlite-vec KNN (auto-merge if >= threshold)
        3. Concept hash match (belt-and-suspenders catch for UNIQUE safety)
        4. Create new engram + store embedding

    Returns:
        (Engram, created) -- created is True if a new engram was inserted.
    """
    # Tier 1: exact name match
    cursor = await db.execute(
        "SELECT * FROM engrams WHERE canonical_name = ?", (canonical_name,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is not None:
        return Engram.from_row(row), False

    # Tier 2: cosine similarity via sqlite-vec KNN
    emb_bytes = embedding_to_bytes(embedding)
    cursor = await db.execute(
        "SELECT engram_id, distance FROM engram_embeddings "
        "WHERE embedding MATCH ? AND k = 5 ORDER BY distance",
        (emb_bytes,),
    )
    knn_matches = await cursor.fetchall()
    await cursor.close()
    for match_row in knn_matches:
        cosine_sim = l2_to_cosine(match_row["distance"])
        if cosine_sim >= similarity_threshold:
            cursor2 = await db.execute(
                "SELECT * FROM engrams WHERE id = ?", (match_row["engram_id"],)
            )
            engram_row = await cursor2.fetchone()
            await cursor2.close()
            if engram_row is not None:
                return Engram.from_row(engram_row), False

    # Tier 3: concept hash check (catches cases KNN missed due to k limit)
    concept_hash = compute_concept_hash(embedding)
    cursor = await db.execute(
        "SELECT * FROM engrams WHERE concept_hash = ?", (concept_hash,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is not None:
        return Engram.from_row(row), False

    # Tier 4: create new engram + store embedding
    cursor = await db.execute(
        "INSERT INTO engrams (canonical_name, concept_hash, description) "
        "VALUES (?, ?, ?) RETURNING *",
        (canonical_name, concept_hash, description),
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    engram = Engram.from_row(row)

    await db.execute(
        "INSERT INTO engram_embeddings (engram_id, embedding) VALUES (?, ?)",
        (engram.id, emb_bytes),
    )

    return engram, True


async def link_document_engram(
    db: aiosqlite.Connection,
    document_id: str,
    engram_id: str,
) -> None:
    """Create document_engrams junction entry. Idempotent via INSERT OR IGNORE."""
    await db.execute(
        "INSERT OR IGNORE INTO document_engrams (document_id, engram_id) VALUES (?, ?)",
        (document_id, engram_id),
    )
