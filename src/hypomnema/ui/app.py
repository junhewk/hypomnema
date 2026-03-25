"""NiceGUI application setup — theme, routes, and startup/shutdown hooks."""

from __future__ import annotations

import asyncio
import logging

from nicegui import app

from hypomnema.config import Settings
from hypomnema.crypto import get_or_create_key
from hypomnema.db.engine import ConnectionPool, get_connection
from hypomnema.db.schema import ensure_vec_tables, run_migrations
from hypomnema.db.settings_store import get_all_settings
from hypomnema.embeddings.factory import build_embeddings
from hypomnema.llm.factory import api_key_for_provider, base_url_for_provider, build_llm

logger = logging.getLogger(__name__)


def configure(settings: Settings | None = None) -> None:
    """Configure the NiceGUI app: mount API routers, register startup/shutdown, import pages."""
    if settings is None:
        settings = Settings()

    app.state.settings = settings

    # Mount existing API routers on /api prefix
    from hypomnema.api.auth import auth_router
    from hypomnema.api.backup import router as backup_router
    from hypomnema.api.documents import router as documents_router
    from hypomnema.api.engrams import router as engrams_router
    from hypomnema.api.feeds import router as feeds_router
    from hypomnema.api.health import router as health_router
    from hypomnema.api.search import router as search_router
    from hypomnema.api.settings import router as settings_router
    from hypomnema.api.viz import router as viz_router

    # Routers already define their own /api/... prefixes
    app.include_router(auth_router)
    app.include_router(backup_router)
    app.include_router(documents_router)
    app.include_router(engrams_router)
    app.include_router(feeds_router)
    app.include_router(search_router)
    app.include_router(settings_router)
    app.include_router(viz_router)
    app.include_router(health_router)

    # Auth middleware for server mode
    if settings.mode == "server":
        from hypomnema.api.auth import PassphraseAuthMiddleware

        # NiceGUI's app is a Starlette app, middleware works the same way
        app.add_middleware(PassphraseAuthMiddleware)  # type: ignore[arg-type]

    # Register lifecycle hooks
    app.on_startup(_startup)
    app.on_shutdown(_shutdown)

    # Import UI pages (registers @ui.page routes)
    import hypomnema.ui.pages.document  # noqa: F401
    import hypomnema.ui.pages.engram  # noqa: F401
    import hypomnema.ui.pages.search  # noqa: F401
    import hypomnema.ui.pages.settings  # noqa: F401
    import hypomnema.ui.pages.setup  # noqa: F401
    import hypomnema.ui.pages.stream  # noqa: F401
    import hypomnema.ui.pages.viz  # noqa: F401


async def _startup() -> None:
    """Initialize database, embeddings, LLM, scheduler, and queue on app startup."""
    settings: Settings = app.state.settings

    # Database
    db = await get_connection(settings.db_path, settings.sqlite_vec_path)
    app.state.db = db

    await run_migrations(db)

    pool = ConnectionPool(size=3)
    await pool.open(settings.db_path, settings.sqlite_vec_path)
    app.state.pool = pool

    # Fernet key
    data_dir = settings.db_path.parent
    data_dir.mkdir(parents=True, exist_ok=True)
    fernet_key = get_or_create_key(data_dir)
    app.state.fernet_key = fernet_key

    # Pre-hash passphrase from env var
    if settings.mode == "server" and settings.passphrase:
        from hypomnema.crypto import hash_passphrase
        from hypomnema.db.settings_store import get_setting, set_setting

        existing = await get_setting(db, "auth_passphrase_hash", fernet_key=fernet_key)
        if not existing:
            hashed = hash_passphrase(settings.passphrase)
            await set_setting(db, "auth_passphrase_hash", hashed, fernet_key=fernet_key, encrypt_value=True)
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

        # Ontology processing queue
        from hypomnema.ontology.queue import OntologyQueue

        ontology_queue = OntologyQueue(app)
        ontology_queue.start()
        app.state.ontology_queue = ontology_queue

        if vec_schema_rebuilt:
            logger.warning("Embedding dimension mismatch; rebuilt vec tables and queued reprocessing")
            cursor = await db.execute("SELECT count(*) FROM documents")
            row = await cursor.fetchone()
            await cursor.close()
            total = row[0] if row else 0
            if total == 0:
                app.state.embedding_change_status = EmbeddingChangeStatus(status="complete", total=0, processed=0)
            else:
                from hypomnema.api.settings import _reprocess_all_documents

                app.state.embedding_change_status = EmbeddingChangeStatus(
                    status="in_progress", total=total, processed=0
                )
                app.state.embedding_change_task = asyncio.create_task(_reprocess_all_documents(app, total))
    else:
        # Setup mode
        app.state.embeddings = None
        app.state.llm = None
        app.state.scheduler = None
        app.state.ontology_queue = None


async def _shutdown() -> None:
    """Clean up resources on app shutdown."""
    if getattr(app.state, "ontology_queue", None):
        await app.state.ontology_queue.shutdown()
    if getattr(app.state, "scheduler", None):
        app.state.scheduler.shutdown(wait=True)
    if getattr(app.state, "embedding_change_task", None):
        app.state.embedding_change_task.cancel()
    if getattr(app.state, "pool", None):
        await app.state.pool.close()
    if getattr(app.state, "db", None):
        await app.state.db.close()
