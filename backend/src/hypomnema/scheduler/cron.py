"""APScheduler cron: feed polling jobs registered from feed_sources table."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from hypomnema.embeddings.base import EmbeddingModel

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from hypomnema.db.engine import connect
from hypomnema.db.models import FeedSource
from hypomnema.ingestion.feeds import list_feed_sources, poll_feed
from hypomnema.triage.bouncer import triage_pending_documents

logger = logging.getLogger(__name__)


class FeedScheduler:
    """Manages APScheduler cron jobs for periodic feed polling.

    Each job opens its own DB connection to avoid sharing aiosqlite
    connections across concurrent jobs.

    Designed to be instantiated in FastAPI lifespan (Phase 9):
        scheduler = FeedScheduler(db_path, embeddings=emb)
        await scheduler.load_jobs()
        scheduler.start()
        ...
        scheduler.shutdown()
    """

    def __init__(
        self,
        db_path: Path,
        *,
        sqlite_vec_path: str = "",
        triage_threshold: float = 0.3,
        feed_timeout: float = 30.0,
        embeddings: EmbeddingModel | None = None,
    ) -> None:
        self._db_path = db_path
        self._sqlite_vec_path = sqlite_vec_path
        self._triage_threshold = triage_threshold
        self._feed_timeout = feed_timeout
        self._embeddings = embeddings
        self._scheduler = AsyncIOScheduler()

    async def _run_feed_job(self, feed_source_id: str) -> None:
        """Job callback: poll one feed source, then triage new docs."""
        async with connect(self._db_path, self._sqlite_vec_path) as db:
            # Re-fetch source (may have been deactivated since scheduled)
            cursor = await db.execute(
                "SELECT * FROM feed_sources WHERE id = ? AND active = 1",
                (feed_source_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                logger.info("Feed %s inactive/deleted, skipping", feed_source_id)
                return

            feed_source = FeedSource.from_row(row)

            try:
                docs = await poll_feed(
                    db, feed_source, timeout=self._feed_timeout
                )
                logger.info(
                    "Feed '%s': %d new documents",
                    feed_source.name, len(docs),
                )
            except Exception:
                logger.exception("Error polling feed '%s'", feed_source.name)
                return

            if docs and self._embeddings is not None:
                try:
                    await triage_pending_documents(
                        db,
                        self._embeddings,
                        threshold=self._triage_threshold,
                    )
                except Exception:
                    logger.exception(
                        "Error triaging docs for feed '%s'", feed_source.name
                    )

    def _job_id(self, feed_source_id: str) -> str:
        return f"feed_{feed_source_id}"

    async def load_jobs(self) -> int:
        """Load all active feed sources from DB and register cron jobs.

        Returns the number of jobs registered.
        """
        async with connect(self._db_path, self._sqlite_vec_path) as db:
            sources = await list_feed_sources(db, active_only=True)

        for source in sources:
            self.add_job(source.id, source.schedule)

        return len(sources)

    def add_job(self, feed_source_id: str, schedule: str) -> None:
        """Register or replace a cron job for a feed source."""
        job_id = self._job_id(feed_source_id)
        trigger = CronTrigger.from_crontab(schedule)
        self._scheduler.add_job(
            self._run_feed_job,
            trigger=trigger,
            args=[feed_source_id],
            id=job_id,
            replace_existing=True,
        )

    def remove_job(self, feed_source_id: str) -> None:
        """Remove a scheduled job if it exists."""
        job_id = self._job_id(feed_source_id)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

    def start(self) -> None:
        """Start the scheduler."""
        self._scheduler.start()

    def shutdown(self, wait: bool = True) -> None:
        """Stop the scheduler."""
        self._scheduler.shutdown(wait=wait)

    @property
    def running(self) -> bool:
        return bool(self._scheduler.running)
