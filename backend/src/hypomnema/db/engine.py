"""SQLite engine: connection factory, pool, PRAGMAs, sqlite-vec extension."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
import sqlite_vec

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


async def get_connection(db_path: Path | str, sqlite_vec_ext_path: str = "") -> aiosqlite.Connection:
    """Create and configure a new aiosqlite connection.

    Caller is responsible for closing. For context-manager usage see connect().
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(str(path))
    db.row_factory = sqlite3.Row

    # Load sqlite-vec
    ext_path: str = sqlite_vec_ext_path or sqlite_vec.loadable_path()
    await db.enable_load_extension(True)
    await db.load_extension(ext_path)
    await db.enable_load_extension(False)

    # PRAGMAs (per-connection)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA cache_size=-64000")

    return db


@asynccontextmanager
async def connect(db_path: Path | str, sqlite_vec_ext_path: str = "") -> AsyncGenerator[aiosqlite.Connection, None]:
    """Async context manager yielding a configured connection."""
    db = await get_connection(db_path, sqlite_vec_ext_path)
    try:
        yield db
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------


class ConnectionPool:
    """Small async connection pool for SQLite.

    Wraps an ``asyncio.Queue`` of pre-configured ``aiosqlite.Connection``
    objects. Each request borrows a connection and returns it after use.
    """

    def __init__(self, size: int = 3) -> None:
        self._size = size
        self._queue: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue(maxsize=size)
        self._all: list[aiosqlite.Connection] = []

    async def open(self, db_path: Path | str, sqlite_vec_ext_path: str = "") -> None:
        """Create *size* connections and add them to the pool."""
        for _ in range(self._size):
            conn = await get_connection(db_path, sqlite_vec_ext_path)
            self._all.append(conn)
            await self._queue.put(conn)
        logger.info("Connection pool opened with %d connections", self._size)

    async def close(self) -> None:
        """Close every connection in the pool."""
        for conn in self._all:
            await conn.close()
        self._all.clear()

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Borrow a connection from the pool; return it when done."""
        conn = await self._queue.get()
        try:
            yield conn
        finally:
            await self._queue.put(conn)
