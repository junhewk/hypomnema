"""One-shot URL fetch: article extraction via trafilatura, PDF parsing, YouTube via transcript API."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

import httpx
import trafilatura

from hypomnema.db.models import Document
from hypomnema.ingestion.feeds import _fetch_transcript, extract_video_id
from hypomnema.ingestion.file_parser import inspect_pdf

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)


class DuplicateUrlError(ValueError):
    """Raised when a URL has already been fetched."""

    def __init__(self, existing_id: str) -> None:
        self.existing_id = existing_id
        super().__init__("URL already fetched")


@dataclasses.dataclass(frozen=True)
class WebFetchResult:
    text: str
    title: str | None
    metadata: dict[str, object | str | None]
    mime_type: str | None = None


_CONTENT_DISPOSITION_FILENAME_RE = re.compile(
    r"""filename\*?=(?:UTF-8''|")?(?P<filename>[^";]+)""",
    re.IGNORECASE,
)


def _normalized_content_type(response: httpx.Response) -> str | None:
    content_type = response.headers.get("content-type", "")
    if not content_type:
        return None
    return content_type.split(";", 1)[0].strip().lower() or None


def _looks_like_pdf_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".pdf")


def _looks_like_pdf_content(content: bytes) -> bool:
    return content.lstrip().startswith(b"%PDF-")


def _is_pdf_response(requested_url: str, response: httpx.Response) -> bool:
    content_type = _normalized_content_type(response)
    filename = _response_filename(response)
    return (
        content_type == "application/pdf"
        or _looks_like_pdf_url(requested_url)
        or _looks_like_pdf_url(str(response.url))
        or (filename is not None and filename.lower().endswith(".pdf"))
        or _looks_like_pdf_content(response.content)
    )


def _response_filename(response: httpx.Response) -> str | None:
    content_disposition = response.headers.get("content-disposition", "")
    match = _CONTENT_DISPOSITION_FILENAME_RE.search(content_disposition)
    if match is not None:
        filename = match.group("filename").strip()
        if filename:
            return unquote(filename)

    path = unquote(urlparse(str(response.url)).path)
    name = Path(path).name
    return name or None


def _response_title(response: httpx.Response) -> str | None:
    filename = _response_filename(response)
    if not filename:
        return None
    stem = Path(filename).stem.strip()
    return stem or None


def _extract_article(response: httpx.Response) -> WebFetchResult:
    """Extract article content from an HTTP response."""
    html = response.text
    extracted = trafilatura.bare_extraction(html, include_tables=True, include_links=False)
    if not isinstance(extracted, dict) or not extracted.get("text"):
        raise ValueError("No extractable content")

    text = str(extracted["text"])
    title = str(extracted.get("title")) if extracted.get("title") else None
    meta: dict[str, object | str | None] = {}
    if extracted.get("author"):
        meta["author"] = extracted["author"]
    if extracted.get("date"):
        meta["date"] = extracted["date"]

    return WebFetchResult(text=text, title=title, metadata=meta)


def _extract_pdf(response: httpx.Response) -> WebFetchResult:
    """Extract PDF content from an HTTP response."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(response.content)
        tmp_path = Path(tmp.name)

    try:
        parsed = inspect_pdf(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    metadata: dict[str, object | str | None] = {
        "fetch_mode": "pdf_url",
        "final_url": str(response.url),
        "content_type": _normalized_content_type(response),
        "file_bytes": len(response.content),
        "page_count": parsed.page_count,
    }
    return WebFetchResult(
        text=parsed.text,
        title=_response_title(response),
        metadata=metadata,
        mime_type="application/pdf",
    )


def _fetch_web_content(url: str) -> WebFetchResult:
    """Fetch a URL and extract either PDF or article content."""
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()

    if _is_pdf_response(url, response):
        return _extract_pdf(response)
    return _extract_article(response)


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
    cursor = await db.execute("SELECT id FROM documents WHERE source_uri = ?", (url,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is not None:
        raise DuplicateUrlError(row["id"])

    video_id = extract_video_id(url)
    if video_id is not None:
        transcript_task = asyncio.to_thread(_fetch_transcript, video_id)
        title_task = asyncio.to_thread(_fetch_oembed_title, url)
        text, title = await asyncio.gather(transcript_task, title_task, return_exceptions=True)
        if isinstance(text, BaseException):
            raise text
        title = title if isinstance(title, str) else None
        metadata: dict[str, object | str | None] = {"video_id": video_id}
        mime_type: str | None = None
    else:
        fetched = await asyncio.to_thread(_fetch_web_content, url)
        text = fetched.text
        title = fetched.title
        metadata = fetched.metadata
        mime_type = fetched.mime_type

    metadata_json = json.dumps(metadata) if metadata else None
    cursor = await db.execute(
        "INSERT INTO documents (source_type, title, text, mime_type, source_uri, metadata) "
        "VALUES ('url', ?, ?, ?, ?, ?) RETURNING *",
        (title, text, mime_type, url, metadata_json),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        raise RuntimeError("INSERT RETURNING produced no row")
    await db.commit()
    return Document.from_row(row)
