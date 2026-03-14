"""One-shot URL fetch: article extraction via trafilatura, YouTube via transcript API."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import httpx
import trafilatura

from hypomnema.db.models import Document
from hypomnema.ingestion.feeds import _fetch_transcript, extract_video_id

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)


class DuplicateUrlError(ValueError):
    """Raised when a URL has already been fetched."""

    def __init__(self, existing_id: str) -> None:
        self.existing_id = existing_id
        super().__init__("URL already fetched")


def _fetch_article(url: str) -> tuple[str, str | None, dict[str, str | None]]:
    """Fetch and extract article content. Returns (text, title, metadata)."""
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()

    html = response.text
    extracted = trafilatura.bare_extraction(html, include_tables=True, include_links=False)
    if not isinstance(extracted, dict) or not extracted.get("text"):
        raise ValueError("No extractable content")

    text: str = extracted["text"]
    title: str | None = extracted.get("title")
    meta: dict[str, str | None] = {}
    if extracted.get("author"):
        meta["author"] = extracted["author"]
    if extracted.get("date"):
        meta["date"] = extracted["date"]

    return text, title, meta


def _fetch_oembed_title(url: str) -> str | None:
    """Fetch YouTube video title via oEmbed."""
    resp = httpx.get(f"https://www.youtube.com/oembed?url={url}&format=json", timeout=10)
    if resp.status_code == 200:
        return resp.json().get("title")  # type: ignore[no-any-return]
    return None


async def fetch_url(db: aiosqlite.Connection, url: str) -> Document:
    """Fetch a URL, extract content, and store as a document.

    Raises:
        DuplicateUrlError: If the URL has already been fetched.
        ValueError: If no content could be extracted.
        httpx.HTTPError: On network errors.
    """
    # Deduplicate
    cursor = await db.execute("SELECT id FROM documents WHERE source_uri = ?", (url,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is not None:
        raise DuplicateUrlError(row["id"])

    video_id = extract_video_id(url)
    if video_id is not None:
        # YouTube — fetch transcript and title concurrently
        transcript_task = asyncio.to_thread(_fetch_transcript, video_id)
        title_task = asyncio.to_thread(_fetch_oembed_title, url)
        text, title = await asyncio.gather(transcript_task, title_task, return_exceptions=True)
        if isinstance(text, BaseException):
            raise text
        title = title if isinstance(title, str) else None
        metadata: dict[str, str | None] = {"video_id": video_id}
    else:
        # Article
        text, title, metadata = await asyncio.to_thread(_fetch_article, url)

    metadata_json = json.dumps(metadata) if metadata else None
    cursor = await db.execute(
        "INSERT INTO documents (source_type, title, text, source_uri, metadata) "
        "VALUES ('url', ?, ?, ?, ?) RETURNING *",
        (title, text, url, metadata_json),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise RuntimeError("INSERT RETURNING produced no row")
    await db.commit()
    return Document.from_row(row)
