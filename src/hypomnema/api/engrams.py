"""Engram endpoints: listing, detail, cluster, delete."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from starlette.responses import Response

if TYPE_CHECKING:
    import sqlite3

from hypomnema.api.deps import DB
from hypomnema.api.schemas import DocumentOut, EngramDetail, PaginatedList
from hypomnema.db.models import Engram
from hypomnema.db.transactions import immediate_transaction
from hypomnema.search.knowledge_search import get_edges_for_engram

router = APIRouter(prefix="/api/engrams", tags=["engrams"])

_DOCS_FOR_ENGRAM_SQL = (
    "SELECT d.* FROM documents d JOIN document_engrams de ON d.id = de.document_id WHERE de.engram_id = ?"
)


async def _fetch_docs_for_engram(db: DB, engram_id: str) -> list[sqlite3.Row]:
    cursor = await db.execute(_DOCS_FOR_ENGRAM_SQL, (engram_id,))
    rows = await cursor.fetchall()
    await cursor.close()
    return list(rows)


@router.get("", response_model=PaginatedList[Engram])
async def list_engrams(db: DB, offset: int = 0, limit: int = 20) -> PaginatedList[Engram]:
    cursor = await db.execute("SELECT COUNT(*) FROM engrams")
    row = await cursor.fetchone()
    await cursor.close()
    total = row[0] if row else 0

    cursor = await db.execute(
        "SELECT * FROM engrams ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = await cursor.fetchall()
    await cursor.close()

    return PaginatedList(
        items=[Engram.from_row(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{engram_id}", response_model=EngramDetail)
async def get_engram(engram_id: str, db: DB) -> EngramDetail:
    cursor = await db.execute("SELECT * FROM engrams WHERE id = ?", (engram_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Engram not found")

    edges = await get_edges_for_engram(db, engram_id)
    doc_rows = await _fetch_docs_for_engram(db, engram_id)

    engram_data = dict(row)
    engram_data["edges"] = edges
    engram_data["documents"] = [DocumentOut(**dict(r)) for r in doc_rows]
    return EngramDetail.model_validate(engram_data)


@router.post("/{engram_id}/article/regenerate")
async def regenerate_article(engram_id: str, db: DB) -> dict[str, object]:
    """Force-regenerate the synthesized article for an engram."""
    from nicegui import app

    cursor = await db.execute("SELECT id FROM engrams WHERE id = ?", (engram_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Engram not found")

    llm = getattr(app.state, "llm", None)
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM not configured")

    from hypomnema.ontology.synthesizer import synthesize_engram_article

    article = await synthesize_engram_article(db, llm, engram_id)
    return {"status": "ok", "article": article}


@router.get("/{engram_id}/cluster", response_model=list[DocumentOut])
async def get_engram_cluster(engram_id: str, db: DB) -> list[DocumentOut]:
    # Verify engram exists
    cursor = await db.execute("SELECT id FROM engrams WHERE id = ?", (engram_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Engram not found")

    doc_rows = await _fetch_docs_for_engram(db, engram_id)
    return [DocumentOut(**dict(r)) for r in doc_rows]


@router.delete("/{engram_id}", status_code=204)
async def delete_engram(engram_id: str, db: DB) -> Response:
    """Delete an engram and cascade to all related tables."""
    cursor = await db.execute("SELECT id FROM engrams WHERE id = ?", (engram_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Engram not found")

    async with immediate_transaction(db):
        await db.execute("DELETE FROM document_engrams WHERE engram_id = ?", (engram_id,))
        await db.execute(
            "DELETE FROM edges WHERE source_engram_id = ? OR target_engram_id = ?",
            (engram_id, engram_id),
        )
        for table in ("engram_aliases", "projections", "engram_embeddings"):
            await db.execute(f"DELETE FROM {table} WHERE engram_id = ?", (engram_id,))  # noqa: S608
        await db.execute("DELETE FROM engrams WHERE id = ?", (engram_id,))
        # Auto-resolve lint issues referencing this engram
        await db.execute(
            "UPDATE lint_issues SET resolved = 1 WHERE resolved = 0 AND engram_ids LIKE ?",
            (f"%{engram_id}%",),
        )

    return Response(status_code=204)
