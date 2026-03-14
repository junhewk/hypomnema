"""Concept hash, multi-tier engram dedup, and creation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    import aiosqlite
    from numpy.typing import NDArray

from hypomnema.db.models import Engram
from hypomnema.ontology.normalizer import normalize

# Cosine similarity threshold for auto-merge (tuned on unit-normalized embeddings).
_AUTO_MERGE_THRESHOLD = 0.91
_DEFAULT_KNN_LIMIT = 10
_HONORIFIC_SUFFIXES = ("교수님", "박사님", "연구원님", "위원님", "교수", "박사")
_LATIN_GLOSS_RE = re.compile(r"^(?P<base>.+?)\s+\((?P<gloss>[a-z0-9][a-z0-9 .,'/&:+-]*)\)$")
_HANGUL_RE = re.compile(r"[가-힣]")
_LAW_TITLE_SHORTFORM_RE = re.compile(r"^(?P<stem>.+?)(?:및.+?)?에관한법률$")

AliasKind = Literal[
    "canonical_name",
    "stripped_latin_gloss",
    "stripped_honorific",
    "compact_whitespace",
    "english_gloss",
    "legal_shortform",
]
MatchReason = Literal["exact_name", "alias_index", "alias_key", "vector_similarity", "concept_hash"]


@dataclass(frozen=True)
class EngramMatch:
    engram: Engram
    reason: MatchReason
    cosine_similarity: float | None = None


@dataclass(frozen=True)
class EngramAliasEntry:
    alias_key: str
    alias_kind: AliasKind


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


def bytes_to_embedding(data: bytes) -> NDArray[np.float32]:
    """Unpack little-endian float32 binary from sqlite-vec back to numpy array."""
    return np.frombuffer(data, dtype="<f4").copy()


def l2_to_cosine(l2_distance: float) -> float:
    """Convert L2 distance to cosine similarity for unit-normalized vectors."""
    return 1.0 - (l2_distance**2 / 2.0)


def cosine_similarity(
    left: NDArray[np.float32],
    right: NDArray[np.float32],
) -> float:
    """Compute cosine similarity for two embedding vectors."""
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


def compute_alias_keys(name: str) -> tuple[str, ...]:
    """Generate deterministic lexical alias keys for conservative dedupe checks."""
    return tuple(entry.alias_key for entry in _compute_conservative_alias_entries(name))


def compute_index_alias_keys(name: str) -> tuple[str, ...]:
    """Generate persisted alias keys used for direct alias-index lookup."""
    return tuple(entry.alias_key for entry in compute_index_alias_entries(name))


def compute_index_alias_entries(name: str) -> tuple[EngramAliasEntry, ...]:
    """Generate persisted alias entries for direct alias lookup."""
    entries, seen = _compute_base_alias_entries(name)

    normalized = normalize(name)
    stripped_gloss = _strip_latin_gloss(normalized)

    english_gloss = _extract_latin_gloss(normalized)
    if english_gloss is not None:
        _add_alias_entry(entries, seen, english_gloss, "english_gloss")
        _add_compact_alias(entries, seen, english_gloss)

    legal_shortform = _derive_legal_shortform(stripped_gloss)
    if legal_shortform is not None:
        _add_alias_entry(entries, seen, legal_shortform, "legal_shortform")
        _add_compact_alias(entries, seen, legal_shortform)

    return tuple(entries)


def alias_keys_overlap(left: str, right: str) -> bool:
    """Return whether two names share any deterministic alias key."""
    return bool(set(compute_alias_keys(left)) & set(compute_alias_keys(right)))


def _strip_latin_gloss(normalized_name: str) -> str:
    match = _LATIN_GLOSS_RE.match(normalized_name)
    if match is None:
        return normalized_name
    base = match.group("base").strip()
    if not _HANGUL_RE.search(base):
        return normalized_name
    return base


def _strip_honorific_suffix(normalized_name: str) -> str:
    stripped = normalized_name
    for suffix in _HONORIFIC_SUFFIXES:
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)].rstrip()
            break
    return stripped


def _extract_latin_gloss(normalized_name: str) -> str | None:
    match = _LATIN_GLOSS_RE.match(normalized_name)
    if match is None:
        return None
    base = match.group("base").strip()
    if not _HANGUL_RE.search(base):
        return None
    return match.group("gloss").strip()


def _derive_legal_shortform(normalized_name: str) -> str | None:
    compact = re.sub(r"\s+", "", normalized_name)
    match = _LAW_TITLE_SHORTFORM_RE.match(compact)
    if match is None:
        return None
    return f"{match.group('stem')}법"


def _compute_base_alias_entries(name: str) -> tuple[list[EngramAliasEntry], set[str]]:
    """Shared base: canonical + stripped gloss/honorific + compact variants."""
    normalized = normalize(name)
    entries: list[EngramAliasEntry] = []
    seen: set[str] = set()

    stripped_gloss = _strip_latin_gloss(normalized)
    stripped_honorific = _strip_honorific_suffix(stripped_gloss)

    _add_alias_entry(entries, seen, normalized, "canonical_name")
    _add_compact_alias(entries, seen, normalized)

    if stripped_gloss != normalized:
        _add_alias_entry(entries, seen, stripped_gloss, "stripped_latin_gloss")
        _add_compact_alias(entries, seen, stripped_gloss)

    if stripped_honorific and stripped_honorific != stripped_gloss:
        _add_alias_entry(entries, seen, stripped_honorific, "stripped_honorific")
        _add_compact_alias(entries, seen, stripped_honorific)

    return entries, seen


def _compute_conservative_alias_entries(name: str) -> tuple[EngramAliasEntry, ...]:
    entries, _ = _compute_base_alias_entries(name)
    return tuple(entries)


def _add_alias_entry(
    entries: list[EngramAliasEntry],
    seen: set[str],
    alias_key: str,
    alias_kind: AliasKind,
) -> None:
    if not alias_key or alias_key in seen:
        return
    seen.add(alias_key)
    entries.append(EngramAliasEntry(alias_key=alias_key, alias_kind=alias_kind))


def _add_compact_alias(
    entries: list[EngramAliasEntry],
    seen: set[str],
    alias_key: str,
) -> None:
    compact = re.sub(r"\s+", "", alias_key)
    if compact and compact != alias_key:
        _add_alias_entry(entries, seen, compact, "compact_whitespace")


async def store_engram_aliases(
    db: aiosqlite.Connection,
    engram_id: str,
    canonical_name: str,
) -> None:
    """Persist deterministic alias rows for one engram."""
    for entry in compute_index_alias_entries(canonical_name):
        await db.execute(
            "INSERT OR IGNORE INTO engram_aliases (engram_id, alias_key, alias_kind) VALUES (?, ?, ?)",
            (engram_id, entry.alias_key, entry.alias_kind),
        )


async def backfill_engram_aliases(db: aiosqlite.Connection) -> None:
    """Ensure every engram has its persisted alias rows (skips if already populated)."""
    cursor = await db.execute(
        "SELECT e.id, e.canonical_name FROM engrams e "
        "LEFT JOIN engram_aliases ea ON ea.engram_id = e.id "
        "WHERE ea.engram_id IS NULL "
        "ORDER BY e.created_at, e.canonical_name"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    for row in rows:
        await store_engram_aliases(db, str(row["id"]), str(row["canonical_name"]))


async def _match_by_alias_index(
    db: aiosqlite.Connection,
    canonical_name: str,
) -> EngramMatch | None:
    alias_keys = compute_index_alias_keys(canonical_name)
    if not alias_keys:
        return None

    placeholders = ", ".join("?" for _ in alias_keys)
    cursor = await db.execute(
        "SELECT e.* FROM engram_aliases ea "
        "JOIN engrams e ON e.id = ea.engram_id "
        f"WHERE ea.alias_key IN ({placeholders}) "
        "ORDER BY e.created_at, e.canonical_name",
        alias_keys,
    )
    rows = await cursor.fetchall()
    await cursor.close()
    if not rows:
        return None

    matched_rows: dict[str, Engram] = {}
    for row in rows:
        engram = Engram.from_row(row)
        matched_rows.setdefault(engram.id, engram)
    if len(matched_rows) != 1:
        return None
    return EngramMatch(next(iter(matched_rows.values())), "alias_index")


async def match_existing_engram(
    db: aiosqlite.Connection,
    canonical_name: str,
    embedding: NDArray[np.float32],
    *,
    similarity_threshold: float = _AUTO_MERGE_THRESHOLD,
    knn_limit: int = _DEFAULT_KNN_LIMIT,
    use_alias_matching: bool = True,
    use_direct_alias_lookup: bool = True,
) -> EngramMatch | None:
    """Find an existing engram for a candidate according to the dedupe policy."""
    cursor = await db.execute(
        "SELECT * FROM engrams WHERE canonical_name = ?", (canonical_name,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is not None:
        return EngramMatch(Engram.from_row(row), "exact_name")

    if use_alias_matching and use_direct_alias_lookup:
        direct_match = await _match_by_alias_index(db, canonical_name)
        if direct_match is not None:
            return direct_match

    emb_bytes = embedding_to_bytes(embedding)
    cursor = await db.execute(
        "SELECT engram_id, distance FROM engram_embeddings "
        "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (emb_bytes, knn_limit),
    )
    knn_matches = await cursor.fetchall()
    await cursor.close()

    if knn_matches:
        candidate_ids = [match_row["engram_id"] for match_row in knn_matches]
        placeholders = ", ".join("?" for _ in candidate_ids)
        cursor2 = await db.execute(
            f"SELECT * FROM engrams WHERE id IN ({placeholders})", candidate_ids  # noqa: S608
        )
        engram_rows = {row["id"]: Engram.from_row(row) for row in await cursor2.fetchall()}
        await cursor2.close()

        candidate_alias_keys = set(compute_alias_keys(canonical_name)) if use_alias_matching else set()
        for match_row in knn_matches:
            engram = engram_rows.get(match_row["engram_id"])
            if engram is None:
                continue
            cosine_sim = l2_to_cosine(match_row["distance"])
            if candidate_alias_keys and candidate_alias_keys & set(compute_alias_keys(engram.canonical_name)):
                return EngramMatch(engram, "alias_key", cosine_similarity=cosine_sim)
            if cosine_sim >= similarity_threshold:
                return EngramMatch(engram, "vector_similarity", cosine_similarity=cosine_sim)

    concept_hash = compute_concept_hash(embedding)
    cursor = await db.execute(
        "SELECT * FROM engrams WHERE concept_hash = ?", (concept_hash,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is not None:
        return EngramMatch(Engram.from_row(row), "concept_hash")
    return None


async def get_or_create_engram(
    db: aiosqlite.Connection,
    canonical_name: str,
    description: str | None,
    embedding: NDArray[np.float32],
    *,
    similarity_threshold: float = _AUTO_MERGE_THRESHOLD,
    knn_limit: int = _DEFAULT_KNN_LIMIT,
    use_alias_matching: bool = True,
    use_direct_alias_lookup: bool = True,
) -> tuple[Engram, bool]:
    """Multi-tier entity dedup inspired by KGEngram pattern.

    Tiers:
        1. Exact canonical_name match (O(1) index lookup)
        2. Direct alias-index lookup (persisted deterministic alias keys)
        3. Lexical alias match against KNN candidates (titles/glosses/spacing)
        4. Cosine similarity via sqlite-vec KNN (auto-merge if >= threshold)
        5. Concept hash match (belt-and-suspenders catch for UNIQUE safety)
        6. Create new engram + store embedding

    Returns:
        (Engram, created) -- created is True if a new engram was inserted.
    """
    match = await match_existing_engram(
        db,
        canonical_name,
        embedding,
        similarity_threshold=similarity_threshold,
        knn_limit=knn_limit,
        use_alias_matching=use_alias_matching,
        use_direct_alias_lookup=use_direct_alias_lookup,
    )
    if match is not None:
        if match.reason in {"exact_name", "alias_index", "alias_key"}:
            await store_engram_aliases(db, match.engram.id, canonical_name)
        return match.engram, False

    # Tier 6: create new engram + store embedding
    concept_hash = compute_concept_hash(embedding)
    emb_bytes = embedding_to_bytes(embedding)
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
    await store_engram_aliases(db, engram.id, canonical_name)

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
