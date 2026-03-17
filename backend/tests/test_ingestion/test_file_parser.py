"""Tests for ingestion/file_parser.py — file parsing and ingestion."""

from pathlib import Path

import pytest

from hypomnema.db.models import Document
from hypomnema.ingestion.file_parser import (
    ParsedFile,
    UnsupportedFormatError,
    ingest_file,
    parse_file,
    preprocess_pdf_text,
)

from .conftest import SAMPLE_TEXT


class TestParseFile:
    def test_preprocess_pdf_text_removes_repeated_margins_and_joins_wrapped_lines(self) -> None:
        text = preprocess_pdf_text([
            "Healthcare AI Ethics\n1\nAI can trans-\nform care.",
            "Healthcare AI Ethics\n2\nThis para-\ngraph spans lines.",
            "Healthcare AI Ethics\n3\nReferences\n[1] Example reference",
        ])

        assert "Healthcare AI Ethics" not in text
        assert "\n1\n" not in text
        assert "transform care." in text
        assert "This paragraph spans lines." in text
        assert "References\n\n[1] Example reference" in text

    def test_preprocess_pdf_text_trims_backmatter_sections_in_long_documents(self) -> None:
        descriptors = [
            "governance", "privacy", "fairness", "autonomy", "accountability", "traceability",
            "safety", "bias", "oversight", "equity", "consent", "transparency", "robustness",
            "accessibility", "procurement", "monitoring", "reliability", "stewardship", "auditing",
        ]
        page_texts = [
            (
                f"Page {index}\nSection {index}\n"
                f"Main body paragraph on {descriptor} topic.\n"
                f"Distinct finding about {descriptor} for healthcare AI oversight."
            )
            for index, descriptor in enumerate(descriptors, start=1)
        ]
        page_texts.extend([
            "Page 20\nAppendix\nAppendix detail 1.",
            "Page 21\nReferences\n[1] Example reference",
            "Page 22\nAcknowledgements\nThanks.",
        ])

        text = preprocess_pdf_text(page_texts)

        assert "Distinct finding about auditing for healthcare AI oversight." in text
        assert "Appendix detail 1." not in text
        assert "[1] Example reference" not in text
        assert "Thanks." not in text

    def test_pdf_extracts_text(self, fixtures_dir: Path):
        result = parse_file(fixtures_dir / "sample.pdf")
        assert SAMPLE_TEXT in result.text

    def test_docx_extracts_text(self, fixtures_dir: Path):
        result = parse_file(fixtures_dir / "sample.docx")
        assert SAMPLE_TEXT in result.text

    def test_md_extracts_text(self, fixtures_dir: Path):
        result = parse_file(fixtures_dir / "sample.md")
        assert SAMPLE_TEXT in result.text

    def test_title_derived_from_filename(self, fixtures_dir: Path):
        result = parse_file(fixtures_dir / "sample.pdf")
        assert result.title == "sample"

    def test_unsupported_format_raises(self, tmp_path: Path):
        txt_file = tmp_path / "file.txt"
        txt_file.write_text("hello")
        with pytest.raises(UnsupportedFormatError, match="Unsupported format"):
            parse_file(txt_file)

    def test_nonexistent_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            parse_file(tmp_path / "nope.pdf")

    def test_correct_mime_types(self, fixtures_dir: Path):
        assert parse_file(fixtures_dir / "sample.pdf").mime_type == "application/pdf"
        assert (
            parse_file(fixtures_dir / "sample.docx").mime_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert parse_file(fixtures_dir / "sample.md").mime_type == "text/markdown"

    def test_returns_parsed_file(self, fixtures_dir: Path):
        result = parse_file(fixtures_dir / "sample.md")
        assert isinstance(result, ParsedFile)


class TestIngestFile:
    async def test_stores_with_file_source_type(self, tmp_db, fixtures_dir: Path):
        doc = await ingest_file(tmp_db, fixtures_dir / "sample.md")
        assert doc.source_type == "file"

    async def test_returns_document_model(self, tmp_db, fixtures_dir: Path):
        doc = await ingest_file(tmp_db, fixtures_dir / "sample.md")
        assert isinstance(doc, Document)

    async def test_correct_mime_type_pdf(self, tmp_db, fixtures_dir: Path):
        doc = await ingest_file(tmp_db, fixtures_dir / "sample.pdf")
        assert doc.mime_type == "application/pdf"

    async def test_correct_mime_type_docx(self, tmp_db, fixtures_dir: Path):
        doc = await ingest_file(tmp_db, fixtures_dir / "sample.docx")
        assert doc.mime_type == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    async def test_correct_mime_type_md(self, tmp_db, fixtures_dir: Path):
        doc = await ingest_file(tmp_db, fixtures_dir / "sample.md")
        assert doc.mime_type == "text/markdown"

    async def test_title_stored(self, tmp_db, fixtures_dir: Path):
        doc = await ingest_file(tmp_db, fixtures_dir / "sample.pdf")
        assert doc.title == "sample"

    async def test_source_uri_stored(self, tmp_db, fixtures_dir: Path):
        pdf_path = fixtures_dir / "sample.pdf"
        doc = await ingest_file(tmp_db, pdf_path)
        assert doc.source_uri == str(pdf_path)

    async def test_persisted_in_database(self, tmp_db, fixtures_dir: Path):
        doc = await ingest_file(tmp_db, fixtures_dir / "sample.md")
        cursor = await tmp_db.execute(
            "SELECT * FROM documents WHERE id = ?", (doc.id,)
        )
        row = await cursor.fetchone()
        assert row is not None
        assert SAMPLE_TEXT in row["text"]
