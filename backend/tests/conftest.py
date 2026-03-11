"""Shared test fixtures."""

from pathlib import Path

import aiosqlite
import pytest_asyncio

from hypomnema.db.engine import get_connection
from hypomnema.db.schema import create_tables


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
