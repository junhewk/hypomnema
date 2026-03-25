"""Tests for the FeedScheduler cron manager."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite

from hypomnema.ingestion import feeds as feeds_mod
from hypomnema.ingestion.feeds import FetchedItem, create_feed_source
from hypomnema.scheduler.cron import FeedScheduler


class TestFeedScheduler:
    def test_add_job_creates_job(self, db_path: Path) -> None:
        sched = FeedScheduler(db_path)
        sched.add_job("feed1", "0 */6 * * *")
        assert sched._scheduler.get_job("feed_feed1") is not None

    def test_remove_job(self, db_path: Path) -> None:
        sched = FeedScheduler(db_path)
        sched.add_job("feed1", "0 */6 * * *")
        sched.remove_job("feed1")
        assert sched._scheduler.get_job("feed_feed1") is None

    def test_add_job_replaces_existing(self, db_path: Path) -> None:
        sched = FeedScheduler(db_path)
        sched.add_job("feed1", "0 */6 * * *")
        sched.add_job("feed1", "0 */12 * * *")
        # replace_existing works — get_job returns the latest
        assert sched._scheduler.get_job("feed_feed1") is not None

    @pytest.mark.asyncio
    async def test_start_and_shutdown(self, db_path: Path) -> None:
        import asyncio

        sched = FeedScheduler(db_path)
        sched.start()
        assert sched.running is True
        sched.shutdown()
        # AsyncIOScheduler defers state transition to the event loop
        await asyncio.sleep(0)
        assert sched.running is False

    @pytest.mark.asyncio
    async def test_load_jobs_registers_active(self, tmp_db: aiosqlite.Connection, db_path: Path) -> None:
        await create_feed_source(tmp_db, "Active1", "rss", "https://example.com/1")
        await create_feed_source(tmp_db, "Active2", "rss", "https://example.com/2")
        fs3 = await create_feed_source(tmp_db, "Inactive", "rss", "https://example.com/3")
        await tmp_db.execute("UPDATE feed_sources SET active = 0 WHERE id = ?", (fs3.id,))
        await tmp_db.commit()

        sched = FeedScheduler(db_path)
        count = await sched.load_jobs()
        assert count == 2


class TestRunFeedJob:
    @pytest.mark.asyncio
    async def test_polls_and_creates_docs(
        self, tmp_db: aiosqlite.Connection, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fs = await create_feed_source(tmp_db, "Test", "rss", "https://example.com/feed")
        monkeypatch.setitem(
            feeds_mod._FETCHERS,
            "rss",
            lambda url, timeout: [FetchedItem(title="T", text="Content", source_uri="https://example.com/item1")],
        )

        sched = FeedScheduler(db_path)
        await sched._run_feed_job(fs.id)

        cursor = await tmp_db.execute("SELECT * FROM documents WHERE source_type = 'feed'")
        rows = list(await cursor.fetchall())
        await cursor.close()
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_inactive_feed_skipped(self, tmp_db: aiosqlite.Connection, db_path: Path) -> None:
        fs = await create_feed_source(tmp_db, "Test", "rss", "https://example.com/feed")
        await tmp_db.execute("UPDATE feed_sources SET active = 0 WHERE id = ?", (fs.id,))
        await tmp_db.commit()

        sched = FeedScheduler(db_path)
        # Should return without error (skips inactive)
        await sched._run_feed_job(fs.id)

        cursor = await tmp_db.execute("SELECT COUNT(*) AS cnt FROM documents")
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        assert row["cnt"] == 0

    @pytest.mark.asyncio
    async def test_updates_last_fetched(
        self, tmp_db: aiosqlite.Connection, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fs = await create_feed_source(tmp_db, "Test", "rss", "https://example.com/feed")
        monkeypatch.setitem(feeds_mod._FETCHERS, "rss", lambda url, timeout: [])

        sched = FeedScheduler(db_path)
        await sched._run_feed_job(fs.id)

        cursor = await tmp_db.execute("SELECT last_fetched FROM feed_sources WHERE id = ?", (fs.id,))
        row = await cursor.fetchone()
        await cursor.close()
        assert row is not None
        assert row["last_fetched"] is not None

    @pytest.mark.asyncio
    async def test_fetch_error_logged(
        self, tmp_db: aiosqlite.Connection, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fs = await create_feed_source(tmp_db, "Test", "rss", "https://example.com/feed")

        def fail(url: str, timeout: float) -> None:
            raise RuntimeError("network error")

        monkeypatch.setitem(feeds_mod._FETCHERS, "rss", fail)

        sched = FeedScheduler(db_path)
        # Should not raise — error is caught and logged
        await sched._run_feed_job(fs.id)

    @pytest.mark.asyncio
    async def test_triggers_triage(
        self,
        tmp_db: aiosqlite.Connection,
        db_path: Path,
        mock_embeddings: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fs = await create_feed_source(tmp_db, "Test", "rss", "https://example.com/feed")
        monkeypatch.setitem(
            feeds_mod._FETCHERS,
            "rss",
            lambda url, timeout: [FetchedItem(title="T", text="Content", source_uri="https://example.com/item1")],
        )

        triage_mock = AsyncMock()
        monkeypatch.setattr("hypomnema.scheduler.cron.triage_pending_documents", triage_mock)

        sched = FeedScheduler(db_path, embeddings=mock_embeddings)
        await sched._run_feed_job(fs.id)

        triage_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_triage_without_embeddings(
        self, tmp_db: aiosqlite.Connection, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fs = await create_feed_source(tmp_db, "Test", "rss", "https://example.com/feed")
        monkeypatch.setitem(
            feeds_mod._FETCHERS,
            "rss",
            lambda url, timeout: [FetchedItem(title="T", text="Content", source_uri="https://example.com/item1")],
        )

        triage_mock = AsyncMock()
        monkeypatch.setattr("hypomnema.scheduler.cron.triage_pending_documents", triage_mock)

        sched = FeedScheduler(db_path, embeddings=None)
        await sched._run_feed_job(fs.id)

        triage_mock.assert_not_called()
