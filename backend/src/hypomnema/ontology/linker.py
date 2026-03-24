"""Edge generation: find neighbors, assign predicates, create edges."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import aiosqlite

    from hypomnema.llm.base import LLMClient

from hypomnema.db.models import Edge, Engram
from hypomnema.ontology.engram import l2_to_cosine

VALID_PREDICATES: frozenset[str] = frozenset({
    "is_a",
    "part_of",
    "related_to",
    "contradicts",
    "supports",
    "provides_methodology_for",
    "exemplifies",
    "derives_from",
    "influences",
    "precedes",
    "co_occurs_with",
    "subsumes",
})


@dataclasses.dataclass(frozen=True)
class ProposedEdge:
    """An edge proposed by the LLM before DB insertion."""

    source_engram_id: str
    target_engram_id: str
    predicate: str
    confidence: float = 1.0
    source_document_id: str | None = None


async def find_neighbors(
    db: aiosqlite.Connection,
    engram_id: str,
    *,
    k: int = 10,
    min_similarity: float = 0.5,
) -> list[tuple[Engram, float]]:
    """Find K nearest engrams via sqlite-vec KNN, excluding self.

    Returns list of (Engram, cosine_similarity) sorted by descending similarity.
    """
    # Get the embedding for the source engram
    cursor = await db.execute(
        "SELECT embedding FROM engram_embeddings WHERE engram_id = ?",
        (engram_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return []

    emb_bytes = row["embedding"]

    # KNN query — request k+1 to account for self-match
    cursor = await db.execute(
        "SELECT engram_id, distance FROM engram_embeddings "
        "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (emb_bytes, k + 1),
    )
    knn_rows = await cursor.fetchall()
    await cursor.close()

    # Filter KNN results: exclude self, apply similarity threshold, cap at k
    candidates: list[tuple[str, float]] = []
    for knn_row in knn_rows:
        if knn_row["engram_id"] == engram_id:
            continue
        cosine_sim = l2_to_cosine(knn_row["distance"])
        if cosine_sim < min_similarity:
            continue
        candidates.append((knn_row["engram_id"], cosine_sim))
        if len(candidates) >= k:
            break

    if not candidates:
        return []

    # Batch fetch all engram rows in a single query
    placeholders = ",".join("?" for _ in candidates)
    candidate_ids = [eid for eid, _ in candidates]
    cursor2 = await db.execute(
        f"SELECT * FROM engrams WHERE id IN ({placeholders})",  # noqa: S608
        candidate_ids,
    )
    engram_rows = await cursor2.fetchall()
    await cursor2.close()
    engram_map = {r["id"]: Engram.from_row(r) for r in engram_rows}

    # Reassemble in similarity order
    neighbors: list[tuple[Engram, float]] = []
    for eid, sim in candidates:
        if eid in engram_map:
            neighbors.append((engram_map[eid], sim))
    return neighbors


_DOCUMENT_CONTEXT_MAX_CHARS = 1500

_PREDICATE_SYSTEM = (
    "You are a knowledge graph edge generator. Given a source concept and a list of "
    "target concepts, determine which relationships exist between the source and each target. "
    f"Use ONLY these predicates: {', '.join(sorted(VALID_PREDICATES))}.\n"
    "Return ONLY valid JSON:\n"
    '{"edges": [{"target": "target_name", "predicate": "...", "confidence": 0.0-1.0}]}\n'
    "Only include edges where a meaningful relationship exists. "
    "Omit pairs with no clear relationship."
)


async def assign_predicates(
    llm: LLMClient,
    source: Engram,
    targets: list[Engram],
    *,
    document_text: str | None = None,
) -> list[ProposedEdge]:
    """Ask LLM to assign predicates between source engram and target engrams.

    Returns list of ProposedEdge (only valid predicates included).
    """
    if not targets:
        return []

    target_descriptions = "\n".join(
        f"- {t.canonical_name}: {t.description or 'no description'}"
        for t in targets
    )
    prompt = (
        f"Source concept: {source.canonical_name}\n"
        f"Description: {source.description or 'no description'}\n\n"
        f"Target concepts:\n{target_descriptions}"
    )
    if document_text:
        truncated = document_text[:_DOCUMENT_CONTEXT_MAX_CHARS]
        prompt += f"\n\nContext from source document:\n{truncated}"

    result = await llm.complete_json(prompt, system=_PREDICATE_SYSTEM)
    return _parse_proposed_edges(result, source, targets)


def _parse_proposed_edges(
    data: dict[str, Any],
    source: Engram,
    targets: list[Engram],
) -> list[ProposedEdge]:
    """Parse LLM JSON response into ProposedEdge objects."""
    target_map = {t.canonical_name: t for t in targets}
    raw_edges = data.get("edges", [])
    if not isinstance(raw_edges, list):
        return []

    proposed: list[ProposedEdge] = []
    for item in raw_edges:
        if not isinstance(item, dict):
            continue
        target_name = item.get("target", "").strip()
        predicate = item.get("predicate", "").strip()
        confidence = item.get("confidence", 1.0)
        if target_name not in target_map:
            continue
        if predicate not in VALID_PREDICATES:
            continue
        if not isinstance(confidence, (int, float)):
            confidence = 1.0
        confidence = max(0.0, min(1.0, float(confidence)))
        proposed.append(ProposedEdge(
            source_engram_id=source.id,
            target_engram_id=target_map[target_name].id,
            predicate=predicate,
            confidence=confidence,
        ))
    return proposed


async def create_edge(
    db: aiosqlite.Connection,
    proposed: ProposedEdge,
) -> Edge | None:
    """Insert edge into DB. Returns Edge if created, None if duplicate.

    Uses INSERT OR IGNORE — UNIQUE(source_engram_id, target_engram_id, predicate)
    prevents duplicates.
    """
    cursor = await db.execute(
        "INSERT OR IGNORE INTO edges "
        "(source_engram_id, target_engram_id, predicate, confidence, source_document_id) "
        "VALUES (?, ?, ?, ?, ?) RETURNING *",
        (
            proposed.source_engram_id,
            proposed.target_engram_id,
            proposed.predicate,
            proposed.confidence,
            proposed.source_document_id,
        ),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return Edge.from_row(row)
