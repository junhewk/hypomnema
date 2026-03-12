"""Hybrid document search: semantic (embeddings) + lexical (FTS5) with RRF fusion."""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

    from hypomnema.embeddings.base import EmbeddingModel

from hypomnema.db.models import Document
from hypomnema.ontology.engram import embedding_to_bytes, l2_to_cosine


@dataclasses.dataclass(frozen=True)
class ScoredDocument:
    """A document with a relevance score from search."""

    document: Document
    score: float
    match_type: str  # "keyword", "semantic", or "hybrid"


# FTS5 metacharacters and boolean operators to strip
_FTS_META = re.compile(r'["\*\(\):^]')
_FTS_BOOL = re.compile(r"\b(AND|OR|NOT|NEAR)\b", re.IGNORECASE)

_RRF_K = 60  # Standard RRF constant


def _sanitize_fts_query(query: str) -> str | None:
    """Sanitize user input for FTS5 MATCH.

    Strips metacharacters, wraps each token in quotes.
    Returns None if no valid tokens remain.
    """
    cleaned = _FTS_META.sub(" ", query)
    cleaned = _FTS_BOOL.sub(" ", cleaned)
    tokens = cleaned.split()
    if not tokens:
        return None
    return " ".join(f'"{token}"' for token in tokens)


async def keyword_search(
    db: aiosqlite.Connection,
    query: str,
    *,
    limit: int = 20,
) -> list[ScoredDocument]:
    """Full-text search using FTS5 BM25 ranking.

    Returns documents sorted by relevance (best first).
    """
    fts_query = _sanitize_fts_query(query)
    if fts_query is None:
        return []

    cursor = await db.execute(
        "SELECT d.*, f.rank AS fts_rank "
        "FROM documents_fts f "
        "JOIN documents d ON d.rowid = f.rowid "
        "WHERE documents_fts MATCH ? "
        "ORDER BY f.rank "
        "LIMIT ?",
        (fts_query, limit),
    )
    rows = await cursor.fetchall()
    await cursor.close()

    return [
        ScoredDocument(
            document=Document.from_row(row),
            score=abs(row["fts_rank"]),
            match_type="keyword",
        )
        for row in rows
    ]


async def semantic_search(
    db: aiosqlite.Connection,
    query: str,
    embeddings: EmbeddingModel,
    *,
    limit: int = 20,
) -> list[ScoredDocument]:
    """Semantic similarity search using document embeddings.

    Returns documents sorted by cosine similarity (best first).
    """
    vectors = embeddings.embed([query])
    query_bytes = embedding_to_bytes(vectors[0])

    cursor = await db.execute(
        "SELECT document_id, distance FROM document_embeddings "
        "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (query_bytes, limit),
    )
    knn_rows = await cursor.fetchall()
    await cursor.close()

    if not knn_rows:
        return []

    # Batch fetch full document rows
    doc_ids = [r["document_id"] for r in knn_rows]
    placeholders = ",".join("?" for _ in doc_ids)
    cursor = await db.execute(
        f"SELECT * FROM documents WHERE id IN ({placeholders})",  # noqa: S608
        doc_ids,
    )
    doc_rows = await cursor.fetchall()
    await cursor.close()
    doc_map = {r["id"]: r for r in doc_rows}

    results: list[ScoredDocument] = []
    for knn_row in knn_rows:
        doc_row = doc_map.get(knn_row["document_id"])
        if doc_row is None:
            continue
        cosine_sim = l2_to_cosine(knn_row["distance"])
        results.append(ScoredDocument(
            document=Document.from_row(doc_row),
            score=cosine_sim,
            match_type="semantic",
        ))
    return results


def _reciprocal_rank_fusion(
    *result_lists: list[ScoredDocument],
    k: int = _RRF_K,
) -> list[ScoredDocument]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion.

    Each document's fused score = Σ(1 / (k + rank)) across all lists
    where rank is 1-based position in each list.
    """
    scores: dict[str, float] = {}
    best_doc: dict[str, ScoredDocument] = {}
    list_count: dict[str, int] = {}  # how many lists each doc appears in

    for result_list in result_lists:
        seen_in_list: set[str] = set()
        for rank, scored in enumerate(result_list, start=1):
            doc_id = scored.document.id
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            if doc_id not in seen_in_list:
                seen_in_list.add(doc_id)
                list_count[doc_id] = list_count.get(doc_id, 0) + 1
            # Keep the higher-scored version
            if doc_id not in best_doc or scored.score > best_doc[doc_id].score:
                best_doc[doc_id] = scored

    # Sort by fused score descending
    sorted_ids = sorted(scores, key=lambda did: scores[did], reverse=True)
    return [
        dataclasses.replace(
            best_doc[doc_id],
            score=scores[doc_id],
            match_type="hybrid" if list_count[doc_id] > 1
            else best_doc[doc_id].match_type,
        )
        for doc_id in sorted_ids
    ]


async def search_documents(
    db: aiosqlite.Connection,
    query: str,
    embeddings: EmbeddingModel,
    *,
    limit: int = 20,
) -> list[ScoredDocument]:
    """Hybrid search: keyword + semantic, merged via Reciprocal Rank Fusion.

    Runs both searches, fuses results, returns top `limit`.
    """
    # Both are async DB operations — could run concurrently but
    # aiosqlite connections are not concurrency-safe, so run sequentially
    keyword_results = await keyword_search(db, query, limit=limit)
    semantic_results = await semantic_search(db, query, embeddings, limit=limit)

    fused = _reciprocal_rank_fusion(keyword_results, semantic_results)
    return fused[:limit]
