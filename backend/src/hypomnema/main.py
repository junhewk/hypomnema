"""FastAPI application factory and lifespan."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hypomnema.config import Settings
from hypomnema.crypto import get_or_create_key
from hypomnema.db.engine import get_connection
from hypomnema.db.schema import create_core_tables, create_vec_tables
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

    # Always create core tables
    await create_core_tables(db)

    # Fernet key
    data_dir = settings.db_path.parent
    data_dir.mkdir(parents=True, exist_ok=True)
    fernet_key = get_or_create_key(data_dir)
    app.state.fernet_key = fernet_key

    # LLM lock for hot-swap
    app.state.llm_lock = asyncio.Lock()

    # Check if setup is complete
    db_settings = await get_all_settings(db, fernet_key=fernet_key)
    setup_complete = db_settings.get("setup_complete")

    if setup_complete:
        # Normal startup: merge DB settings, create vec tables, init everything
        settings = Settings.with_db_overrides(settings, db_settings)
        app.state.settings = settings

        await create_vec_tables(db, settings.embedding_dim)

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
    else:
        # Setup mode: no embeddings, no LLM, no scheduler
        app.state.embeddings = None
        app.state.llm = None
        app.state.scheduler = None

    yield

    if app.state.scheduler:
        app.state.scheduler.shutdown(wait=True)
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
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from hypomnema.api.documents import router as documents_router
    from hypomnema.api.engrams import router as engrams_router
    from hypomnema.api.feeds import router as feeds_router
    from hypomnema.api.search import router as search_router
    from hypomnema.api.settings import router as settings_router
    from hypomnema.api.viz import router as viz_router
    from hypomnema.api.health import router as health_router

    app.include_router(documents_router)
    app.include_router(engrams_router)
    app.include_router(feeds_router)
    app.include_router(search_router)
    app.include_router(settings_router)
    app.include_router(viz_router)
    app.include_router(health_router)

    if settings.static_dir and settings.static_dir.exists():
        from starlette.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")

    return app
