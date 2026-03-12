"""Document endpoints: scribble creation, file upload, listing, detail."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

if TYPE_CHECKING:
    from hypomnema.embeddings.base import EmbeddingModel
    from hypomnema.llm.base import LLMClient

from hypomnema.api.deps import DB, LLM, AppSettings, Embeddings
from hypomnema.api.schemas import DocumentDetail, DocumentOut, PaginatedList, ScribbleCreate
from hypomnema.db.engine import connect
from hypomnema.db.models import Engram
from hypomnema.ingestion.file_parser import UnsupportedFormatError, ingest_file
from hypomnema.ingestion.scribble import create_scribble
from hypomnema.ontology.pipeline import link_document, process_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])


async def _run_ontology_pipeline(
    document_id: str,
    db_path: Path,
    sqlite_vec_path: str,
    llm: LLMClient,
    embeddings: EmbeddingModel,
) -> None:
    """Background task: extract entities and generate edges."""
    async with connect(db_path, sqlite_vec_path) as bg_db:
        try:
            await process_document(bg_db, document_id, llm, embeddings)
            await link_document(bg_db, document_id, llm)
        except Exception:
            logger.exception("Ontology pipeline failed for document %s", document_id)


@router.post("/scribbles", response_model=DocumentOut, status_code=201)
async def create_scribble_endpoint(
    body: ScribbleCreate,
    db: DB,
    llm: LLM,
    embeddings: Embeddings,
    settings: AppSettings,
    background_tasks: BackgroundTasks,
) -> DocumentOut:
    try:
        doc = await create_scribble(db, body.text, title=body.title)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    background_tasks.add_task(
        _run_ontology_pipeline, doc.id, settings.db_path, settings.sqlite_vec_path, llm, embeddings
    )
    return DocumentOut.model_validate(doc, from_attributes=True)


@router.post("/files", response_model=DocumentOut, status_code=201)
async def upload_file_endpoint(
    file: UploadFile,
    db: DB,
    llm: LLM,
    embeddings: Embeddings,
    settings: AppSettings,
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
    background_tasks.add_task(
        _run_ontology_pipeline, doc.id, settings.db_path, settings.sqlite_vec_path, llm, embeddings
    )
    return DocumentOut.model_validate(doc, from_attributes=True)


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
