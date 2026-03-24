"""Serial processing queue for the ontology pipeline."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


@dataclass
class PipelineJob:
    document_id: str
    revision: int | None = None


class OntologyQueue:
    """Asyncio-based serial queue for ontology pipeline jobs."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._queue: asyncio.Queue[PipelineJob] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._worker_task = asyncio.create_task(self._worker())

    async def enqueue(self, document_id: str, revision: int | None = None) -> None:
        await self._queue.put(PipelineJob(document_id, revision))

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                from hypomnema.api.documents import _run_ontology_pipeline

                await _run_ontology_pipeline(self._app, job.document_id, job.revision)
            except Exception:
                logger.exception("Queue worker: pipeline failed for %s", job.document_id)
            finally:
                self._queue.task_done()

    async def join(self) -> None:
        """Wait until all pending jobs are processed."""
        await self._queue.join()

    async def shutdown(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
