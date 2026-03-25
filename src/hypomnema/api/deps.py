"""FastAPI dependency injection — pull resources from app.state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request

if TYPE_CHECKING:
    import asyncio
    from collections.abc import AsyncGenerator

    import aiosqlite

    from hypomnema.config import Settings
    from hypomnema.db.engine import ConnectionPool
    from hypomnema.embeddings.base import EmbeddingModel
    from hypomnema.llm.base import LLMClient
    from hypomnema.scheduler.cron import FeedScheduler


async def get_db(request: Request) -> AsyncGenerator[aiosqlite.Connection, None]:
    pool: ConnectionPool | None = getattr(request.app.state, "pool", None)
    if pool is not None:
        async with pool.acquire() as conn:
            yield conn
    else:
        # Fallback for tests or pre-pool setups
        yield getattr(request.app.state, "db", None)  # type: ignore[misc]


def get_llm(request: Request) -> LLMClient:
    llm = getattr(request.app.state, "llm", None)
    if llm is None:
        raise HTTPException(status_code=503, detail="Setup not complete")
    return llm  # type: ignore[no-any-return]


def get_embeddings(request: Request) -> EmbeddingModel:
    emb = getattr(request.app.state, "embeddings", None)
    if emb is None:
        raise HTTPException(status_code=503, detail="Setup not complete")
    return emb  # type: ignore[no-any-return]


def get_scheduler(request: Request) -> FeedScheduler:
    return getattr(request.app.state, "scheduler", None)  # type: ignore[return-value]


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=503, detail="Setup not complete")
    return settings  # type: ignore[no-any-return]


def get_fernet_key(request: Request) -> bytes:
    return getattr(request.app.state, "fernet_key", None)  # type: ignore[return-value]


def get_llm_lock(request: Request) -> asyncio.Lock:
    lock = getattr(request.app.state, "llm_lock", None)
    if lock is None:
        raise HTTPException(status_code=503, detail="Setup not complete")
    return lock  # type: ignore[no-any-return]


DB = Annotated["aiosqlite.Connection", Depends(get_db)]
LLM = Annotated["LLMClient", Depends(get_llm)]
Embeddings = Annotated["EmbeddingModel", Depends(get_embeddings)]
Scheduler = Annotated["FeedScheduler", Depends(get_scheduler)]
AppSettings = Annotated["Settings", Depends(get_settings)]
FernetKey = Annotated[bytes, Depends(get_fernet_key)]
LLMLock = Annotated["asyncio.Lock", Depends(get_llm_lock)]
