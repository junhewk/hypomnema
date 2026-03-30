"""Feed ingestion: RSS, web scrape, YouTube transcript fetching."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    import aiosqlite

import feedparser
import httpx
from youtube_transcript_api import YouTubeTranscriptApi

from hypomnema.db.models import Document, FeedSource
from hypomnema.db.transactions import immediate_transaction

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class FetchedItem:
    """Single item extracted from a feed source."""

    title: str | None
    text: str
    source_uri: str
    metadata: dict[str, Any] | None = None


# ── Helpers ───────────────────────────────────────────────


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        path = parsed.path.lstrip("/").split("/")[0]
        return path or None
    if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            ids = qs.get("v")
            return ids[0] if ids else None
        match = re.match(r"^/(embed|v)/([^/?]+)", parsed.path)
        if match:
            return match.group(2)
    return None


def _strip_html(html: str) -> str:
    """Remove HTML tags, leaving plain text."""
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _extract_html_title(html: str) -> str | None:
    """Extract <title> content from HTML."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _fetch_transcript(video_id: str) -> str:
    """Fetch and concatenate YouTube transcript snippets."""
    yt = YouTubeTranscriptApi()
    transcript = yt.fetch(video_id)
    return " ".join(snippet.text for snippet in transcript.snippets)


# ── Fetchers (sync, pure network I/O) ────────────────────


def fetch_rss(url: str, *, timeout: float = 30.0) -> list[FetchedItem]:
    """Parse an RSS/Atom feed and return entries as FetchedItems."""
    with httpx.Client(timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()

    feed = feedparser.parse(response.text)
    items: list[FetchedItem] = []
    for entry in feed.entries:
        text = _strip_html(entry.get("summary", "") or entry.get("title", "")).strip()
        if not text:
            continue
        link = entry.get("link", url)
        title = entry.get("title")
        published = entry.get("published")
        metadata = {"published": published} if published else None
        items.append(FetchedItem(title=title, text=text, source_uri=link, metadata=metadata))
    return items


def fetch_scrape(url: str, *, timeout: float = 30.0) -> list[FetchedItem]:
    """Scrape a web page and return its text content."""
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()

    html = response.text
    title = _extract_html_title(html)
    text = _strip_html(html).strip()
    if not text:
        raise ValueError(f"No extractable text from {url}")

    return [FetchedItem(title=title, text=text, source_uri=url)]


def fetch_youtube(url: str, *, timeout: float = 30.0) -> list[FetchedItem]:
    """Extract transcript(s) from YouTube video(s).

    Supports single video URLs and channel RSS feeds.
    """
    if "/feeds/videos.xml" in url:
        # Channel RSS — parse feed, then fetch transcripts per video
        rss_items = fetch_rss(url, timeout=timeout)
        items: list[FetchedItem] = []
        for rss_item in rss_items:
            video_id = extract_video_id(rss_item.source_uri)
            if video_id is None:
                continue
            try:
                text = _fetch_transcript(video_id)
            except Exception:
                logger.warning("Failed to fetch transcript for %s", video_id)
                continue
            items.append(
                FetchedItem(
                    title=rss_item.title,
                    text=text,
                    source_uri=rss_item.source_uri,
                    metadata={"video_id": video_id},
                )
            )
        return items

    # Single video URL
    video_id = extract_video_id(url)
    if video_id is None:
        raise ValueError(f"Could not extract video ID from {url}")
    text = _fetch_transcript(video_id)
    return [
        FetchedItem(
            title=None,
            text=text,
            source_uri=url,
            metadata={"video_id": video_id},
        )
    ]


_FETCHERS: dict[str, Any] = {
    "rss": fetch_rss,
    "scrape": fetch_scrape,
    "youtube": fetch_youtube,
}


# ── Ingestion (async, DB) ────────────────────────────────


async def ingest_feed_items(
    db: aiosqlite.Connection,
    items: list[FetchedItem],
) -> list[Document]:
    """Insert feed items as documents, skipping duplicates by source_uri.

    Returns list of newly created documents (excludes duplicates).
    """
    if not items:
        return []

    created: list[Document] = []
    async with immediate_transaction(db):
        uris = [item.source_uri for item in items]
        placeholders = ", ".join("?" for _ in uris)
        cursor = await db.execute(
            f"SELECT source_uri FROM documents WHERE source_uri IN ({placeholders})",
            uris,
        )
        existing_uris = {row["source_uri"] for row in await cursor.fetchall()}
        await cursor.close()

        for item in items:
            if item.source_uri in existing_uris:
                continue

            metadata_json = json.dumps(item.metadata) if item.metadata else None
            cursor = await db.execute(
                "INSERT INTO documents (source_type, title, text, source_uri, metadata) "
                "VALUES ('feed', ?, ?, ?, ?) RETURNING *",
                (item.title, item.text, item.source_uri, metadata_json),
            )
            row = await cursor.fetchone()
            await cursor.close()
            assert row is not None
            created.append(Document.from_row(row))
            existing_uris.add(item.source_uri)

    return created


async def poll_feed(
    db: aiosqlite.Connection,
    feed_source: FeedSource,
    *,
    timeout: float = 30.0,
) -> list[Document]:
    """Fetch items from a feed source and ingest new ones.

    Dispatches to the correct fetcher (run in thread to avoid blocking),
    inserts new documents, updates last_fetched timestamp.
    """
    fetcher = _FETCHERS.get(feed_source.feed_type)
    if fetcher is None:
        raise ValueError(f"Unknown feed type: {feed_source.feed_type}")

    items = await asyncio.to_thread(fetcher, feed_source.url, timeout=timeout)
    docs = await ingest_feed_items(db, items)

    async with immediate_transaction(db):
        await db.execute(
            "UPDATE feed_sources SET last_fetched = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (feed_source.id,),
        )
    return docs


# ── Feed Source CRUD ──────────────────────────────────────


async def create_feed_source(
    db: aiosqlite.Connection,
    name: str,
    feed_type: str,
    url: str,
    schedule: str = "0 */6 * * *",
) -> FeedSource:
    """Create a new feed source.

    Raises:
        ValueError: If feed_type is invalid.
    """
    if feed_type not in ("rss", "scrape", "youtube"):
        raise ValueError(f"Invalid feed_type: {feed_type}")

    async with immediate_transaction(db):
        cursor = await db.execute(
            "INSERT INTO feed_sources (name, feed_type, url, schedule) VALUES (?, ?, ?, ?) RETURNING *",
            (name, feed_type, url, schedule),
        )
        row = await cursor.fetchone()
        await cursor.close()
    assert row is not None
    return FeedSource.from_row(row)


async def list_feed_sources(
    db: aiosqlite.Connection,
    *,
    active_only: bool = False,
) -> list[FeedSource]:
    """List feed sources, optionally filtered to active ones."""
    query = "SELECT * FROM feed_sources"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY created_at"
    cursor = await db.execute(query)
    rows = await cursor.fetchall()
    await cursor.close()
    return [FeedSource.from_row(r) for r in rows]


async def update_feed_source(
    db: aiosqlite.Connection,
    feed_id: str,
    *,
    name: str | None = None,
    url: str | None = None,
    schedule: str | None = None,
    active: bool | None = None,
) -> FeedSource:
    """Update a feed source. Only provided fields are updated.

    Raises:
        ValueError: If no fields provided or feed_id not found.
    """
    updates: list[str] = []
    params: list[str | int] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if url is not None:
        updates.append("url = ?")
        params.append(url)
    if schedule is not None:
        updates.append("schedule = ?")
        params.append(schedule)
    if active is not None:
        updates.append("active = ?")
        params.append(int(active))

    if not updates:
        raise ValueError("No fields to update")

    params.append(feed_id)
    async with immediate_transaction(db):
        cursor = await db.execute(
            f"UPDATE feed_sources SET {', '.join(updates)} WHERE id = ? RETURNING *",
            params,
        )
        row = await cursor.fetchone()
        await cursor.close()
    if row is None:
        raise ValueError(f"Feed source {feed_id} not found")
    return FeedSource.from_row(row)


async def delete_feed_source(
    db: aiosqlite.Connection,
    feed_id: str,
) -> bool:
    """Delete a feed source. Returns True if deleted, False if not found."""
    async with immediate_transaction(db):
        cursor = await db.execute("DELETE FROM feed_sources WHERE id = ? RETURNING id", (feed_id,))
        row = await cursor.fetchone()
        await cursor.close()
    return row is not None
