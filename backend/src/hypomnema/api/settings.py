"""Settings API — manage LLM provider config and API keys."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, FastAPI, HTTPException, Request

from hypomnema.api.deps import AppSettings, DB, FernetKey, LLMLock
from hypomnema.api.schemas import (
    ChangeEmbeddingPayload,
    EmbeddingChangeStatus,
    EmbeddingProviderInfo,
    ProviderInfo,
    ProvidersResponse,
    SettingsResponse,
    SettingsUpdate,
    SetupPayload,
)
from hypomnema.crypto import mask_key
from hypomnema.db.settings_store import get_all_settings, set_setting
from hypomnema.embeddings.factory import EMBEDDING_DEFAULTS, build_embeddings
from hypomnema.llm.factory import api_key_for_provider, base_url_for_provider, build_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

_ENCRYPTED_KEYS = {"anthropic_api_key", "google_api_key", "openai_api_key"}
_VALID_LLM_PROVIDERS = {"claude", "google", "openai", "ollama"}


def _build_response(settings: AppSettings, masked_keys: dict[str, str]) -> SettingsResponse:
    return SettingsResponse(
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        anthropic_api_key=masked_keys.get("anthropic_api_key", mask_key(settings.anthropic_api_key) if settings.anthropic_api_key else ""),
        google_api_key=masked_keys.get("google_api_key", mask_key(settings.google_api_key) if settings.google_api_key else ""),
        openai_api_key=masked_keys.get("openai_api_key", mask_key(settings.openai_api_key) if settings.openai_api_key else ""),
        ollama_base_url=settings.ollama_base_url,
        openai_base_url=settings.openai_base_url,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
    )


@router.get("", response_model=SettingsResponse)
async def get_settings(
    settings: AppSettings,
    db: DB,
) -> SettingsResponse:
    """Return current settings with masked API keys."""
    from hypomnema.db.settings_store import get_all_settings_masked

    db_masked = await get_all_settings_masked(db)
    # Merge: for API key fields, prefer DB masked values if present
    masked_keys: dict[str, str] = {}
    for key in _ENCRYPTED_KEYS:
        if key in db_masked:
            masked_keys[key] = db_masked[key]
    return _build_response(settings, masked_keys)


@router.put("", response_model=SettingsResponse)
async def update_settings(
    body: SettingsUpdate,
    request: Request,
    settings: AppSettings,
    db: DB,
    fernet_key: FernetKey,
    llm_lock: LLMLock,
) -> SettingsResponse:
    """Update LLM-related settings. Hot-swaps the LLM client."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Reject embedding changes
    embedding_fields = {"embedding_provider", "embedding_model", "embedding_dim"}
    if embedding_fields & set(updates):
        raise HTTPException(status_code=400, detail="Embedding config cannot be changed at runtime")

    # Validate LLM provider
    if "llm_provider" in updates and updates["llm_provider"] not in _VALID_LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid LLM provider: {updates['llm_provider']}")

    # Persist each field to DB
    for key, value in updates.items():
        await set_setting(
            db, key, value,
            fernet_key=fernet_key,
            encrypt_value=key in _ENCRYPTED_KEYS,
        )

    # Reload full settings from DB
    db_settings = await get_all_settings(db, fernet_key=fernet_key)

    from hypomnema.config import Settings

    new_settings = Settings.with_db_overrides(settings, db_settings)
    request.app.state.settings = new_settings

    # Hot-swap LLM
    provider = new_settings.llm_provider
    if provider != "mock":
        api_key = api_key_for_provider(provider, new_settings)
        base_url = base_url_for_provider(provider, new_settings)
        new_llm = build_llm(provider, api_key=api_key, model=new_settings.llm_model, base_url=base_url)
        async with llm_lock:
            request.app.state.llm = new_llm

    # Build masked response from already-decrypted settings
    masked_keys = {
        k: mask_key(v) for k, v in db_settings.items() if k in _ENCRYPTED_KEYS and v
    }
    return _build_response(new_settings, masked_keys)


@router.post("/setup", response_model=SettingsResponse)
async def complete_setup(
    body: SetupPayload,
    request: Request,
    settings: AppSettings,
    db: DB,
    fernet_key: FernetKey,
    llm_lock: LLMLock,
) -> SettingsResponse:
    """One-time first-run setup — choose embedding provider and optionally LLM."""
    # 1. Reject if already set up
    cursor = await db.execute("SELECT value FROM settings WHERE key = 'setup_complete'")
    row = await cursor.fetchone()
    await cursor.close()
    if row is not None:
        raise HTTPException(status_code=409, detail="Setup already complete")

    # 2. Determine embedding config
    dim, model = EMBEDDING_DEFAULTS[body.embedding_provider]

    # 3. Store embedding settings (plain text, not encrypted)
    for key, value in [
        ("embedding_provider", body.embedding_provider),
        ("embedding_dim", str(dim)),
        ("embedding_model", model),
    ]:
        await set_setting(db, key, value, fernet_key=fernet_key, encrypt_value=False)

    # 4. Store LLM settings if provided
    if body.llm_provider:
        await set_setting(db, "llm_provider", body.llm_provider, fernet_key=fernet_key, encrypt_value=False)
    if body.anthropic_api_key:
        await set_setting(db, "anthropic_api_key", body.anthropic_api_key, fernet_key=fernet_key, encrypt_value=True)
    if body.google_api_key:
        await set_setting(db, "google_api_key", body.google_api_key, fernet_key=fernet_key, encrypt_value=True)
    if body.openai_api_key:
        await set_setting(db, "openai_api_key", body.openai_api_key, fernet_key=fernet_key, encrypt_value=True)
    if body.ollama_base_url:
        await set_setting(db, "ollama_base_url", body.ollama_base_url, fernet_key=fernet_key, encrypt_value=False)
    if body.openai_base_url:
        await set_setting(db, "openai_base_url", body.openai_base_url, fernet_key=fernet_key, encrypt_value=False)

    # 5. Create vec tables
    from hypomnema.db.schema import create_vec_tables
    await create_vec_tables(db, dim)

    # 6. Reload settings and update app state
    db_settings = await get_all_settings(db, fernet_key=fernet_key)
    from hypomnema.config import Settings
    new_settings = Settings.with_db_overrides(settings, db_settings)
    request.app.state.settings = new_settings

    # 7. Initialize embeddings
    request.app.state.embeddings = build_embeddings(new_settings)

    # 8. Initialize LLM if provider specified
    provider = new_settings.llm_provider
    if provider and provider != "mock":
        async with llm_lock:
            request.app.state.llm = build_llm(
                provider,
                api_key=api_key_for_provider(provider, new_settings),
                model=new_settings.llm_model,
                base_url=base_url_for_provider(provider, new_settings),
            )

    # 9. Start feed scheduler
    from hypomnema.scheduler.cron import FeedScheduler
    scheduler = FeedScheduler(
        new_settings.db_path,
        sqlite_vec_path=new_settings.sqlite_vec_path,
        triage_threshold=new_settings.triage_threshold,
        feed_timeout=new_settings.feed_fetch_timeout,
        embeddings=request.app.state.embeddings,
    )
    await scheduler.load_jobs()
    scheduler.start()
    request.app.state.scheduler = scheduler

    # 10. Mark setup complete
    await set_setting(db, "setup_complete", "1", fernet_key=fernet_key, encrypt_value=False)

    # Build response
    masked_keys = {
        k: mask_key(v) for k, v in db_settings.items() if k in _ENCRYPTED_KEYS and v
    }
    return _build_response(new_settings, masked_keys)


@router.post("/change-embedding", response_model=EmbeddingChangeStatus)
async def change_embedding_provider(
    body: ChangeEmbeddingPayload,
    request: Request,
    settings: AppSettings,
    db: DB,
    fernet_key: FernetKey,
) -> EmbeddingChangeStatus:
    """Change embedding provider — nuclear operation that rebuilds the knowledge graph."""
    # Reject if a change is already in progress
    if request.app.state.embedding_change_status.status == "in_progress":
        raise HTTPException(status_code=409, detail="Embedding change already in progress")

    # Validate API key for cloud providers
    if body.embedding_provider == "openai" and not (body.openai_api_key or settings.openai_api_key):
        raise HTTPException(status_code=400, detail="OpenAI API key required")
    if body.embedding_provider == "google" and not (body.google_api_key or settings.google_api_key):
        raise HTTPException(status_code=400, detail="Google API key required")

    dim, model = EMBEDDING_DEFAULTS[body.embedding_provider]

    # Store new API keys if provided
    if body.openai_api_key:
        await set_setting(db, "openai_api_key", body.openai_api_key, fernet_key=fernet_key, encrypt_value=True)
    if body.google_api_key:
        await set_setting(db, "google_api_key", body.google_api_key, fernet_key=fernet_key, encrypt_value=True)

    # Reset knowledge graph + vec tables
    from hypomnema.db.schema import create_vec_tables, drop_vec_tables, reset_knowledge_graph

    await reset_knowledge_graph(db)
    await drop_vec_tables(db)
    await create_vec_tables(db, dim)

    # Update embedding settings in DB
    for key, value in [
        ("embedding_provider", body.embedding_provider),
        ("embedding_dim", str(dim)),
        ("embedding_model", model),
    ]:
        await set_setting(db, key, value, fernet_key=fernet_key, encrypt_value=False)

    # Reload settings
    db_settings = await get_all_settings(db, fernet_key=fernet_key)
    from hypomnema.config import Settings
    new_settings = Settings.with_db_overrides(settings, db_settings)
    request.app.state.settings = new_settings

    # Reinitialize embeddings
    request.app.state.embeddings = build_embeddings(new_settings)

    # Count documents to reprocess
    cursor = await db.execute("SELECT count(*) FROM documents")
    row = await cursor.fetchone()
    await cursor.close()
    total = row[0] if row else 0

    # Set initial status
    change_status = EmbeddingChangeStatus(status="in_progress", total=total, processed=0)
    request.app.state.embedding_change_status = change_status

    # Kick off background reprocessing (store ref to prevent GC)
    request.app.state.embedding_change_task = asyncio.create_task(
        _reprocess_all_documents(request.app, total)
    )

    return change_status


async def _reprocess_all_documents(app: FastAPI, total: int) -> None:
    """Background task: reprocess all documents through the ontology pipeline."""
    from hypomnema.db.engine import get_connection
    from hypomnema.ontology.pipeline import (
        link_document,
        process_document,
    )

    settings = app.state.settings
    try:
        db = await get_connection(settings.db_path, settings.sqlite_vec_path)
        try:
            llm = app.state.llm
            embeddings = app.state.embeddings

            if llm is None or embeddings is None:
                app.state.embedding_change_status = EmbeddingChangeStatus(
                    status="failed", total=total, processed=0,
                    error="LLM or embedding model not configured",
                )
                return

            # Phase 1: extract engrams
            cursor = await db.execute(
                "SELECT id FROM documents WHERE processed = 0 ORDER BY created_at"
            )
            doc_ids = [row["id"] for row in await cursor.fetchall()]
            await cursor.close()

            processed = 0
            for doc_id in doc_ids:
                try:
                    await process_document(db, doc_id, llm, embeddings)
                except Exception:
                    logger.exception("Error processing document %s", doc_id)
                processed += 1
                app.state.embedding_change_status = EmbeddingChangeStatus(
                    status="in_progress", total=total, processed=processed,
                )

            # Phase 2: link edges
            cursor = await db.execute(
                "SELECT id FROM documents WHERE processed = 1 ORDER BY created_at"
            )
            link_ids = [row["id"] for row in await cursor.fetchall()]
            await cursor.close()

            for doc_id in link_ids:
                try:
                    await link_document(db, doc_id, llm)
                except Exception:
                    logger.exception("Error linking document %s", doc_id)

            app.state.embedding_change_status = EmbeddingChangeStatus(
                status="complete", total=total, processed=total,
            )
        finally:
            await db.close()

    except Exception as exc:
        logger.exception("Embedding change reprocessing failed")
        app.state.embedding_change_status = EmbeddingChangeStatus(
            status="failed", total=total, processed=0, error=str(exc),
        )


@router.get("/embedding-status", response_model=EmbeddingChangeStatus)
async def get_embedding_status(request: Request) -> EmbeddingChangeStatus:
    """Return current embedding change status."""
    return request.app.state.embedding_change_status


@router.get("/providers", response_model=ProvidersResponse)
async def get_providers() -> ProvidersResponse:
    """Return available provider metadata (excludes mock)."""
    return ProvidersResponse(
        llm=[
            ProviderInfo(id="claude", name="Anthropic Claude", requires_key=True, default_model="claude-sonnet-4-20250514"),
            ProviderInfo(id="google", name="Google Gemini", requires_key=True, default_model="gemini-2.0-flash"),
            ProviderInfo(id="openai", name="OpenAI", requires_key=True, default_model="gpt-4o"),
            ProviderInfo(id="ollama", name="Ollama (local)", requires_key=False, default_model="llama3.1"),
        ],
        embedding=[
            EmbeddingProviderInfo(id="local", name="Local (sentence-transformers)", default_dimension=EMBEDDING_DEFAULTS["local"][0], requires_key=False),
            EmbeddingProviderInfo(id="openai", name="OpenAI Embeddings", default_dimension=EMBEDDING_DEFAULTS["openai"][0], requires_key=True),
            EmbeddingProviderInfo(id="google", name="Google Embeddings", default_dimension=EMBEDDING_DEFAULTS["google"][0], requires_key=True),
        ],
    )


