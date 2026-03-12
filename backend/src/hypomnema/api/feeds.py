"""Feed source CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from hypomnema.api.deps import DB, Scheduler
from hypomnema.api.schemas import FeedCreate, FeedUpdate
from hypomnema.db.models import FeedSource
from hypomnema.ingestion.feeds import (
    create_feed_source,
    delete_feed_source,
    list_feed_sources,
    update_feed_source,
)

router = APIRouter(prefix="/api/feeds", tags=["feeds"])


@router.post("", response_model=FeedSource, status_code=201)
async def create_feed(body: FeedCreate, db: DB, scheduler: Scheduler) -> FeedSource:
    try:
        source = await create_feed_source(db, body.name, body.feed_type, body.url, body.schedule)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if body.active:
        scheduler.add_job(source.id, source.schedule)
    return source


@router.get("", response_model=list[FeedSource])
async def list_feeds(db: DB) -> list[FeedSource]:
    return await list_feed_sources(db)


@router.patch("/{feed_id}", response_model=FeedSource)
async def update_feed(feed_id: str, body: FeedUpdate, db: DB, scheduler: Scheduler) -> FeedSource:
    # Check existence first to distinguish 404 from 400 without string matching
    cursor = await db.execute("SELECT id FROM feed_sources WHERE id = ?", (feed_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    try:
        source = await update_feed_source(
            db, feed_id, name=body.name, url=body.url, schedule=body.schedule, active=body.active
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # Sync scheduler
    if source.active:
        scheduler.add_job(source.id, source.schedule)
    else:
        scheduler.remove_job(source.id)
    return source


@router.delete("/{feed_id}", status_code=204)
async def delete_feed(feed_id: str, db: DB, scheduler: Scheduler) -> Response:
    deleted = await delete_feed_source(db, feed_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Feed not found")
    scheduler.remove_job(feed_id)
    return Response(status_code=204)
