"""API test fixtures: app, client, dependency injection."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest_asyncio

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite

from httpx import ASGITransport, AsyncClient

from hypomnema.config import Settings
from hypomnema.db.engine import get_connection
from hypomnema.db.schema import create_tables
from hypomnema.embeddings.mock import MockEmbeddingModel
from hypomnema.llm.mock import MockLLMClient
from hypomnema.main import create_app
from hypomnema.ontology.queue import OntologyQueue
from hypomnema.scheduler.cron import FeedScheduler


@pytest_asyncio.fixture
async def app(tmp_path: Path):
    """Test app with real DB, mock LLM/embeddings, no scheduler running."""
    db_path = tmp_path / "test.db"
    settings = Settings(db_path=db_path, llm_provider="mock")

    test_app = create_app(settings, use_lifespan=False)

    db = await get_connection(db_path)
    await create_tables(db)
    test_app.state.db = db
    test_app.state.llm = MockLLMClient()
    test_app.state.embeddings = MockEmbeddingModel(dimension=384)
    test_app.state.settings = settings
    test_app.state.scheduler = FeedScheduler(db_path, embeddings=test_app.state.embeddings)
    ontology_queue = OntologyQueue(test_app)
    ontology_queue.start()
    test_app.state.ontology_queue = ontology_queue

    yield test_app

    await test_app.state.ontology_queue.shutdown()
    await db.close()


@pytest_asyncio.fixture
async def client(app):
    """httpx AsyncClient wired to test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def insert_engram(db: aiosqlite.Connection, name: str, *, description: str | None = None) -> str:
    """Insert a test engram and return its id."""
    concept_hash = hashlib.sha256(name.encode()).hexdigest()[:16]
    cursor = await db.execute(
        "INSERT INTO engrams (canonical_name, concept_hash, description) VALUES (?, ?, ?) RETURNING id",
        (name, concept_hash, description or f"Description of {name}"),
    )
    row = await cursor.fetchone()
    await db.commit()
    assert row is not None
    return str(row[0])


async def insert_edge(db: aiosqlite.Connection, source_id: str, target_id: str, predicate: str = "relates_to") -> str:
    """Insert a test edge and return its id."""
    cursor = await db.execute(
        "INSERT INTO edges (source_engram_id, target_engram_id, predicate) VALUES (?, ?, ?) RETURNING id",
        (source_id, target_id, predicate),
    )
    row = await cursor.fetchone()
    await db.commit()
    assert row is not None
    return str(row[0])
