"""FastAPI application factory — retained for test compatibility.

The primary application entry point is now hypomnema.ui.app.configure(),
which sets up NiceGUI with the same API routers. This module preserves
create_app() so that tests (which need a bare FastAPI app without NiceGUI)
continue to work.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hypomnema.config import Settings
from hypomnema.crypto import get_or_create_key
from hypomnema.db.engine import ConnectionPool, get_connection
from hypomnema.db.schema import ensure_vec_tables, run_migrations
from hypomnema.db.settings_store import get_all_settings
from hypomnema.embeddings.factory import build_embeddings
from hypomnema.llm.factory import api_key_for_provider, base_url_for_provider, build_llm

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings: Settings = app.state.settings

    # Database
    db = await get_connection(settings.db_path, settings.sqlite_vec_path)
    app.state.db = db

    # Run schema migrations
    await run_migrations(db)

    # Connection pool for request handling
    pool = ConnectionPool(size=3)
    await pool.open(settings.db_path, settings.sqlite_vec_path)
    app.state.pool = pool

    # Fernet key
    data_dir = settings.db_path.parent
    data_dir.mkdir(parents=True, exist_ok=True)
    fernet_key = get_or_create_key(data_dir)
    app.state.fernet_key = fernet_key

    # Pre-hash passphrase from env var (server/Docker mode)
    if settings.mode == "server" and settings.passphrase:
        from hypomnema.crypto import hash_passphrase
        from hypomnema.db.settings_store import get_setting, set_setting

        existing = await get_setting(db, "auth_passphrase_hash", fernet_key=fernet_key)
        if not existing:
            hashed = hash_passphrase(settings.passphrase)
            await set_setting(
                db,
                "auth_passphrase_hash",
                hashed,
                fernet_key=fernet_key,
                encrypt_value=True,
            )
            logger.info("Pre-set passphrase from HYPOMNEMA_PASSPHRASE env var")

    # LLM lock for hot-swap
    app.state.llm_lock = asyncio.Lock()

    # Embedding change status
    from hypomnema.api.schemas import EmbeddingChangeStatus

    app.state.embedding_change_status = EmbeddingChangeStatus()
    app.state.embedding_change_task = None

    # Check if setup is complete
    db_settings = await get_all_settings(db, fernet_key=fernet_key)
    setup_complete = db_settings.get("setup_complete")

    if setup_complete:
        # Normal startup: merge DB settings, create vec tables, init everything
        settings = Settings.with_db_overrides(settings, db_settings)
        app.state.settings = settings

        vec_schema_rebuilt = await ensure_vec_tables(db, settings.embedding_dim)

        # Embeddings
        if settings.llm_provider == "mock":
            from hypomnema.embeddings.mock import MockEmbeddingModel

            app.state.embeddings = MockEmbeddingModel(dimension=settings.embedding_dim)
        else:
            app.state.embeddings = build_embeddings(settings)

        # LLM
        if settings.llm_provider == "mock":
            from hypomnema.llm.mock import MockLLMClient

            app.state.llm = MockLLMClient()
        else:
            app.state.llm = build_llm(
                settings.llm_provider,
                api_key=api_key_for_provider(settings.llm_provider, settings),
                model=settings.llm_model,
                base_url=base_url_for_provider(settings.llm_provider, settings),
            )

        # Feed scheduler
        from hypomnema.scheduler.cron import FeedScheduler

        scheduler = FeedScheduler(
            settings.db_path,
            sqlite_vec_path=settings.sqlite_vec_path,
            triage_threshold=settings.triage_threshold,
            feed_timeout=settings.feed_fetch_timeout,
            embeddings=app.state.embeddings,
        )
        await scheduler.load_jobs()
        scheduler.start()
        app.state.scheduler = scheduler

        # Ontology processing queue (serial)
        from hypomnema.ontology.queue import OntologyQueue

        ontology_queue = OntologyQueue(app)
        ontology_queue.start()
        app.state.ontology_queue = ontology_queue

        if vec_schema_rebuilt:
            logger.warning(
                "Embedding dimension mismatch detected; rebuilt vec tables"
                " for %s dimensions and queued full reprocessing",
                settings.embedding_dim,
            )
            cursor = await db.execute("SELECT count(*) FROM documents")
            row = await cursor.fetchone()
            await cursor.close()
            total = row[0] if row else 0
            if total == 0:
                app.state.embedding_change_status = EmbeddingChangeStatus(
                    status="complete",
                    total=0,
                    processed=0,
                )
            else:
                from hypomnema.api.settings import _reprocess_all_documents

                app.state.embedding_change_status = EmbeddingChangeStatus(
                    status="in_progress",
                    total=total,
                    processed=0,
                )
                app.state.embedding_change_task = asyncio.create_task(_reprocess_all_documents(app, total))
    else:
        # Setup mode: no embeddings, no LLM, no scheduler
        app.state.embeddings = None
        app.state.llm = None
        app.state.scheduler = None
        app.state.ontology_queue = None

    yield

    if app.state.ontology_queue:
        await app.state.ontology_queue.shutdown()
    if app.state.scheduler:
        app.state.scheduler.shutdown(wait=True)
    if app.state.embedding_change_task:
        app.state.embedding_change_task.cancel()
    await pool.close()
    await db.close()


def create_app(settings: Settings | None = None, *, use_lifespan: bool = True) -> FastAPI:
    """Create the FastAPI application.

    Args:
        settings: Configuration. Defaults to loading from environment.
        use_lifespan: If False, skip lifespan (for tests that inject state manually).
    """
    if settings is None:
        settings = Settings()

    app = FastAPI(title="Hypomnema", lifespan=lifespan if use_lifespan else None)
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from hypomnema.api.auth import auth_router
    from hypomnema.api.backup import router as backup_router
    from hypomnema.api.documents import router as documents_router
    from hypomnema.api.engrams import router as engrams_router
    from hypomnema.api.feeds import router as feeds_router
    from hypomnema.api.health import router as health_router
    from hypomnema.api.search import router as search_router
    from hypomnema.api.settings import router as settings_router
    from hypomnema.api.viz import router as viz_router

    app.include_router(auth_router)
    app.include_router(backup_router)
    app.include_router(documents_router)
    app.include_router(engrams_router)
    app.include_router(feeds_router)
    app.include_router(search_router)
    app.include_router(settings_router)
    app.include_router(viz_router)
    app.include_router(health_router)

    # Auth middleware for server mode (must be added after CORS middleware)
    if settings.mode == "server":
        from hypomnema.api.auth import PassphraseAuthMiddleware

        app.add_middleware(PassphraseAuthMiddleware)  # type: ignore[arg-type]

    return app
