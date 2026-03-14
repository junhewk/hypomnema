"""Synchronous sqlite3 wrapper with an async-compatible interface.

Used by eval harnesses and tests that need to call async ontology functions
(which expect aiosqlite-style ``await db.execute(...)``) against a plain
synchronous sqlite3 connection.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import sqlite_vec

if TYPE_CHECKING:
    from pathlib import Path


class SyncCursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    async def fetchone(self) -> sqlite3.Row | None:
        return self._cursor.fetchone()

    async def fetchall(self) -> list[sqlite3.Row]:
        return self._cursor.fetchall()

    async def close(self) -> None:
        self._cursor.close()


class SyncConnection:
    """Wraps ``sqlite3.Connection`` so callers can ``await`` its methods."""

    def __init__(self, db_path: Path) -> None:
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.enable_load_extension(True)
        self._connection.load_extension(sqlite_vec.loadable_path())
        self._connection.enable_load_extension(False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute("PRAGMA cache_size=-64000")

    async def execute(
        self,
        sql: str,
        parameters: tuple[object, ...] | list[object] | None = None,
    ) -> SyncCursor:
        cursor = self._connection.execute(sql, parameters or ())
        return SyncCursor(cursor)

    async def commit(self) -> None:
        self._connection.commit()

    async def rollback(self) -> None:
        self._connection.rollback()

    async def close(self) -> None:
        self._connection.close()
