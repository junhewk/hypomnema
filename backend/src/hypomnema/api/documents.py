"""Document endpoints: scribble creation, file upload, listing, detail."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request, UploadFile

import httpx

from hypomnema.api.deps import DB
from hypomnema.api.schemas import DocumentDetail, DocumentOut, DocumentUpdate, DocumentWithEngrams, EngramSummary, RelatedDocument, ScribbleCreate, UrlFetch
from hypomnema.db.models import Engram
from hypomnema.ingestion.file_parser import UnsupportedFormatError, ingest_file
from hypomnema.ingestion.scribble import create_scribble
from hypomnema.ingestion.url_fetch import DuplicateUrlError, fetch_url
from hypomnema.ontology.pipeline import link_document, process_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])

# Draft = scribble that was never processed (no tidy_text yet)
_DRAFT_FILTER = "source_type = 'scribble' AND processed = 0 AND tidy_text IS NULL"


async def _run_ontology_pipeline(app: FastAPI, document_id: str, revision: int | None = None) -> None:
    """Background task: extract entities, generate edges, and compute projections.

    Uses the app's shared database connection to avoid SQLite write-lock contention.
    """
    db = app.state.db
    llm = app.state.llm
    embeddings = app.state.embeddings
    try:
        await process_document(db, document_id, llm, embeddings, expected_revision=revision)
        await link_document(db, document_id, llm, expected_revision=revision)

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
    if not body.draft:
        background_tasks.add_task(_run_ontology_pipeline, request.app, doc.id)
    return DocumentOut.model_validate(doc, from_attributes=True)


@router.post("/urls", response_model=DocumentOut, status_code=201)
async def fetch_url_endpoint(
    body: UrlFetch,
    request: Request,
    db: DB,
    background_tasks: BackgroundTasks,
) -> DocumentOut:
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    try:
        doc = await fetch_url(db, body.url)
    except DuplicateUrlError as e:
        raise HTTPException(status_code=409, detail=f"URL already fetched (doc {e.existing_id})") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {e}") from e
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
        "revision = revision + 1, updated_at = datetime('now') WHERE id = ? RETURNING *",
        (*values, document_id),
    )
    updated_row = await cursor.fetchone()
    await cursor.close()

    # Clean up old associations
    await db.execute("DELETE FROM document_engrams WHERE document_id = ?", (document_id,))
    await db.execute("DELETE FROM document_embeddings WHERE document_id = ?", (document_id,))
    await db.execute("DELETE FROM edges WHERE source_document_id = ?", (document_id,))
    await db.commit()

    # Re-run ontology pipeline in background with current revision
    revision = updated_row["revision"]
    background_tasks.add_task(_run_ontology_pipeline, request.app, document_id, revision)

    return DocumentOut(**dict(updated_row))


@router.get("", response_model=list[DocumentWithEngrams])
async def list_documents(db: DB, days: int = 14) -> list[DocumentWithEngrams]:
    cursor = await db.execute(
        "SELECT d.*, group_concat(e.id || '\x1f' || e.canonical_name, '\x1e') AS engram_agg "
        "FROM documents d "
        "LEFT JOIN document_engrams de ON d.id = de.document_id "
        "LEFT JOIN engrams e ON de.engram_id = e.id "
        "WHERE d.created_at >= datetime('now', ? || ' days') "
        f"AND NOT ({_DRAFT_FILTER}) "
        "GROUP BY d.id "
        "ORDER BY d.created_at DESC",
        (str(-days),),
    )
    rows = await cursor.fetchall()
    await cursor.close()

    result: list[DocumentWithEngrams] = []
    for r in rows:
        data = dict(r)
        engram_agg = data.pop("engram_agg", None)
        engrams: list[EngramSummary] = []
        if engram_agg:
            for pair in engram_agg.split("\x1e"):
                eid, cname = pair.split("\x1f", 1)
                engrams.append(EngramSummary(id=eid, canonical_name=cname))
        data["engrams"] = engrams
        result.append(DocumentWithEngrams(**data))
    return result


@router.get("/count")
async def get_document_count(db: DB) -> dict[str, int]:
    """Return total document count excluding drafts."""
    cursor = await db.execute(
        f"SELECT COUNT(*) FROM documents WHERE NOT ({_DRAFT_FILTER})"
    )
    row = await cursor.fetchone()
    await cursor.close()
    return {"total": row[0] if row else 0}


@router.get("/drafts", response_model=list[DocumentOut])
async def list_drafts(db: DB) -> list[DocumentOut]:
    cursor = await db.execute(
        f"SELECT * FROM documents WHERE {_DRAFT_FILTER} ORDER BY updated_at DESC"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [DocumentOut(**dict(r)) for r in rows]


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
