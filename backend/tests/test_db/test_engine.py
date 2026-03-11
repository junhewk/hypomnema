"""Tests for db/engine.py — connection factory, PRAGMAs, extension loading."""

from pathlib import Path

import aiosqlite
import pytest

from hypomnema.db.engine import connect, get_connection


class TestGetConnection:
    async def test_creates_db_file(self, tmp_path: Path):
        db_path = tmp_path / "new.db"
        assert not db_path.exists()
        db = await get_connection(db_path)
        try:
            assert db_path.exists()
        finally:
            await db.close()

    async def test_creates_parent_directories(self, tmp_path: Path):
        db_path = tmp_path / "nested" / "dirs" / "test.db"
        db = await get_connection(db_path)
        try:
            assert db_path.exists()
        finally:
            await db.close()

    async def test_wal_mode_enabled(self, tmp_path: Path):
        db = await get_connection(tmp_path / "wal.db")
        try:
            cursor = await db.execute("PRAGMA journal_mode")
            row = await cursor.fetchone()
            assert row[0] == "wal"
        finally:
            await db.close()

    async def test_foreign_keys_enabled(self, tmp_path: Path):
        db = await get_connection(tmp_path / "fk.db")
        try:
            cursor = await db.execute("PRAGMA foreign_keys")
            assert (await cursor.fetchone())[0] == 1
        finally:
            await db.close()

    async def test_busy_timeout_set(self, tmp_path: Path):
        db = await get_connection(tmp_path / "busy.db")
        try:
            cursor = await db.execute("PRAGMA busy_timeout")
            assert (await cursor.fetchone())[0] == 5000
        finally:
            await db.close()

    async def test_cache_size_set(self, tmp_path: Path):
        db = await get_connection(tmp_path / "cache.db")
        try:
            cursor = await db.execute("PRAGMA cache_size")
            assert (await cursor.fetchone())[0] == -64000
        finally:
            await db.close()

    async def test_sqlite_vec_loaded(self, tmp_path: Path):
        db = await get_connection(tmp_path / "vec.db")
        try:
            cursor = await db.execute("SELECT vec_version()")
            row = await cursor.fetchone()
            assert row[0]
            assert isinstance(row[0], str)
        finally:
            await db.close()

    async def test_row_factory_allows_dict_access(self, tmp_path: Path):
        db = await get_connection(tmp_path / "row.db")
        try:
            await db.execute("CREATE TABLE t (a TEXT, b INTEGER)")
            await db.execute("INSERT INTO t VALUES ('hello', 42)")
            cursor = await db.execute("SELECT a, b FROM t")
            row = await cursor.fetchone()
            assert row["a"] == "hello"
            assert row["b"] == 42
        finally:
            await db.close()


class TestConnectContextManager:
    async def test_yields_connection(self, tmp_path: Path):
        async with connect(tmp_path / "ctx.db") as db:
            assert isinstance(db, aiosqlite.Connection)

    async def test_connection_usable(self, tmp_path: Path):
        async with connect(tmp_path / "ctx2.db") as db:
            cursor = await db.execute("SELECT 1")
            assert (await cursor.fetchone())[0] == 1

    async def test_connection_closed_after_exit(self, tmp_path: Path):
        async with connect(tmp_path / "ctx3.db") as db:
            pass
        with pytest.raises(Exception):
            await db.execute("SELECT 1")

    async def test_sqlite_vec_available(self, tmp_path: Path):
        async with connect(tmp_path / "ctx4.db") as db:
            cursor = await db.execute("SELECT vec_version()")
            assert (await cursor.fetchone())[0]
