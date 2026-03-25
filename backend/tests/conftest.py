"""Shared test fixtures."""

import hashlib
from pathlib import Path

import aiosqlite
import numpy as np
import pytest
import pytest_asyncio

from hypomnema.db.engine import get_connection
from hypomnema.db.schema import create_tables
from hypomnema.embeddings.mock import MockEmbeddingModel
from hypomnema.llm.mock import MockLLMClient
from hypomnema.ontology.engram import embedding_to_bytes


@pytest_asyncio.fixture
async def tmp_db(tmp_path: Path) -> aiosqlite.Connection:
    """Fresh SQLite database with full schema, per test.

    Uses tmp_path (not :memory:) because:
    - WAL mode is a no-op on :memory: databases
    - sqlite-vec extension loading may differ on :memory:
    - tmp_path is auto-cleaned by pytest
    """
    db_path = tmp_path / "test.db"
    db = await get_connection(db_path)
    await create_tables(db)
    yield db
    await db.close()


@pytest.fixture
def mock_llm() -> MockLLMClient:
    return MockLLMClient()


@pytest.fixture
def mock_embeddings() -> MockEmbeddingModel:
    return MockEmbeddingModel(dimension=384)


def make_embedding(seed: int, dim: int = 384) -> np.ndarray[object, np.dtype[np.float32]]:
    """Generate a deterministic unit-normalized embedding for testing."""
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(dim).astype(np.float32)
    return vec / np.linalg.norm(vec)


async def insert_engram_with_embedding(
    db: aiosqlite.Connection, name: str, embedding: np.ndarray[object, np.dtype[np.float32]]
) -> str:
    """Insert an engram with its embedding and return the engram ID."""
    concept_hash = hashlib.sha256(name.encode()).hexdigest()[:16]
    cursor = await db.execute(
        "INSERT INTO engrams (canonical_name, concept_hash, description) VALUES (?, ?, ?) RETURNING id",
        (name, concept_hash, f"Description of {name}"),
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    engram_id: str = row[0]

    emb_bytes = embedding_to_bytes(np.asarray(embedding, dtype=np.float32))
    await db.execute(
        "INSERT INTO engram_embeddings (engram_id, embedding) VALUES (?, ?)",
        (engram_id, emb_bytes),
    )
    await db.commit()
    return engram_id
