"""Document endpoints: scribble creation, file upload, listing, detail."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hypomnema.llm.base import LLMClient

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, UploadFile

from hypomnema.api.deps import DB
from hypomnema.api.schemas import (
    DocumentDetail,
    DocumentOut,
    DocumentUpdate,
    DocumentWithEngrams,
    EngramSummary,
    RelatedDocument,
    RevisionOut,
    ScribbleCreate,
    UrlFetch,
)
from hypomnema.db.models import Document, Engram
from hypomnema.db.transactions import immediate_transaction
from hypomnema.ingestion.file_parser import UnsupportedFormatError, ingest_file
from hypomnema.ingestion.scribble import create_scribble
from hypomnema.ingestion.url_fetch import DuplicateUrlError, fetch_url
from hypomnema.ontology.pipeline import (
    link_document,
    process_document,
    remove_document_associations,
    revise_document,
    update_processing_metadata,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])

_DRAFT_FILTER = "source_type = 'scribble' AND processed = 0 AND tidy_text IS NULL"


async def snapshot_and_update_document(
    db: DB,
    doc: Document,
    *,
    text: str | None = None,
    title: str | None = None,
    annotation: str | None = None,
) -> Document:
    """Snapshot current state into revision log, apply updates, return updated doc.

    Clears tidy fields and increments revision. Caller is responsible for
    source-type validation and queue enqueue.
    """
    updates: dict[str, object] = {}
    if text is not None:
        updates["text"] = text
    if title is not None:
        updates["title"] = title
    if annotation is not None:
        updates["annotation"] = annotation if annotation.strip() else None
    if not updates:
        return doc
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    async with immediate_transaction(db):
        await db.execute(
            "INSERT INTO document_revisions (document_id, revision, text, annotation, title) "
            "VALUES (?, ?, ?, ?, ?)",
            (doc.id, doc.revision, doc.text, doc.annotation, doc.tidy_title or doc.title),
        )
        cursor = await db.execute(
            f"UPDATE documents SET {set_clause}, tidy_title = NULL, tidy_text = NULL, tidy_level = NULL, "  # noqa: S608
            "revision = revision + 1 WHERE id = ? RETURNING *",
            (*values, doc.id),
        )
        row = await cursor.fetchone()
        await cursor.close()
    if row is None:
        raise ValueError(f"Document {doc.id} not found after update")
    return Document.from_row(row)




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
        result: dict[str, object] = json.loads(raw)
        return result
    return dict(raw)


async def _finalize_pipeline(
    db: DB, document_id: str, metadata: dict[str, object],
    llm: LLMClient | None = None,
) -> str:
    """Shared tail: projections, heat scoring, article synthesis, and final status."""
    from hypomnema.ontology.heat import compute_all_heat
    from hypomnema.visualization.projection import compute_projections

    await update_processing_metadata(db, document_id, metadata, status="running", stage="project", last_error=None)
    await compute_projections(db)
    await compute_all_heat(db)

    # Synthesize articles and cluster overviews
    if llm is not None:
        try:
            from hypomnema.ontology.synthesizer import synthesize_stale_articles

            await update_processing_metadata(
                db, document_id, metadata, status="running", stage="synthesize", last_error=None,
            )
            await synthesize_stale_articles(db, llm, limit=5)
        except Exception:
            logger.exception("Article synthesis failed (non-fatal)")

        try:
            from hypomnema.visualization.cluster_synthesis import synthesize_cluster_overviews

            await synthesize_cluster_overviews(db, llm)
        except Exception:
            logger.exception("Cluster synthesis failed (non-fatal)")

    # Run knowledge graph lint checks
    try:
        from hypomnema.ontology.lint import run_lint

        await run_lint(db)
    except Exception:
        logger.exception("Lint checks failed (non-fatal)")

    processing = metadata.get("processing")
    processing_dict = processing if isinstance(processing, dict) else {}
    has_issues = processing_dict.get("fallback_used") or processing_dict.get("chunk_failed")
    return "partial" if has_issues else "completed"


async def _run_ontology_pipeline(app: FastAPI, document_id: str, revision: int | None = None) -> None:
    """Background task: extract entities, generate edges, and compute projections."""
    db = app.state.db
    llm = app.state.llm
    embeddings = app.state.embeddings
    tidy_level = app.state.settings.tidy_level
    metadata = await _load_document_metadata(db, document_id)

    async def progress_callback(payload: dict[str, object]) -> None:
        await update_processing_metadata(db, document_id, metadata, **payload)

    try:
        await update_processing_metadata(db, document_id, metadata, status="running", stage="extract", last_error=None)
        await process_document(
            db, document_id, llm, embeddings,
            expected_revision=revision, tidy_level=tidy_level, progress_callback=progress_callback,
        )
        await update_processing_metadata(db, document_id, metadata, status="running", stage="link", last_error=None)
        await link_document(db, document_id, llm, expected_revision=revision)
        final_status = await _finalize_pipeline(db, document_id, metadata, llm=llm)
        await update_processing_metadata(db, document_id, metadata, status=final_status, stage="done", last_error=None)
    except Exception as exc:
        await update_processing_metadata(
            db, document_id, metadata, status="failed", stage="failed",
            last_error=f"{type(exc).__name__}: {exc}",
        )
        logger.exception("Ontology pipeline failed for document %s", document_id)


async def _run_revision_pipeline(app: FastAPI, document_id: str, revision: int | None = None) -> None:
    """Background task: incremental re-extraction after a document revision."""
    db = app.state.db
    llm = app.state.llm
    embeddings = app.state.embeddings
    tidy_level = app.state.settings.tidy_level
    metadata = await _load_document_metadata(db, document_id)

    async def progress_callback(payload: dict[str, object]) -> None:
        await update_processing_metadata(db, document_id, metadata, **payload)

    try:
        await update_processing_metadata(db, document_id, metadata, status="running", stage="revise", last_error=None)
        await revise_document(
            db, document_id, llm, embeddings,
            expected_revision=revision, tidy_level=tidy_level, progress_callback=progress_callback,
        )
        final_status = await _finalize_pipeline(db, document_id, metadata, llm=llm)
        await update_processing_metadata(db, document_id, metadata, status=final_status, stage="done", last_error=None)
    except Exception as exc:
        await update_processing_metadata(
            db, document_id, metadata, status="failed", stage="failed",
            last_error=f"{type(exc).__name__}: {exc}",
        )
        logger.exception("Revision pipeline failed for document %s", document_id)


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
    """Update a document's text/title/annotation and re-run ontology pipeline.

    Source-type rules:
    - Scribbles: accept text, title (annotation rejected)
    - Non-scribbles: accept annotation, title (text rejected — original is immutable)
    """
    cursor = await db.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")

    doc = Document.from_row(row)

    # Source-type validation
    if doc.source_type == "scribble" and body.annotation is not None:
        raise HTTPException(status_code=400, detail="Scribbles do not support annotations")
    if doc.source_type != "scribble" and body.text is not None:
        raise HTTPException(status_code=400, detail="Original text is immutable for non-scribble documents")
    if body.text is None and body.title is None and body.annotation is None:
        raise HTTPException(status_code=400, detail="Nothing to update")

    try:
        updated = await snapshot_and_update_document(
            db, doc, text=body.text, title=body.title, annotation=body.annotation,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    updated = await _queue_processing_metadata(db, updated)
    await request.app.state.ontology_queue.enqueue(document_id, updated.revision, incremental=True)
    return DocumentOut.model_validate(updated, from_attributes=True)


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, db: DB) -> Response:
    """Delete a document and clean up all associated data."""
    cursor = await db.execute("SELECT id FROM documents WHERE id = ?", (document_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")

    async with immediate_transaction(db):
        await remove_document_associations(db, document_id)

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
        for table in ("engram_aliases", "projections", "engram_embeddings"):
            await db.execute(f"DELETE FROM {table} WHERE engram_id IN (SELECT id FROM _orphan_engrams)")  # noqa: S608
        await db.execute("DELETE FROM engrams WHERE id IN (SELECT id FROM _orphan_engrams)")
        await db.execute("DROP TABLE IF EXISTS _orphan_engrams")

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
    cursor = await db.execute(f"SELECT COUNT(*) FROM documents WHERE NOT ({_DRAFT_FILTER})")
    row = await cursor.fetchone()
    await cursor.close()
    return {"total": row[0] if row else 0}


@router.get("/drafts", response_model=list[DocumentOut])
async def list_drafts(db: DB) -> list[DocumentOut]:
    cursor = await db.execute(f"SELECT * FROM documents WHERE {_DRAFT_FILTER} ORDER BY updated_at DESC")
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
        "SELECT e.* FROM engrams e JOIN document_engrams de ON e.id = de.engram_id WHERE de.document_id = ?",
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


@router.get("/{document_id}/revisions", response_model=list[RevisionOut])
async def list_revisions(document_id: str, db: DB) -> list[RevisionOut]:
    """List past revisions of a document (newest first)."""
    cursor = await db.execute(
        "SELECT * FROM document_revisions WHERE document_id = ? ORDER BY revision DESC",
        (document_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [RevisionOut(**dict(r)) for r in rows]


@router.get("/{document_id}/revisions/{revision_num}", response_model=RevisionOut)
async def get_revision(document_id: str, revision_num: int, db: DB) -> RevisionOut:
    """Get a specific past revision of a document."""
    cursor = await db.execute(
        "SELECT * FROM document_revisions WHERE document_id = ? AND revision = ?",
        (document_id, revision_num),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Revision not found")
    return RevisionOut(**dict(row))
