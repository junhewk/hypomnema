"""Tests for serialized SQLite write transactions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from hypomnema.db.engine import get_connection
from hypomnema.db.transactions import immediate_transaction


class TestImmediateTransaction:
    async def test_serializes_writes_across_connections(self, tmp_path: Path) -> None:
        db_path = tmp_path / "serialized.db"
        db1 = await get_connection(db_path)
        db2 = await get_connection(db_path)
        release_first = asyncio.Event()
        first_started = asyncio.Event()
        events: list[str] = []

        try:
            await db1.execute("CREATE TABLE writes (value TEXT NOT NULL)")
            await db1.commit()

            async def writer_one() -> None:
                async with immediate_transaction(db1):
                    await db1.execute("INSERT INTO writes (value) VALUES ('first')")
                    first_started.set()
                    events.append("first-active")
                    await release_first.wait()
                events.append("first-committed")

            async def writer_two() -> None:
                await first_started.wait()
                async with immediate_transaction(db2):
                    events.append("second-active")
                    await db2.execute("INSERT INTO writes (value) VALUES ('second')")
                events.append("second-committed")

            task_one = asyncio.create_task(writer_one())
            task_two = asyncio.create_task(writer_two())

            await first_started.wait()
            await asyncio.sleep(0.05)
            assert "second-active" not in events

            release_first.set()
            await asyncio.gather(task_one, task_two)

            assert events == [
                "first-active",
                "first-committed",
                "second-active",
                "second-committed",
            ]

            cursor = await db1.execute("SELECT value FROM writes ORDER BY rowid")
            rows = await cursor.fetchall()
            await cursor.close()
            assert [row[0] for row in rows] == ["first", "second"]
        finally:
            await db1.close()
            await db2.close()

    async def test_allows_nested_transactions_on_same_connection(self, tmp_path: Path) -> None:
        db = await get_connection(tmp_path / "nested.db")
        try:
            await db.execute("CREATE TABLE writes (value TEXT NOT NULL)")
            await db.commit()

            async with immediate_transaction(db):
                await db.execute("INSERT INTO writes (value) VALUES ('outer')")
                async with immediate_transaction(db):
                    await db.execute("INSERT INTO writes (value) VALUES ('inner')")

            cursor = await db.execute("SELECT value FROM writes ORDER BY rowid")
            rows = await cursor.fetchall()
            await cursor.close()
            assert [row[0] for row in rows] == ["outer", "inner"]
        finally:
            await db.close()

    async def test_rejects_nested_writes_on_different_connections(self, tmp_path: Path) -> None:
        db_path = tmp_path / "different-connection.db"
        db1 = await get_connection(db_path)
        db2 = await get_connection(db_path)
        try:
            async with immediate_transaction(db1):
                with pytest.raises(RuntimeError, match="different connections"):
                    async with immediate_transaction(db2):
                        pass
        finally:
            await db1.close()
            await db2.close()
