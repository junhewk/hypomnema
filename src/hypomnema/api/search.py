"""Search endpoints: document search, knowledge graph search, and synthesis."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from hypomnema.api.deps import DB, Embeddings
from hypomnema.api.schemas import ScoredDocumentOut
from hypomnema.db.models import Edge
from hypomnema.search.doc_search import search_documents
from hypomnema.search.knowledge_search import get_edges_by_predicate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/documents", response_model=list[ScoredDocumentOut])
async def search_documents_endpoint(q: str, db: DB, embeddings: Embeddings) -> list[ScoredDocumentOut]:
    results = await search_documents(db, q, embeddings)
    return [
        ScoredDocumentOut.model_validate({**result.document.model_dump(mode="python"), "score": result.score})
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


_SYNTHESIS_SYSTEM = """\
You are a research synthesis engine. Given a query and excerpts from multiple \
documents, write a clear, well-structured synthesis that:

- Directly addresses the query
- Draws from and cites the source documents by title
- Notes agreements and tensions between sources
- Identifies gaps or open questions
- Uses concise, factual language

Format as markdown. Keep between 200-600 words."""

_DOC_BUDGET = 2000
_MAX_DOCS = 10


class SynthesizeRequest(BaseModel):
    query: str
    document_ids: list[str]


async def _synthesize_from_docs(
    db: DB, llm: Any, query: str, document_ids: list[str],
) -> str:
    """Core synthesis logic: fetch docs, LLM synthesize, store. Returns new document ID."""
    placeholders = ",".join("?" for _ in document_ids)
    cursor = await db.execute(
        f"SELECT id, title, tidy_title, text, tidy_text FROM documents "  # noqa: S608
        f"WHERE id IN ({placeholders})",
        document_ids,
    )
    docs = [dict(r) for r in await cursor.fetchall()]
    await cursor.close()

    if not docs:
        raise ValueError("No documents found")

    parts = [f'Query: "{query}"\n']
    for i, doc in enumerate(docs[:_MAX_DOCS], 1):
        title = doc.get("tidy_title") or doc.get("title") or "Untitled"
        text = (doc.get("tidy_text") or doc.get("text") or "")[:_DOC_BUDGET]
        parts.append(f"### Source {i}: {title}\n{text}\n")
    parts.append("\nSynthesize a comprehensive answer to the query based on these sources.")

    synthesis_text = await llm.complete("\n".join(parts), system=_SYNTHESIS_SYSTEM)
    synthesis_text = synthesis_text.strip()
    if not synthesis_text:
        raise ValueError("Empty synthesis response")

    title = f"Synthesis: {query[:100]}"
    metadata = json.dumps({"query": query, "source_document_ids": document_ids})

    from hypomnema.db.transactions import immediate_transaction

    async with immediate_transaction(db):
        cursor = await db.execute(
            "INSERT INTO documents (source_type, title, text, metadata) "
            "VALUES ('synthesis', ?, ?, ?) RETURNING *",
            (title, synthesis_text, metadata),
        )
        row = await cursor.fetchone()
        await cursor.close()

    if row is None:
        raise RuntimeError("INSERT RETURNING produced no row")
    return str(row["id"])


@router.post("/synthesize")
async def synthesize_endpoint(body: SynthesizeRequest, db: DB, request: Request) -> dict[str, object]:
    """Synthesize a new document from search results."""
    from nicegui import app

    llm = getattr(app.state, "llm", None)
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM not configured")
    if not body.document_ids:
        raise HTTPException(status_code=400, detail="No document IDs provided")

    try:
        doc_id = await _synthesize_from_docs(db, llm, body.query, body.document_ids)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    queue = getattr(app.state, "ontology_queue", None)
    if queue:
        await queue.enqueue(doc_id)

    return {"status": "ok", "document_id": doc_id}
