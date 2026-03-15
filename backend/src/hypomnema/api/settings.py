"""Settings API — manage LLM provider config and API keys."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, FastAPI, HTTPException, Request

from hypomnema.api.deps import AppSettings, DB, FernetKey, LLMLock
from hypomnema.api.schemas import (
    ChangeEmbeddingPayload,
    ConnectivityCheck,
    ConnectivityCheckResponse,
    EmbeddingChangeStatus,
    EmbeddingProviderInfo,
    ModelOption,
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
_BASE_LLM_PROVIDER = "google"
_BASE_LLM_MODEL = "gemini-2.5-flash"
_LLM_MODELS: dict[str, list[ModelOption]] = {
    "claude": [
        ModelOption(id="claude-sonnet-4-20250514", name="Claude Sonnet 4"),
        ModelOption(id="claude-3-5-haiku-20241022", name="Claude 3.5 Haiku"),
    ],
    "google": [
        ModelOption(id="gemini-2.5-flash", name="Gemini 2.5 Flash"),
        ModelOption(id="gemini-3-flash-preview", name="Gemini 3 Flash Preview"),
        ModelOption(id="gemini-2.5-pro", name="Gemini 2.5 Pro"),
        ModelOption(id="gemini-3-pro-preview", name="Gemini 3 Pro Preview"),
        ModelOption(id="gemini-2.5-flash-lite-preview-09-2025", name="Gemini 2.5 Flash-Lite Preview"),
    ],
    "openai": [
        ModelOption(id="gpt-5.4", name="GPT-5.4"),
        ModelOption(id="gpt-5-mini", name="GPT-5 mini"),
        ModelOption(id="gpt-4.1-mini", name="GPT-4.1 mini"),
        ModelOption(id="gpt-4o", name="GPT-4o"),
    ],
    "ollama": [],
}
_DEFAULT_LLM_MODELS = {
    "claude": "claude-sonnet-4-20250514",
    "google": _BASE_LLM_MODEL,
    "openai": "gpt-5-mini",
    "ollama": "llama3.1",
}


def _build_response(settings: AppSettings, masked_keys: dict[str, str]) -> SettingsResponse:
    return SettingsResponse(
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        anthropic_api_key=masked_keys.get("anthropic_api_key", mask_key(settings.anthropic_api_key) if settings.anthropic_api_key else ""),
        google_api_key=masked_keys.get("google_api_key", mask_key(settings.google_api_key) if settings.google_api_key else ""),
        openai_api_key=masked_keys.get("openai_api_key", mask_key(settings.openai_api_key) if settings.openai_api_key else ""),
        ollama_base_url=settings.ollama_base_url,
        openai_base_url=settings.openai_base_url,
        tidy_level=settings.tidy_level,
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

    # 2. Resolve and validate embedding config before persisting it.
    dim, model = await _resolve_embedding_configuration(
        body.embedding_provider,
        settings,
        openai_api_key=body.openai_api_key,
        google_api_key=body.google_api_key,
        openai_base_url=body.openai_base_url,
    )

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
        await set_setting(
            db,
            "llm_model",
            _resolve_llm_model(body.llm_provider, body.llm_model),
            fernet_key=fernet_key,
            encrypt_value=False,
        )
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
    from hypomnema.db.schema import ensure_vec_tables
    await ensure_vec_tables(db, dim)

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


_LLM_PROVIDER_CATALOG = [
    ProviderInfo(
        id="google",
        name="Google Gemini",
        requires_key=True,
        default_model=_DEFAULT_LLM_MODELS["google"],
        models=_LLM_MODELS["google"],
    ),
    ProviderInfo(
        id="openai",
        name="OpenAI",
        requires_key=True,
        default_model=_DEFAULT_LLM_MODELS["openai"],
        models=_LLM_MODELS["openai"],
    ),
    ProviderInfo(
        id="claude",
        name="Anthropic Claude",
        requires_key=True,
        default_model=_DEFAULT_LLM_MODELS["claude"],
        models=_LLM_MODELS["claude"],
    ),
    ProviderInfo(
        id="ollama",
        name="Ollama (local)",
        requires_key=False,
        default_model=_DEFAULT_LLM_MODELS["ollama"],
        models=[],
    ),
]


def _resolve_llm_model(provider: str, model: str | None) -> str:
    return model or _DEFAULT_LLM_MODELS.get(provider, "")


def _resolve_api_key(provider: str, body: ConnectivityCheck, settings: AppSettings) -> str:
    match provider:
        case "claude":
            return body.anthropic_api_key if body.anthropic_api_key is not None else settings.anthropic_api_key
        case "google":
            return body.google_api_key if body.google_api_key is not None else settings.google_api_key
        case "openai":
            return body.openai_api_key if body.openai_api_key is not None else settings.openai_api_key
        case _:
            return ""


def _resolve_base_url(provider: str, body: ConnectivityCheck, settings: AppSettings) -> str:
    match provider:
        case "ollama":
            return body.ollama_base_url if body.ollama_base_url is not None else settings.ollama_base_url
        case "openai":
            return body.openai_base_url if body.openai_base_url is not None else settings.openai_base_url
        case _:
            return ""


async def _resolve_embedding_configuration(
    provider: str,
    settings: AppSettings,
    *,
    openai_api_key: str | None = None,
    google_api_key: str | None = None,
    openai_base_url: str | None = None,
) -> tuple[int, str]:
    default_dim, default_model = EMBEDDING_DEFAULTS[provider]
    if provider == "local":
        return default_dim, default_model

    result = await _check_embedding_connection(
        ConnectivityCheck(
            kind="embedding",
            provider=provider,
            model=default_model,
            openai_api_key=openai_api_key,
            google_api_key=google_api_key,
            openai_base_url=openai_base_url,
        ),
        settings,
    )
    if result.dimension is None:
        raise HTTPException(status_code=400, detail="Embedding connection check did not return a dimension")
    return result.dimension, result.model


async def _check_llm_connection(
    body: ConnectivityCheck,
    settings: AppSettings,
) -> ConnectivityCheckResponse:
    if body.provider not in _VALID_LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid LLM provider: {body.provider}")

    model = _resolve_llm_model(body.provider, body.model)
    api_key = _resolve_api_key(body.provider, body, settings)
    base_url = _resolve_base_url(body.provider, body, settings)

    if body.provider != "ollama" and not api_key:
        raise HTTPException(status_code=400, detail=f"{body.provider} API key required")

    try:
        llm = build_llm(
            body.provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        await llm.complete(
            "Reply with exactly wired.",
            system="You are a connectivity probe. Reply with exactly wired.",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Connection check failed: {exc}") from exc

    return ConnectivityCheckResponse(
        kind="llm",
        provider=body.provider,
        model=model,
        message=f"{model} is wired and reachable.",
    )


async def _check_embedding_connection(
    body: ConnectivityCheck,
    settings: AppSettings,
) -> ConnectivityCheckResponse:
    provider = body.provider
    model = body.model or EMBEDDING_DEFAULTS.get(provider, (0, ""))[1]
    api_key = _resolve_api_key(provider, body, settings)
    base_url = _resolve_base_url(provider, body, settings)
    try:
        if provider == "local":
            from hypomnema.embeddings.local_gpu import LocalEmbeddingModel

            embeddings = LocalEmbeddingModel(model_name=model)
        elif provider == "openai":
            from hypomnema.embeddings.openai import OpenAIEmbeddingModel

            if not api_key:
                raise HTTPException(status_code=400, detail="OpenAI API key required")
            embeddings = OpenAIEmbeddingModel(api_key=api_key, model=model, base_url=base_url or None)
        elif provider == "google":
            from hypomnema.embeddings.google import GoogleEmbeddingModel

            if not api_key:
                raise HTTPException(status_code=400, detail="Google API key required")
            embeddings = GoogleEmbeddingModel(api_key=api_key, model=model)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid embedding provider: {provider}")

        vectors = await asyncio.to_thread(embeddings.embed, ["wired"])
        dimension = int(vectors.shape[1]) if len(vectors.shape) == 2 else embeddings.dimension
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Connection check failed: {exc}") from exc

    return ConnectivityCheckResponse(
        kind="embedding",
        provider=provider,
        model=model,
        message=f"{model} is wired and reachable.",
        dimension=dimension,
    )


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

    dim, model = await _resolve_embedding_configuration(
        body.embedding_provider,
        settings,
        openai_api_key=body.openai_api_key,
        google_api_key=body.google_api_key,
        openai_base_url=body.openai_base_url,
    )

    # Store new API keys if provided
    if body.openai_api_key:
        await set_setting(db, "openai_api_key", body.openai_api_key, fernet_key=fernet_key, encrypt_value=True)
    if body.google_api_key:
        await set_setting(db, "google_api_key", body.google_api_key, fernet_key=fernet_key, encrypt_value=True)
    if body.openai_base_url is not None:
        await set_setting(db, "openai_base_url", body.openai_base_url, fernet_key=fernet_key, encrypt_value=False)

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

    if total == 0:
        change_status = EmbeddingChangeStatus(status="complete", total=0, processed=0)
        request.app.state.embedding_change_status = change_status
        request.app.state.embedding_change_task = None
        return change_status

    # Set initial status
    change_status = EmbeddingChangeStatus(status="in_progress", total=total, processed=0)
    request.app.state.embedding_change_status = change_status

    # Kick off background reprocessing (store ref to prevent GC)
    request.app.state.embedding_change_task = asyncio.create_task(
        _reprocess_all_documents(request.app, total)
    )

    return change_status


async def _reprocess_all_documents(app: FastAPI, total: int) -> None:
    """Background task: reprocess all documents through the ontology pipeline.

    Uses the app's shared database connection (app.state.db) to avoid
    opening a second connection that would contend for SQLite write locks.
    """
    from hypomnema.ontology.pipeline import (
        link_document,
        process_document,
    )

    try:
        db = app.state.db
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
                await process_document(
                    db,
                    doc_id,
                    llm,
                    embeddings,
                    tidy_level=app.state.settings.tidy_level,
                )
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

        # Auto-compute projections so viz is immediately available
        try:
            from hypomnema.visualization.projection import compute_projections

            await compute_projections(db)
        except Exception:
            logger.exception("Failed to compute projections after reprocessing")

        app.state.embedding_change_status = EmbeddingChangeStatus(
            status="complete", total=total, processed=total,
        )

    except Exception as exc:
        logger.exception("Embedding change reprocessing failed")
        app.state.embedding_change_status = EmbeddingChangeStatus(
            status="failed", total=total, processed=0, error=str(exc),
        )


@router.get("/embedding-status", response_model=EmbeddingChangeStatus)
async def get_embedding_status(request: Request) -> EmbeddingChangeStatus:
    """Return current embedding change status."""
    return request.app.state.embedding_change_status


@router.post("/check-connection", response_model=ConnectivityCheckResponse)
async def check_connection(
    body: ConnectivityCheck,
    settings: AppSettings,
) -> ConnectivityCheckResponse:
    """Validate that a selected LLM or embedding model is reachable."""
    if body.kind == "llm":
        return await _check_llm_connection(body, settings)
    return await _check_embedding_connection(body, settings)


@router.get("/providers", response_model=ProvidersResponse)
async def get_providers() -> ProvidersResponse:
    """Return available provider metadata (excludes mock)."""
    return ProvidersResponse(
        llm=_LLM_PROVIDER_CATALOG,
        embedding=[
            EmbeddingProviderInfo(
                id="local",
                name="Local (sentence-transformers)",
                default_model=EMBEDDING_DEFAULTS["local"][1],
                default_dimension=EMBEDDING_DEFAULTS["local"][0],
                requires_key=False,
            ),
            EmbeddingProviderInfo(
                id="openai",
                name="OpenAI Embeddings",
                default_model=EMBEDDING_DEFAULTS["openai"][1],
                default_dimension=EMBEDDING_DEFAULTS["openai"][0],
                requires_key=True,
            ),
            EmbeddingProviderInfo(
                id="google",
                name="Google Embeddings",
                default_model=EMBEDDING_DEFAULTS["google"][1],
                default_dimension=EMBEDDING_DEFAULTS["google"][0],
                requires_key=True,
            ),
        ],
    )
