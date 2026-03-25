"""Fixtures for ingestion tests."""

from pathlib import Path

import pytest

SAMPLE_TEXT = "Hypomnema is an automated ontological synthesizer."


def _create_sample_pdf(path: Path, text: str) -> None:
    """Create a minimal PDF with extractable text using pypdf."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    w = PdfWriter()
    page = w.add_blank_page(width=612, height=792)

    # Raw content stream with text operator
    escaped = text.replace("(", r"\(").replace(")", r"\)")
    content = f"BT /F1 12 Tf 100 700 Td ({escaped}) Tj ET".encode()
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = w._add_object(stream)

    # Font resource (Type1 Helvetica — built-in, no embedding needed)
    font_dict = DictionaryObject()
    font_dict[NameObject("/Type")] = NameObject("/Font")
    font_dict[NameObject("/Subtype")] = NameObject("/Type1")
    font_dict[NameObject("/BaseFont")] = NameObject("/Helvetica")
    resources = DictionaryObject()
    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = w._add_object(font_dict)
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources

    with open(path, "wb") as f:
        w.write(f)


def _create_sample_docx(path: Path, text: str) -> None:
    """Create a minimal DOCX with one paragraph."""
    from docx import Document as DocxDocument

    doc = DocxDocument()
    doc.add_paragraph(text)
    doc.save(str(path))


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    """Directory containing sample.pdf, sample.docx, sample.md."""
    _create_sample_pdf(tmp_path / "sample.pdf", SAMPLE_TEXT)
    _create_sample_docx(tmp_path / "sample.docx", SAMPLE_TEXT)
    (tmp_path / "sample.md").write_text(f"# Sample\n\n{SAMPLE_TEXT}", encoding="utf-8")
    return tmp_path
