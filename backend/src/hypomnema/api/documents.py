"""Document endpoints: scribble creation, file upload, listing, detail."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request, UploadFile

from hypomnema.api.deps import DB
from hypomnema.api.schemas import DocumentDetail, DocumentOut, DocumentUpdate, PaginatedList, RelatedDocument, ScribbleCreate
from hypomnema.db.models import Engram
from hypomnema.ingestion.file_parser import UnsupportedFormatError, ingest_file
from hypomnema.ingestion.scribble import create_scribble
from hypomnema.ontology.pipeline import link_document, process_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])


async def _run_ontology_pipeline(app: FastAPI, document_id: str) -> None:
    """Background task: extract entities, generate edges, and compute projections.

    Uses the app's shared database connection to avoid SQLite write-lock contention.
    """
    db = app.state.db
    llm = app.state.llm
    embeddings = app.state.embeddings
    try:
        await process_document(db, document_id, llm, embeddings)
        await link_document(db, document_id, llm)

        # Auto-compute projections so viz is immediately available
        from hypomnema.visualization.projection import compute_projections

        await compute_projections(db)
    except Exception:
        logger.exception("Ontology pipeline failed for document %s", document_id)


@router.post("/scribbles", response_model=DocumentOut, status_code=201)
async def create_scribble_endpoint(
    body: ScribbleCreate,
    request: Request,
    db: DB,
    background_tasks: BackgroundTasks,
) -> DocumentOut:
    try:
        doc = await create_scribble(db, body.text, title=body.title)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    background_tasks.add_task(_run_ontology_pipeline, request.app, doc.id)
    return DocumentOut.model_validate(doc, from_attributes=True)


@router.post("/files", response_model=DocumentOut, status_code=201)
async def upload_file_endpoint(
    file: UploadFile,
    request: Request,
    db: DB,
    background_tasks: BackgroundTasks,
) -> DocumentOut:
    suffix = Path(file.filename or "upload").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        doc = await ingest_file(db, tmp_path)
    except (UnsupportedFormatError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)
    background_tasks.add_task(_run_ontology_pipeline, request.app, doc.id)
    return DocumentOut.model_validate(doc, from_attributes=True)


@router.patch("/{document_id}", response_model=DocumentOut)
async def update_document(
    document_id: str,
    body: DocumentUpdate,
    request: Request,
    db: DB,
    background_tasks: BackgroundTasks,
) -> DocumentOut:
    """Update a document's text/title and re-run ontology pipeline."""
    cursor = await db.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if body.text is None and body.title is None:
        raise HTTPException(status_code=400, detail="Nothing to update")

    # Build update
    updates: dict[str, object] = {}
    if body.text is not None:
        updates["text"] = body.text
    if body.title is not None:
        updates["title"] = body.title

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    cursor = await db.execute(
        f"UPDATE documents SET {set_clause}, processed = 0, tidy_title = NULL, tidy_text = NULL, "  # noqa: S608
        "updated_at = datetime('now') WHERE id = ? RETURNING *",
        (*values, document_id),
    )
    updated_row = await cursor.fetchone()
    await cursor.close()

    # Clean up old associations
    await db.execute("DELETE FROM document_engrams WHERE document_id = ?", (document_id,))
    await db.execute("DELETE FROM document_embeddings WHERE document_id = ?", (document_id,))
    await db.execute("DELETE FROM edges WHERE source_document_id = ?", (document_id,))
    await db.commit()

    # Re-run ontology pipeline in background
    background_tasks.add_task(_run_ontology_pipeline, request.app, document_id)

    return DocumentOut(**dict(updated_row))


@router.get("", response_model=PaginatedList[DocumentOut])
async def list_documents(db: DB, offset: int = 0, limit: int = 20) -> PaginatedList[DocumentOut]:
    cursor = await db.execute("SELECT COUNT(*) FROM documents")
    row = await cursor.fetchone()
    await cursor.close()
    total = row[0] if row else 0

    cursor = await db.execute(
        "SELECT * FROM documents ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = await cursor.fetchall()
    await cursor.close()

    return PaginatedList[DocumentOut](
        items=[DocumentOut(**dict(r)) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: str, db: DB) -> DocumentDetail:
    cursor = await db.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Fetch linked engrams
    cursor = await db.execute(
        "SELECT e.* FROM engrams e "
        "JOIN document_engrams de ON e.id = de.engram_id "
        "WHERE de.document_id = ?",
        (document_id,),
    )
    engram_rows = await cursor.fetchall()
    await cursor.close()

    doc_data = dict(row)
    doc_data["engrams"] = [Engram.from_row(r) for r in engram_rows]
    return DocumentDetail.model_validate(doc_data)


@router.get("/{document_id}/related", response_model=list[RelatedDocument])
async def get_related_documents(document_id: str, db: DB) -> list[RelatedDocument]:
    """Get documents that share engrams with the given document."""
    cursor = await db.execute(
        "SELECT DISTINCT d.id, d.tidy_title, d.title "
        "FROM document_engrams de1 "
        "JOIN document_engrams de2 ON de1.engram_id = de2.engram_id "
        "JOIN documents d ON de2.document_id = d.id "
        "WHERE de1.document_id = ? AND de2.document_id != ? "
        "ORDER BY d.created_at DESC",
        (document_id, document_id),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [RelatedDocument(id=r["id"], title=r["tidy_title"] or r["title"]) for r in rows]
