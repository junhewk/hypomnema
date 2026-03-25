"""Tests for ingestion/scribble.py — scribble creation and storage."""

import pytest

from hypomnema.db.models import Document
from hypomnema.ingestion.scribble import create_scribble


class TestCreateScribble:
    async def test_stores_with_scribble_source_type(self, tmp_db):
        doc = await create_scribble(tmp_db, "Hello world")
        assert doc.source_type == "scribble"

    async def test_returns_document_model(self, tmp_db):
        doc = await create_scribble(tmp_db, "Hello world")
        assert isinstance(doc, Document)

    async def test_empty_text_rejected(self, tmp_db):
        with pytest.raises(ValueError, match="must not be empty"):
            await create_scribble(tmp_db, "")

    async def test_whitespace_only_rejected(self, tmp_db):
        with pytest.raises(ValueError, match="must not be empty"):
            await create_scribble(tmp_db, "   \n\t  ")

    async def test_optional_title_stored(self, tmp_db):
        doc = await create_scribble(tmp_db, "content", title="My Note")
        assert doc.title == "My Note"

    async def test_title_none_by_default(self, tmp_db):
        doc = await create_scribble(tmp_db, "content")
        assert doc.title is None

    async def test_text_is_stripped(self, tmp_db):
        doc = await create_scribble(tmp_db, "  padded text  \n")
        assert doc.text == "padded text"

    async def test_persisted_in_database(self, tmp_db):
        doc = await create_scribble(tmp_db, "persistent")
        cursor = await tmp_db.execute("SELECT * FROM documents WHERE id = ?", (doc.id,))
        row = await cursor.fetchone()
        assert row is not None
        assert row["text"] == "persistent"

    async def test_fts_indexed(self, tmp_db):
        await create_scribble(tmp_db, "xylophone unique search term")
        cursor = await tmp_db.execute("SELECT * FROM documents_fts WHERE documents_fts MATCH 'xylophone'")
        rows = await cursor.fetchall()
        assert len(rows) == 1
