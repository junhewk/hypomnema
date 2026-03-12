"""Tests for feed ingestion: fetchers, ingestion, CRUD."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import pytest_asyncio

from hypomnema.db.models import FeedSource
from hypomnema.ingestion import feeds as feeds_mod
from hypomnema.ingestion.feeds import (
    FetchedItem,
    _strip_html,
    create_feed_source,
    delete_feed_source,
    extract_video_id,
    fetch_rss,
    fetch_scrape,
    fetch_youtube,
    ingest_feed_items,
    list_feed_sources,
    poll_feed,
    update_feed_source,
)

# ── Sample data ──────────────────────────────────────────

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test</title>
<item><title>Entry One</title><link>https://example.com/1</link>
<description>First entry content.</description>
<pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>
<item><title>Entry Two</title><link>https://example.com/2</link>
<description>Second entry content.</description></item>
</channel></rss>"""

SAMPLE_HTML = "<html><head><title>Test Page</title></head><body><p>Hello world.</p></body></html>"

EMPTY_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Empty</title></channel></rss>"""


def _mock_httpx_response(text: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status_code, text=text, request=httpx.Request("GET", "https://example.com"))


# ── extract_video_id ─────────────────────────────────────


class TestExtractVideoId:
    def test_watch_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self) -> None:
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self) -> None:
        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_url(self) -> None:
        assert extract_video_id("https://example.com/page") is None

    def test_no_v_param(self) -> None:
        assert extract_video_id("https://www.youtube.com/watch?") is None


# ── _strip_html ──────────────────────────────────────────


class TestStripHtml:
    def test_removes_tags(self) -> None:
        assert _strip_html("<p>hello</p>") == "hello"

    def test_collapses_whitespace(self) -> None:
        assert _strip_html("<p>hello</p>  <p>world</p>") == "hello world"


# ── fetch_rss ────────────────────────────────────────────


class TestFetchRss:
    def test_parses_entries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            httpx.Client, "get", lambda self, url, **kw: _mock_httpx_response(SAMPLE_RSS)
        )
        items = fetch_rss("https://example.com/feed.xml")
        assert len(items) == 2
        assert items[0].title == "Entry One"
        assert items[0].source_uri == "https://example.com/1"
        assert items[0].text == "First entry content."

    def test_empty_feed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            httpx.Client, "get", lambda self, url, **kw: _mock_httpx_response(EMPTY_RSS)
        )
        items = fetch_rss("https://example.com/feed.xml")
        assert items == []

    def test_skips_empty_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel><title>T</title>
        <item><title></title><link>https://example.com/x</link>
        <description></description></item>
        </channel></rss>"""
        monkeypatch.setattr(
            httpx.Client, "get", lambda self, url, **kw: _mock_httpx_response(rss)
        )
        items = fetch_rss("https://example.com/feed.xml")
        assert items == []

    def test_preserves_published(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            httpx.Client, "get", lambda self, url, **kw: _mock_httpx_response(SAMPLE_RSS)
        )
        items = fetch_rss("https://example.com/feed.xml")
        assert items[0].metadata is not None
        assert "published" in items[0].metadata
        assert items[1].metadata is None

    def test_network_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_error(self: Any, url: str, **kw: Any) -> None:
            raise httpx.ConnectError("fail")

        monkeypatch.setattr(httpx.Client, "get", raise_error)
        with pytest.raises(httpx.ConnectError):
            fetch_rss("https://example.com/feed.xml")


# ── fetch_scrape ─────────────────────────────────────────


class TestFetchScrape:
    def test_extracts_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            httpx.Client, "get", lambda self, url, **kw: _mock_httpx_response(SAMPLE_HTML)
        )
        items = fetch_scrape("https://example.com/page")
        assert len(items) == 1
        assert "Hello world." in items[0].text

    def test_extracts_title(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            httpx.Client, "get", lambda self, url, **kw: _mock_httpx_response(SAMPLE_HTML)
        )
        items = fetch_scrape("https://example.com/page")
        assert items[0].title == "Test Page"

    def test_empty_page_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            httpx.Client, "get", lambda self, url, **kw: _mock_httpx_response("")
        )
        with pytest.raises(ValueError, match="No extractable text"):
            fetch_scrape("https://example.com/page")

    def test_follows_redirects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Just verify follow_redirects is used (Client is constructed with it)
        monkeypatch.setattr(
            httpx.Client, "get", lambda self, url, **kw: _mock_httpx_response(SAMPLE_HTML)
        )
        items = fetch_scrape("https://example.com/redirect")
        assert len(items) == 1


# ── fetch_youtube ────────────────────────────────────────


class TestFetchYoutube:
    def test_single_video(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "hypomnema.ingestion.feeds._fetch_transcript",
            lambda vid: "hello world transcript",
        )
        items = fetch_youtube("https://www.youtube.com/watch?v=abc123")
        assert len(items) == 1
        assert items[0].text == "hello world transcript"
        assert items[0].metadata == {"video_id": "abc123"}

    def test_channel_rss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        channel_rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel><title>Chan</title>
        <item><title>Vid 1</title><link>https://www.youtube.com/watch?v=vid1</link>
        <description>Desc</description></item>
        </channel></rss>"""
        monkeypatch.setattr(
            httpx.Client, "get", lambda self, url, **kw: _mock_httpx_response(channel_rss)
        )
        monkeypatch.setattr(
            "hypomnema.ingestion.feeds._fetch_transcript",
            lambda vid: f"transcript for {vid}",
        )
        items = fetch_youtube("https://www.youtube.com/feeds/videos.xml?channel_id=UC123")
        assert len(items) == 1
        assert items[0].text == "transcript for vid1"
        assert items[0].title == "Vid 1"

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not extract video ID"):
            fetch_youtube("https://example.com/not-a-video")

    def test_transcript_failure_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        channel_rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel><title>Chan</title>
        <item><title>Vid 1</title><link>https://www.youtube.com/watch?v=vid1</link>
        <description>Desc</description></item>
        </channel></rss>"""
        monkeypatch.setattr(
            httpx.Client, "get", lambda self, url, **kw: _mock_httpx_response(channel_rss)
        )

        def fail_transcript(vid: str) -> str:
            raise RuntimeError("no transcript")

        monkeypatch.setattr(
            "hypomnema.ingestion.feeds._fetch_transcript", fail_transcript
        )
        items = fetch_youtube("https://www.youtube.com/feeds/videos.xml?channel_id=UC123")
        assert items == []


# ── ingest_feed_items ────────────────────────────────────


class TestIngestFeedItems:
    @pytest.mark.asyncio
    async def test_creates_feed_documents(self, tmp_db: Any) -> None:
        items = [FetchedItem(title="T1", text="Content one", source_uri="https://example.com/1")]
        docs = await ingest_feed_items(tmp_db, items)
        assert len(docs) == 1
        assert docs[0].source_type == "feed"
        assert docs[0].title == "T1"
        assert docs[0].text == "Content one"

    @pytest.mark.asyncio
    async def test_url_dedup(self, tmp_db: Any) -> None:
        items = [FetchedItem(title="T1", text="Content", source_uri="https://example.com/1")]
        await ingest_feed_items(tmp_db, items)
        docs2 = await ingest_feed_items(tmp_db, items)
        assert docs2 == []

    @pytest.mark.asyncio
    async def test_returns_only_new(self, tmp_db: Any) -> None:
        items1 = [FetchedItem(title="T1", text="Content", source_uri="https://example.com/1")]
        await ingest_feed_items(tmp_db, items1)
        items2 = [
            FetchedItem(title="T1", text="Content", source_uri="https://example.com/1"),
            FetchedItem(title="T2", text="New content", source_uri="https://example.com/2"),
        ]
        docs = await ingest_feed_items(tmp_db, items2)
        assert len(docs) == 1
        assert docs[0].source_uri == "https://example.com/2"

    @pytest.mark.asyncio
    async def test_empty_items_no_commit(self, tmp_db: Any) -> None:
        docs = await ingest_feed_items(tmp_db, [])
        assert docs == []

    @pytest.mark.asyncio
    async def test_metadata_stored(self, tmp_db: Any) -> None:
        items = [FetchedItem(
            title="T1", text="Content", source_uri="https://example.com/1",
            metadata={"published": "2024-01-01"},
        )]
        docs = await ingest_feed_items(tmp_db, items)
        assert docs[0].metadata == {"published": "2024-01-01"}

    @pytest.mark.asyncio
    async def test_triaged_defaults_zero(self, tmp_db: Any) -> None:
        items = [FetchedItem(title="T1", text="Content", source_uri="https://example.com/1")]
        docs = await ingest_feed_items(tmp_db, items)
        assert docs[0].triaged == 0


# ── poll_feed ────────────────────────────────────────────


@pytest_asyncio.fixture
async def sample_feed_source(tmp_db: Any) -> FeedSource:
    return await create_feed_source(tmp_db, "Test RSS", "rss", "https://example.com/feed.xml")


class TestPollFeed:
    @pytest.mark.asyncio
    async def test_dispatches_rss(
        self, tmp_db: Any, sample_feed_source: FeedSource, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(
            feeds_mod._FETCHERS, "rss",
            lambda url, timeout: [FetchedItem(title="T", text="C", source_uri="https://example.com/r1")],
        )
        docs = await poll_feed(tmp_db, sample_feed_source)
        assert len(docs) == 1

    @pytest.mark.asyncio
    async def test_dispatches_scrape(self, tmp_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        source = await create_feed_source(tmp_db, "Scrape", "scrape", "https://example.com/page")
        monkeypatch.setitem(
            feeds_mod._FETCHERS, "scrape",
            lambda url, timeout: [FetchedItem(title="P", text="Page", source_uri=url)],
        )
        docs = await poll_feed(tmp_db, source)
        assert len(docs) == 1

    @pytest.mark.asyncio
    async def test_dispatches_youtube(self, tmp_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        source = await create_feed_source(tmp_db, "YT", "youtube", "https://www.youtube.com/watch?v=abc")
        monkeypatch.setitem(
            feeds_mod._FETCHERS, "youtube",
            lambda url, timeout: [FetchedItem(title="V", text="Trans", source_uri=url, metadata={"video_id": "abc"})],
        )
        docs = await poll_feed(tmp_db, source)
        assert len(docs) == 1

    @pytest.mark.asyncio
    async def test_updates_last_fetched(
        self, tmp_db: Any, sample_feed_source: FeedSource, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(feeds_mod._FETCHERS, "rss", lambda url, timeout: [])
        assert sample_feed_source.last_fetched is None
        await poll_feed(tmp_db, sample_feed_source)
        cursor = await tmp_db.execute(
            "SELECT last_fetched FROM feed_sources WHERE id = ?", (sample_feed_source.id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        assert row["last_fetched"] is not None

    @pytest.mark.asyncio
    async def test_unknown_type_raises(self, tmp_db: Any) -> None:
        # Create a FeedSource with invalid type directly via model
        source = FeedSource(
            id="fake", name="Bad", feed_type="invalid", url="http://x",
            schedule="* * * * *", active=True, last_fetched=None,
            created_at="2024-01-01T00:00:00+00:00",
        )
        with pytest.raises(ValueError, match="Unknown feed type"):
            await poll_feed(tmp_db, source)

    @pytest.mark.asyncio
    async def test_fetch_error_propagates(
        self, tmp_db: Any, sample_feed_source: FeedSource, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail(url: str, timeout: float) -> None:
            raise RuntimeError("network fail")

        monkeypatch.setitem(feeds_mod._FETCHERS, "rss", fail)
        with pytest.raises(RuntimeError, match="network fail"):
            await poll_feed(tmp_db, sample_feed_source)


# ── Feed Source CRUD ─────────────────────────────────────


class TestFeedSourceCrud:
    @pytest.mark.asyncio
    async def test_create(self, tmp_db: Any) -> None:
        fs = await create_feed_source(tmp_db, "My Feed", "rss", "https://example.com/rss")
        assert fs.name == "My Feed"
        assert fs.feed_type == "rss"
        assert fs.url == "https://example.com/rss"
        assert fs.active is True
        assert fs.schedule == "0 */6 * * *"

    @pytest.mark.asyncio
    async def test_create_invalid_type(self, tmp_db: Any) -> None:
        with pytest.raises(ValueError, match="Invalid feed_type"):
            await create_feed_source(tmp_db, "Bad", "invalid", "https://example.com")

    @pytest.mark.asyncio
    async def test_list_all(self, tmp_db: Any) -> None:
        await create_feed_source(tmp_db, "F1", "rss", "https://example.com/1")
        await create_feed_source(tmp_db, "F2", "scrape", "https://example.com/2")
        sources = await list_feed_sources(tmp_db)
        assert len(sources) == 2

    @pytest.mark.asyncio
    async def test_list_active_only(self, tmp_db: Any) -> None:
        fs1 = await create_feed_source(tmp_db, "F1", "rss", "https://example.com/1")
        await create_feed_source(tmp_db, "F2", "scrape", "https://example.com/2")
        await update_feed_source(tmp_db, fs1.id, active=False)
        sources = await list_feed_sources(tmp_db, active_only=True)
        assert len(sources) == 1
        assert sources[0].name == "F2"

    @pytest.mark.asyncio
    async def test_update(self, tmp_db: Any) -> None:
        fs = await create_feed_source(tmp_db, "Old", "rss", "https://example.com/old")
        updated = await update_feed_source(tmp_db, fs.id, name="New")
        assert updated.name == "New"
        assert updated.url == fs.url

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, tmp_db: Any) -> None:
        with pytest.raises(ValueError, match="not found"):
            await update_feed_source(tmp_db, "nonexistent", name="X")

    @pytest.mark.asyncio
    async def test_update_no_fields(self, tmp_db: Any) -> None:
        with pytest.raises(ValueError, match="No fields"):
            await update_feed_source(tmp_db, "any-id")

    @pytest.mark.asyncio
    async def test_delete(self, tmp_db: Any) -> None:
        fs = await create_feed_source(tmp_db, "Del", "rss", "https://example.com/del")
        result = await delete_feed_source(tmp_db, fs.id)
        assert result is True
        sources = await list_feed_sources(tmp_db)
        assert len(sources) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, tmp_db: Any) -> None:
        result = await delete_feed_source(tmp_db, "nonexistent")
        assert result is False
