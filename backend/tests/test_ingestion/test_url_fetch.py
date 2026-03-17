"""Tests for URL fetch ingestion, including direct PDF URLs."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import httpx
import pytest
from pypdf import PdfWriter

from hypomnema.ingestion.url_fetch import DuplicateUrlError, fetch_url


class _FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        headers: dict[str, str] | None = None,
        text: str = "",
        content: bytes | None = None,
        status_code: int = 200,
    ) -> None:
        self.url = url
        self.headers = headers or {}
        self._text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.status_code = status_code

    @property
    def text(self) -> str:
        if self._text:
            return self._text
        return self.content.decode("utf-8", errors="ignore")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", self.url)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        return self._response


def _make_blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    payload = io.BytesIO()
    writer.write(payload)
    return payload.getvalue()


def _patch_http_client(monkeypatch: Any, response: _FakeResponse) -> None:
    monkeypatch.setattr(
        "hypomnema.ingestion.url_fetch.httpx.Client",
        lambda *args, **kwargs: _FakeClient(response),
    )


class TestFetchUrl:
    async def test_fetches_direct_pdf_and_stores_pdf_metadata(
        self,
        tmp_db,
        fixtures_dir: Path,
        monkeypatch: Any,
    ) -> None:
        pdf_bytes = (fixtures_dir / "sample.pdf").read_bytes()
        _patch_http_client(
            monkeypatch,
            _FakeResponse(
                url="https://example.com/paper.pdf",
                headers={"content-type": "application/pdf"},
                content=pdf_bytes,
            ),
        )

        doc = await fetch_url(tmp_db, "https://example.com/paper.pdf")

        assert doc.source_type == "url"
        assert doc.mime_type == "application/pdf"
        assert doc.title == "paper"
        assert doc.metadata is not None
        assert doc.metadata["fetch_mode"] == "pdf_url"
        assert doc.metadata["final_url"] == "https://example.com/paper.pdf"
        assert doc.metadata["page_count"] == 1
        assert doc.metadata["file_bytes"] == len(pdf_bytes)

    async def test_detects_pdf_after_redirect_without_pdf_content_type(
        self,
        tmp_db,
        fixtures_dir: Path,
        monkeypatch: Any,
    ) -> None:
        pdf_bytes = (fixtures_dir / "sample.pdf").read_bytes()
        _patch_http_client(
            monkeypatch,
            _FakeResponse(
                url="https://cdn.example.com/archive/policy-brief.pdf",
                headers={"content-type": "application/octet-stream"},
                content=pdf_bytes,
            ),
        )

        doc = await fetch_url(tmp_db, "https://example.com/download?id=42")

        assert doc.mime_type == "application/pdf"
        assert doc.metadata is not None
        assert doc.metadata["final_url"] == "https://cdn.example.com/archive/policy-brief.pdf"

    async def test_detects_pdf_from_attachment_filename_and_magic_header(
        self,
        tmp_db,
        fixtures_dir: Path,
        monkeypatch: Any,
    ) -> None:
        pdf_bytes = (fixtures_dir / "sample.pdf").read_bytes()
        _patch_http_client(
            monkeypatch,
            _FakeResponse(
                url="https://files.example.com/download/42",
                headers={
                    "content-type": "application/octet-stream",
                    "content-disposition": 'attachment; filename="healthcare-ai-ethics.pdf"',
                },
                content=pdf_bytes,
            ),
        )

        doc = await fetch_url(tmp_db, "https://osf.example.com/download/42")

        assert doc.mime_type == "application/pdf"
        assert doc.title == "healthcare-ai-ethics"
        assert doc.metadata is not None
        assert doc.metadata["fetch_mode"] == "pdf_url"

    async def test_rejects_duplicate_original_url(
        self,
        tmp_db,
        fixtures_dir: Path,
        monkeypatch: Any,
    ) -> None:
        pdf_bytes = (fixtures_dir / "sample.pdf").read_bytes()
        _patch_http_client(
            monkeypatch,
            _FakeResponse(
                url="https://example.com/paper.pdf",
                headers={"content-type": "application/pdf"},
                content=pdf_bytes,
            ),
        )

        await fetch_url(tmp_db, "https://example.com/paper.pdf")

        with pytest.raises(DuplicateUrlError):
            await fetch_url(tmp_db, "https://example.com/paper.pdf")

    async def test_rejects_pdf_with_no_extractable_text(
        self,
        tmp_db,
        monkeypatch: Any,
    ) -> None:
        _patch_http_client(
            monkeypatch,
            _FakeResponse(
                url="https://example.com/scanned.pdf",
                headers={"content-type": "application/pdf"},
                content=_make_blank_pdf_bytes(),
            ),
        )

        with pytest.raises(ValueError, match="No extractable text"):
            await fetch_url(tmp_db, "https://example.com/scanned.pdf")

    async def test_article_branch_still_uses_trafilatura(
        self,
        tmp_db,
        monkeypatch: Any,
    ) -> None:
        _patch_http_client(
            monkeypatch,
            _FakeResponse(
                url="https://example.com/post",
                headers={"content-type": "text/html; charset=utf-8"},
                text="<html><head><title>Ignored</title></head><body>Article</body></html>",
            ),
        )
        monkeypatch.setattr(
            "hypomnema.ingestion.url_fetch.trafilatura.bare_extraction",
            lambda *_args, **_kwargs: {
                "text": "Article body",
                "title": "Article title",
                "author": "Researcher",
                "date": "2026-03-16",
            },
        )

        doc = await fetch_url(tmp_db, "https://example.com/post")

        assert doc.mime_type is None
        assert doc.title == "Article title"
        assert doc.metadata == {"author": "Researcher", "date": "2026-03-16"}
