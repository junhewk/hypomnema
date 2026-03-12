"""File parsing: PDF, DOCX, Markdown text extraction and storage."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite

from docx import Document as DocxDocument
from pypdf import PdfReader

from hypomnema.db.models import Document

_MIME_MAP: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
}


class UnsupportedFormatError(ValueError):
    """Raised when a file extension is not supported."""


@dataclasses.dataclass(frozen=True)
class ParsedFile:
    """Result of text extraction from a file."""

    text: str
    mime_type: str
    title: str | None = None


def parse_pdf(path: Path) -> str:
    reader = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if not text:
        raise ValueError(f"No extractable text in {path.name}")
    return text


def parse_docx(path: Path) -> str:
    doc = DocxDocument(str(path))
    text = "\n".join(p.text for p in doc.paragraphs).strip()
    if not text:
        raise ValueError(f"No extractable text in {path.name}")
    return text


def parse_markdown(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"No extractable text in {path.name}")
    return text


_PARSERS = {".pdf": parse_pdf, ".docx": parse_docx, ".md": parse_markdown}


def parse_file(path: Path) -> ParsedFile:
    suffix = path.suffix.lower()
    mime_type = _MIME_MAP.get(suffix)
    if mime_type is None:
        raise UnsupportedFormatError(f"Unsupported format: {suffix}")

    text = _PARSERS[suffix](path)

    return ParsedFile(text=text, mime_type=mime_type, title=path.stem)


async def ingest_file(db: aiosqlite.Connection, path: Path) -> Document:
    parsed = parse_file(path)
    cursor = await db.execute(
        "INSERT INTO documents (source_type, title, text, mime_type, source_uri) "
        "VALUES ('file', ?, ?, ?, ?) RETURNING *",
        (parsed.title, parsed.text, parsed.mime_type, str(path)),
    )
    row = await cursor.fetchone()
    await db.commit()
    assert row is not None
    return Document.from_row(row)
