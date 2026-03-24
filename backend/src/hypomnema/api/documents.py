"""Document endpoints: scribble creation, file upload, listing, detail."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, UploadFile

import httpx

from hypomnema.api.deps import DB
from hypomnema.api.schemas import DocumentDetail, DocumentOut, DocumentUpdate, DocumentWithEngrams, EngramSummary, RelatedDocument, ScribbleCreate, UrlFetch
from hypomnema.db.models import Document, Engram
from hypomnema.ingestion.file_parser import UnsupportedFormatError, ingest_file
from hypomnema.ingestion.scribble import create_scribble
from hypomnema.ingestion.url_fetch import DuplicateUrlError, fetch_url
from hypomnema.ontology.pipeline import link_document, process_document, update_processing_metadata

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])

_DRAFT_FILTER = "source_type = 'scribble' AND processed = 0 AND tidy_text IS NULL"


async def _remove_document_associations(db: DB, document_id: str) -> None:
    """Delete engram links, embeddings, and edges tied to a document."""
    await db.execute("DELETE FROM document_engrams WHERE document_id = ?", (document_id,))
    await db.execute("DELETE FROM document_embeddings WHERE document_id = ?", (document_id,))
    await db.execute("DELETE FROM edges WHERE source_document_id = ?", (document_id,))


async def _queue_processing_metadata(db: DB, doc: Document) -> Document:
    metadata = dict(doc.metadata or {})
    await update_processing_metadata(
        db,
        doc.id,
        metadata,
        status="queued",
        stage="queued",
        source_profile="pdf" if doc.mime_type == "application/pdf" else "default",
        chunk_total=0,
        chunk_completed=0,
        chunk_failed=0,
        retry_count=0,
        fallback_used=False,
        last_error=None,
    )
    doc.metadata = metadata
    return doc


async def _load_document_metadata(db: DB, document_id: str) -> dict[str, object]:
    cursor = await db.execute("SELECT metadata FROM documents WHERE id = ?", (document_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None or row["metadata"] is None:
        return {}
    raw = row["metadata"]
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)


async def _run_ontology_pipeline(app: FastAPI, document_id: str, revision: int | None = None) -> None:
    """Background task: extract entities, generate edges, and compute projections.

    Uses the app's shared database connection to avoid SQLite write-lock contention.
    """
    db = app.state.db
    llm = app.state.llm
    embeddings = app.state.embeddings
    tidy_level = app.state.settings.tidy_level
    metadata = await _load_document_metadata(db, document_id)

    async def progress_callback(payload: dict[str, object]) -> None:
        await update_processing_metadata(db, document_id, metadata, **payload)

    try:
        await update_processing_metadata(
            db,
            document_id,
            metadata,
            status="running",
            stage="extract",
            last_error=None,
        )
        await process_document(
            db,
            document_id,
            llm,
            embeddings,
            expected_revision=revision,
            tidy_level=tidy_level,
            progress_callback=progress_callback,
        )
        await update_processing_metadata(
            db,
            document_id,
            metadata,
            status="running",
            stage="link",
            last_error=None,
        )
        await link_document(db, document_id, llm, expected_revision=revision)
        await update_processing_metadata(
            db,
            document_id,
            metadata,
            status="running",
            stage="project",
            last_error=None,
        )

        # Auto-compute projections so viz is immediately available
        from hypomnema.visualization.projection import compute_projections

        await compute_projections(db)
        processing = metadata.get("processing", {})
        final_status = "partial" if processing.get("fallback_used") or processing.get("chunk_failed") else "completed"
        await update_processing_metadata(
            db,
            document_id,
            metadata,
            status=final_status,
            stage="done",
            last_error=None,
        )
    except Exception as exc:
        await update_processing_metadata(
            db,
            document_id,
            metadata,
            status="failed",
            stage="failed",
            last_error=f"{type(exc).__name__}: {exc}",
        )
        logger.exception("Ontology pipeline failed for document %s", document_id)


@router.post("/scribbles", response_model=DocumentOut, status_code=201)
async def create_scribble_endpoint(
    body: ScribbleCreate,
    request: Request,
    db: DB,
) -> DocumentOut:
    try:
        doc = await create_scribble(db, body.text, title=body.title)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not body.draft:
        doc = await _queue_processing_metadata(db, doc)
        await request.app.state.ontology_queue.enqueue(doc.id)
    return DocumentOut.model_validate(doc, from_attributes=True)


@router.post("/urls", response_model=DocumentOut, status_code=201)
async def fetch_url_endpoint(
    body: UrlFetch,
    request: Request,
    db: DB,
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
    doc = await _queue_processing_metadata(db, doc)
    await request.app.state.ontology_queue.enqueue(doc.id)
    return DocumentOut.model_validate(doc, from_attributes=True)


@router.post("/files", response_model=DocumentOut, status_code=201)
async def upload_file_endpoint(
    file: UploadFile,
    request: Request,
    db: DB,
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
    doc = await _queue_processing_metadata(db, doc)
    await request.app.state.ontology_queue.enqueue(doc.id)
    return DocumentOut.model_validate(doc, from_attributes=True)


@router.patch("/{document_id}", response_model=DocumentOut)
async def update_document(
    document_id: str,
    body: DocumentUpdate,
    request: Request,
    db: DB,
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
        f"UPDATE documents SET {set_clause}, processed = 0, tidy_title = NULL, tidy_text = NULL, tidy_level = NULL, "  # noqa: S608
        "revision = revision + 1, updated_at = datetime('now') WHERE id = ? RETURNING *",
        (*values, document_id),
    )
    updated_row = await cursor.fetchone()
    await cursor.close()

    await _remove_document_associations(db, document_id)
    await db.commit()

    doc = await _queue_processing_metadata(db, Document.from_row(updated_row))

    revision = updated_row["revision"]
    await request.app.state.ontology_queue.enqueue(document_id, revision)

    return DocumentOut.model_validate(doc, from_attributes=True)


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, db: DB) -> Response:
    """Delete a document and clean up all associated data."""
    cursor = await db.execute("SELECT id FROM documents WHERE id = ?", (document_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")

    await _remove_document_associations(db, document_id)

    # FTS cleanup handled by trigger
    await db.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    # Garbage-collect orphaned engrams: materialize IDs once, delete from all tables
    await db.execute("DROP TABLE IF EXISTS _orphan_engrams")
    await db.execute("""
        CREATE TEMP TABLE _orphan_engrams AS
        SELECT e.id FROM engrams e
        LEFT JOIN document_engrams de ON e.id = de.engram_id
        LEFT JOIN edges src ON e.id = src.source_engram_id
        LEFT JOIN edges tgt ON e.id = tgt.target_engram_id
        WHERE de.document_id IS NULL AND src.id IS NULL AND tgt.id IS NULL
    """)
    for table in ("engram_aliases", "projections", "engram_embeddings", "engrams"):
        await db.execute(f"DELETE FROM {table} WHERE engram_id IN (SELECT id FROM _orphan_engrams)")  # noqa: S608
    await db.execute("DROP TABLE IF EXISTS _orphan_engrams")
    await db.commit()

    return Response(status_code=204)


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
