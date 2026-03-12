"""Search endpoints: document search and knowledge graph search."""

from __future__ import annotations

from fastapi import APIRouter

from hypomnema.api.deps import DB, Embeddings
from hypomnema.api.schemas import ScoredDocumentOut
from hypomnema.db.models import Edge
from hypomnema.search.doc_search import search_documents
from hypomnema.search.knowledge_search import get_edges_by_predicate

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/documents", response_model=list[ScoredDocumentOut])
async def search_documents_endpoint(
    q: str, db: DB, embeddings: Embeddings
) -> list[ScoredDocumentOut]:
    results = await search_documents(db, q, embeddings)
    return [
        ScoredDocumentOut.model_validate(
            {**result.document.model_dump(mode="python"), "score": result.score}
        )
        for result in results
    ]


@router.get("/knowledge", response_model=list[Edge])
async def search_knowledge_endpoint(q: str, db: DB) -> list[Edge]:
    _EDGE_LIMIT = 100

    # Search engrams by canonical_name (only need IDs for edge lookup)
    cursor = await db.execute(
        "SELECT id FROM engrams WHERE canonical_name LIKE ? LIMIT 10",
        (f"%{q}%",),
    )
    rows = await cursor.fetchall()
    await cursor.close()

    if rows:
        # Batch query: fetch edges for all matching engrams in one shot
        engram_ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in engram_ids)
        cursor = await db.execute(
            f"SELECT * FROM edges "  # noqa: S608
            f"WHERE source_engram_id IN ({placeholders}) "
            f"OR target_engram_id IN ({placeholders}) "
            f"ORDER BY confidence DESC LIMIT ?",
            [*engram_ids, *engram_ids, _EDGE_LIMIT],
        )
        edge_rows = await cursor.fetchall()
        await cursor.close()
        return [Edge.from_row(r) for r in edge_rows]

    # Fallback: search by predicate
    return await get_edges_by_predicate(db, q, limit=_EDGE_LIMIT)
