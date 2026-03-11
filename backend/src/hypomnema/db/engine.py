"""SQLite engine: connection factory, PRAGMAs, sqlite-vec extension."""

import sqlite3
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
import sqlite_vec


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
