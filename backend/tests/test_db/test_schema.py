"""Tests for db/schema.py — DDL, constraints, virtual tables, triggers."""

import json
import struct
from datetime import datetime
from pathlib import Path

import pytest

from hypomnema.db.engine import get_connection
from hypomnema.db.models import Document, Edge, Engram, FeedSource, Projection
from hypomnema.db.schema import create_tables, ensure_vec_tables, get_vec_table_embedding_dim


def _float_list_to_bytes(floats: list[float]) -> bytes:
    """Pack floats into little-endian binary blob for sqlite-vec."""
    return struct.pack(f"<{len(floats)}f", *floats)


async def _fetch_table_sql(db, table_name: str) -> str | None:
    cursor = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return str(row["sql"]) if row["sql"] is not None else None


async def _fetch_trigger_table(db, trigger_name: str) -> str | None:
    cursor = await db.execute(
        "SELECT tbl_name FROM sqlite_master WHERE type = 'trigger' AND name = ?",
        (trigger_name,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return str(row["tbl_name"])


async def _fetch_index_table(db, index_name: str) -> str | None:
    cursor = await db.execute(
        "SELECT tbl_name FROM sqlite_master WHERE type = 'index' AND name = ?",
        (index_name,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return str(row["tbl_name"])


async def _fetch_fk_parents(db, table_name: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA foreign_key_list({table_name})")  # noqa: S608
    rows = await cursor.fetchall()
    await cursor.close()
    return {str(row["table"]) for row in rows}


async def _fetch_table_columns(db, table_name: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table_name})")  # noqa: S608
    rows = await cursor.fetchall()
    await cursor.close()
    return {str(row["name"]) for row in rows}


async def _count_rows(db, table_name: str) -> int:
    cursor = await db.execute(f"SELECT count(*) FROM {table_name}")  # noqa: S608
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    return int(row[0])


async def _create_legacy_documents_schema(db) -> None:
    await db.execute("""
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL CHECK (source_type IN ('scribble', 'file', 'feed')),
            title TEXT,
            text TEXT NOT NULL,
            mime_type TEXT,
            source_uri TEXT,
            metadata TEXT,
            triaged INTEGER NOT NULL DEFAULT 0,
            processed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)
    await db.execute("""
        CREATE TABLE engrams (
            id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL UNIQUE,
            concept_hash TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)
    await db.execute("""
        CREATE TABLE edges (
            id TEXT PRIMARY KEY,
            source_engram_id TEXT NOT NULL REFERENCES engrams(id),
            target_engram_id TEXT NOT NULL REFERENCES engrams(id),
            predicate TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            source_document_id TEXT REFERENCES documents(id),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            UNIQUE(source_engram_id, target_engram_id, predicate)
        )
    """)
    await db.execute("""
        CREATE TABLE document_engrams (
            document_id TEXT NOT NULL REFERENCES documents(id),
            engram_id TEXT NOT NULL REFERENCES engrams(id),
            PRIMARY KEY (document_id, engram_id)
        )
    """)
    await db.execute(
        "INSERT INTO documents (id, source_type, title, text, processed, triaged) VALUES (?, ?, ?, ?, ?, ?)",
        ("doc_legacy", "file", "Legacy", "legacy text", 1, 1),
    )
    await db.execute(
        "INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
        ("eng_legacy", "Legacy concept", "legacy-hash"),
    )
    await db.execute(
        "INSERT INTO edges (id, source_engram_id, target_engram_id, predicate, source_document_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("edge_legacy", "eng_legacy", "eng_legacy", "self", "doc_legacy"),
    )
    await db.execute(
        "INSERT INTO document_engrams (document_id, engram_id) VALUES (?, ?)",
        ("doc_legacy", "eng_legacy"),
    )
    await db.commit()


async def _create_half_migrated_documents_schema(db) -> None:
    await db.execute("""
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL CHECK (source_type IN ('scribble', 'file', 'feed', 'url')),
            title TEXT,
            text TEXT NOT NULL,
            mime_type TEXT,
            source_uri TEXT,
            metadata TEXT,
            triaged INTEGER NOT NULL DEFAULT 0,
            processed INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL DEFAULT 1,
            tidy_title TEXT,
            tidy_text TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)
    await db.execute("""
        CREATE TABLE "_documents_old" (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL CHECK (source_type IN ('scribble', 'file', 'feed')),
            title TEXT,
            text TEXT NOT NULL,
            mime_type TEXT,
            source_uri TEXT,
            metadata TEXT,
            triaged INTEGER NOT NULL DEFAULT 0,
            processed INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL DEFAULT 1,
            tidy_title TEXT,
            tidy_text TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)
    await db.execute("""
        CREATE TABLE engrams (
            id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL UNIQUE,
            concept_hash TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)
    await db.execute("""
        CREATE TABLE edges (
            id TEXT PRIMARY KEY,
            source_engram_id TEXT NOT NULL REFERENCES engrams(id),
            target_engram_id TEXT NOT NULL REFERENCES engrams(id),
            predicate TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            source_document_id TEXT REFERENCES "_documents_old"(id),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            UNIQUE(source_engram_id, target_engram_id, predicate)
        )
    """)
    await db.execute("""
        CREATE TABLE document_engrams (
            document_id TEXT NOT NULL REFERENCES "_documents_old"(id),
            engram_id TEXT NOT NULL REFERENCES engrams(id),
            PRIMARY KEY (document_id, engram_id)
        )
    """)
    await db.execute("""
        CREATE VIRTUAL TABLE documents_fts USING fts5(
            title, text,
            content='documents',
            content_rowid='rowid'
        )
    """)
    await db.execute(
        'CREATE INDEX idx_documents_source_type ON "_documents_old"(source_type)'
    )
    await db.execute("""
        CREATE TRIGGER documents_fts_insert
        AFTER INSERT ON "_documents_old" BEGIN
            INSERT INTO documents_fts(rowid, title, text)
            VALUES (new.rowid, new.title, new.text);
        END
    """)
    await db.execute(
        "INSERT INTO _documents_old (id, source_type, title, text, processed, triaged) VALUES (?, ?, ?, ?, ?, ?)",
        ("doc_broken", "scribble", "Broken", "broken text", 1, 1),
    )
    await db.execute(
        "INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
        ("eng_broken", "Broken concept", "broken-hash"),
    )
    await db.execute(
        "INSERT INTO edges (id, source_engram_id, target_engram_id, predicate, source_document_id) "
        "VALUES (?, ?, ?, ?, ?)",
        ("edge_broken", "eng_broken", "eng_broken", "self", "doc_broken"),
    )
    await db.execute(
        "INSERT INTO document_engrams (document_id, engram_id) VALUES (?, ?)",
        ("doc_broken", "eng_broken"),
    )
    await db.commit()


class TestIdempotency:
    async def test_create_tables_twice_no_error(self, tmp_db):
        await create_tables(tmp_db)  # second call

    async def test_all_tables_exist(self, tmp_db):
        for table in [
            "documents",
            "engrams",
            "engram_aliases",
            "edges",
            "document_engrams",
            "feed_sources",
            "projections",
        ]:
            cursor = await tmp_db.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", (table,))
            assert (await cursor.fetchone())[0] == 1, f"Table '{table}' not found"

    async def test_create_tables_backfills_engram_aliases(self, tmp_db):
        await tmp_db.execute(
            "INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
            ("eng_alias", "생명윤리및안전에관한법률", "hash_alias"),
        )
        await tmp_db.commit()
        await tmp_db.execute("DELETE FROM engram_aliases WHERE engram_id = ?", ("eng_alias",))
        await tmp_db.commit()

        await create_tables(tmp_db)

        cursor = await tmp_db.execute(
            "SELECT alias_key FROM engram_aliases WHERE engram_id = ? ORDER BY alias_key",
            ("eng_alias",),
        )
        alias_keys = {row["alias_key"] for row in await cursor.fetchall()}
        assert "생명윤리및안전에관한법률" in alias_keys
        assert "생명윤리법" in alias_keys

    async def test_virtual_tables_exist(self, tmp_db):
        for vt in ["engram_embeddings", "document_embeddings", "documents_fts"]:
            cursor = await tmp_db.execute("SELECT count(*) FROM sqlite_master WHERE name=?", (vt,))
            assert (await cursor.fetchone())[0] >= 1, f"Virtual table '{vt}' not found"

    async def test_reads_vec_table_dimension(self, tmp_db):
        assert await get_vec_table_embedding_dim(tmp_db, "engram_embeddings") == 384
        assert await get_vec_table_embedding_dim(tmp_db, "document_embeddings") == 384

    async def test_rebuilds_vec_tables_when_dimension_changes(self, tmp_db):
        await tmp_db.execute(
            "INSERT INTO documents (id, source_type, text, processed, triaged) VALUES (?, ?, ?, ?, ?)",
            ("doc1", "scribble", "hello", 2, 1),
        )
        await tmp_db.execute(
            "INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
            ("eng1", "concept", "hash1"),
        )
        await tmp_db.execute(
            "INSERT INTO document_engrams (document_id, engram_id) VALUES (?, ?)",
            ("doc1", "eng1"),
        )
        await tmp_db.commit()

        rebuilt = await ensure_vec_tables(tmp_db, 1536)

        assert rebuilt is True
        assert await get_vec_table_embedding_dim(tmp_db, "engram_embeddings") == 1536
        assert await get_vec_table_embedding_dim(tmp_db, "document_embeddings") == 1536

        cursor = await tmp_db.execute("SELECT count(*) FROM engrams")
        assert (await cursor.fetchone())[0] == 0
        cursor = await tmp_db.execute("SELECT processed, triaged FROM documents WHERE id = 'doc1'")
        row = await cursor.fetchone()
        assert row["processed"] == 0
        assert row["triaged"] == 0


class TestDocumentSchemaMigration:
    async def test_migrates_legacy_documents_table_with_child_rows(self, tmp_path: Path):
        db = await get_connection(tmp_path / "legacy.db")
        try:
            await _create_legacy_documents_schema(db)

            await create_tables(db)

            documents_sql = await _fetch_table_sql(db, "documents")
            assert documents_sql is not None
            assert "'url'" in documents_sql
            assert "tidy_level" in await _fetch_table_columns(db, "documents")
            assert await _fetch_table_sql(db, "_documents_old") is None
            assert await _fetch_fk_parents(db, "edges") == {"documents", "engrams"}
            assert await _fetch_fk_parents(db, "document_engrams") == {"documents", "engrams"}
            assert await _count_rows(db, "documents") == 1
            assert await _count_rows(db, "documents_fts") == 1
            assert await _fetch_trigger_table(db, "documents_fts_insert") == "documents"
        finally:
            await db.close()

    async def test_repairs_half_migrated_documents_schema(self, tmp_path: Path):
        db = await get_connection(tmp_path / "half-migrated.db")
        try:
            await _create_half_migrated_documents_schema(db)

            await create_tables(db)

            assert await _fetch_table_sql(db, "_documents_old") is None
            assert "tidy_level" in await _fetch_table_columns(db, "documents")
            assert await _fetch_fk_parents(db, "edges") == {"documents", "engrams"}
            assert await _fetch_fk_parents(db, "document_engrams") == {"documents", "engrams"}
            assert await _fetch_index_table(db, "idx_documents_source_type") == "documents"
            assert await _fetch_trigger_table(db, "documents_fts_insert") == "documents"
            assert await _count_rows(db, "documents") == 1
            assert await _count_rows(db, "documents_fts") == 1
        finally:
            await db.close()


class TestDocumentsCRUD:
    async def test_insert_scribble(self, tmp_db):
        await tmp_db.execute("INSERT INTO documents (id, source_type, text) VALUES (?, ?, ?)",
                             ("doc1", "scribble", "Hello world"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM documents WHERE id = 'doc1'")
        row = await cursor.fetchone()
        assert row["source_type"] == "scribble"
        assert row["text"] == "Hello world"
        assert row["triaged"] == 0
        assert row["processed"] == 0
        assert row["tidy_level"] is None

    async def test_auto_id_generated(self, tmp_db):
        await tmp_db.execute("INSERT INTO documents (source_type, text) VALUES (?, ?)",
                             ("scribble", "Auto ID"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT id FROM documents WHERE text = 'Auto ID'")
        row = await cursor.fetchone()
        assert row["id"]
        assert len(row["id"]) == 32

    async def test_auto_timestamps(self, tmp_db):
        await tmp_db.execute("INSERT INTO documents (id, source_type, text) VALUES (?, ?, ?)",
                             ("doc_ts", "scribble", "ts test"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT created_at, updated_at FROM documents WHERE id = 'doc_ts'")
        row = await cursor.fetchone()
        assert row["created_at"] is not None
        assert "T" in row["created_at"]

    async def test_source_type_check_constraint(self, tmp_db):
        with pytest.raises(Exception):
            await tmp_db.execute("INSERT INTO documents (id, source_type, text) VALUES (?, ?, ?)",
                                 ("bad", "email", "invalid"))

    async def test_text_not_null(self, tmp_db):
        with pytest.raises(Exception):
            await tmp_db.execute("INSERT INTO documents (id, source_type) VALUES (?, ?)",
                                 ("bad2", "scribble"))

    async def test_metadata_json_roundtrip(self, tmp_db):
        meta = json.dumps({"author": "Latour", "pages": 42})
        await tmp_db.execute("INSERT INTO documents (id, source_type, text, metadata) VALUES (?, ?, ?, ?)",
                             ("doc_meta", "file", "text", meta))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT metadata FROM documents WHERE id = 'doc_meta'")
        parsed = json.loads((await cursor.fetchone())["metadata"])
        assert parsed["author"] == "Latour"

    async def test_from_row_model(self, tmp_db):
        await tmp_db.execute("INSERT INTO documents (id, source_type, title, text) VALUES (?, ?, ?, ?)",
                             ("doc_m", "scribble", "Title", "body"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM documents WHERE id = 'doc_m'")
        doc = Document.from_row(await cursor.fetchone())
        assert doc.id == "doc_m"
        assert doc.title == "Title"
        assert isinstance(doc.created_at, datetime)


class TestEngramsCRUD:
    async def test_insert_engram(self, tmp_db):
        await tmp_db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                             ("eng1", "artificial intelligence", "hash_ai"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM engrams WHERE id = 'eng1'")
        assert (await cursor.fetchone())["canonical_name"] == "artificial intelligence"

    async def test_canonical_name_unique(self, tmp_db):
        await tmp_db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                             ("e1", "machine learning", "h1"))
        await tmp_db.commit()
        with pytest.raises(Exception):
            await tmp_db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                                 ("e2", "machine learning", "h2"))

    async def test_concept_hash_unique(self, tmp_db):
        await tmp_db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                             ("e1", "deep learning", "hash_dl"))
        await tmp_db.commit()
        with pytest.raises(Exception):
            await tmp_db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                                 ("e2", "neural networks", "hash_dl"))

    async def test_from_row_model(self, tmp_db):
        await tmp_db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                             ("em", "test", "ht"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM engrams WHERE id = 'em'")
        engram = Engram.from_row(await cursor.fetchone())
        assert engram.canonical_name == "test"


class TestEdgesCRUD:
    _EDGE_INSERT = (
        "INSERT INTO edges (id, source_engram_id, target_engram_id, predicate)"
        " VALUES (?, ?, ?, ?)"
    )

    async def _insert_engrams(self, db):
        await db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                         ("e_src", "source", "h_src"))
        await db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                         ("e_tgt", "target", "h_tgt"))
        await db.commit()

    async def test_insert_edge(self, tmp_db):
        await self._insert_engrams(tmp_db)
        await tmp_db.execute(
            self._EDGE_INSERT, ("edge1", "e_src", "e_tgt", "supports")
        )
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM edges WHERE id = 'edge1'")
        row = await cursor.fetchone()
        assert row["predicate"] == "supports"
        assert row["confidence"] == 1.0

    async def test_unique_constraint(self, tmp_db):
        await self._insert_engrams(tmp_db)
        await tmp_db.execute(
            self._EDGE_INSERT, ("eu1", "e_src", "e_tgt", "contradicts")
        )
        await tmp_db.commit()
        with pytest.raises(Exception):
            await tmp_db.execute(
                self._EDGE_INSERT, ("eu2", "e_src", "e_tgt", "contradicts")
            )

    async def test_different_predicates_allowed(self, tmp_db):
        await self._insert_engrams(tmp_db)
        await tmp_db.execute(
            self._EDGE_INSERT, ("ed1", "e_src", "e_tgt", "supports")
        )
        await tmp_db.execute(
            self._EDGE_INSERT, ("ed2", "e_src", "e_tgt", "contradicts")
        )
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT count(*) FROM edges")
        assert (await cursor.fetchone())[0] == 2

    async def test_fk_enforcement_source(self, tmp_db):
        await self._insert_engrams(tmp_db)
        with pytest.raises(Exception):
            await tmp_db.execute(
                self._EDGE_INSERT, ("efk", "nonexistent", "e_tgt", "supports")
            )
            await tmp_db.commit()

    async def test_fk_enforcement_target(self, tmp_db):
        await self._insert_engrams(tmp_db)
        with pytest.raises(Exception):
            await tmp_db.execute(
                self._EDGE_INSERT, ("efk2", "e_src", "nonexistent", "supports")
            )
            await tmp_db.commit()

    async def test_from_row_model(self, tmp_db):
        await self._insert_engrams(tmp_db)
        await tmp_db.execute(
            "INSERT INTO edges (id, source_engram_id, target_engram_id,"
            " predicate, confidence) VALUES (?, ?, ?, ?, ?)",
            ("em", "e_src", "e_tgt", "critiques", 0.85),
        )
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM edges WHERE id = 'em'")
        edge = Edge.from_row(await cursor.fetchone())
        assert edge.predicate == "critiques"
        assert edge.confidence == pytest.approx(0.85)


class TestDocumentEngrams:
    async def test_junction_insert_and_query(self, tmp_db):
        await tmp_db.execute("INSERT INTO documents (id, source_type, text) VALUES (?, ?, ?)",
                             ("dj", "scribble", "junction"))
        await tmp_db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                             ("ej", "concept", "hj"))
        await tmp_db.execute("INSERT INTO document_engrams (document_id, engram_id) VALUES (?, ?)",
                             ("dj", "ej"))
        await tmp_db.commit()
        cursor = await tmp_db.execute(
            "SELECT e.canonical_name FROM engrams e"
            " JOIN document_engrams de ON e.id = de.engram_id"
            " WHERE de.document_id = 'dj'"
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["canonical_name"] == "concept"

    async def test_pk_prevents_duplicates(self, tmp_db):
        await tmp_db.execute("INSERT INTO documents (id, source_type, text) VALUES (?, ?, ?)",
                             ("dd", "scribble", "dup"))
        await tmp_db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                             ("ed", "dup", "hd"))
        await tmp_db.execute("INSERT INTO document_engrams (document_id, engram_id) VALUES (?, ?)",
                             ("dd", "ed"))
        await tmp_db.commit()
        with pytest.raises(Exception):
            await tmp_db.execute("INSERT INTO document_engrams (document_id, engram_id) VALUES (?, ?)",
                                 ("dd", "ed"))

    async def test_fk_enforcement(self, tmp_db):
        with pytest.raises(Exception):
            await tmp_db.execute("INSERT INTO document_engrams (document_id, engram_id) VALUES (?, ?)",
                                 ("no_doc", "no_eng"))
            await tmp_db.commit()


class TestSqliteVec:
    async def test_insert_and_retrieve_engram_embedding(self, tmp_db):
        emb = _float_list_to_bytes([0.1] * 384)
        await tmp_db.execute("INSERT INTO engram_embeddings (engram_id, embedding) VALUES (?, ?)",
                             ("ve1", emb))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT engram_id FROM engram_embeddings WHERE engram_id = 've1'")
        assert (await cursor.fetchone())[0] == "ve1"

    async def test_insert_and_retrieve_document_embedding(self, tmp_db):
        emb = _float_list_to_bytes([0.2] * 384)
        await tmp_db.execute("INSERT INTO document_embeddings (document_id, embedding) VALUES (?, ?)",
                             ("vd1", emb))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT document_id FROM document_embeddings WHERE document_id = 'vd1'")
        assert (await cursor.fetchone())[0] == "vd1"

    async def test_knn_query(self, tmp_db):
        eng_a = [1.0] + [0.0] * 383
        eng_b = [0.0] + [1.0] + [0.0] * 382
        eng_c = [0.7] + [0.7] + [0.0] * 382
        for eid, emb in [("a", eng_a), ("b", eng_b), ("c", eng_c)]:
            await tmp_db.execute("INSERT INTO engram_embeddings (engram_id, embedding) VALUES (?, ?)",
                                 (eid, _float_list_to_bytes(emb)))
        await tmp_db.commit()
        query = _float_list_to_bytes([1.0] + [0.0] * 383)
        cursor = await tmp_db.execute(
            "SELECT engram_id, distance FROM engram_embeddings WHERE embedding MATCH ? AND k = 2 ORDER BY distance",
            (query,))
        rows = await cursor.fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "a"   # closest
        assert rows[1][0] == "c"   # second closest
        assert rows[0][1] < rows[1][1]

    async def test_wrong_dimension_rejected(self, tmp_db):
        bad = _float_list_to_bytes([0.1] * 128)  # 128 != 384
        with pytest.raises(Exception):
            await tmp_db.execute("INSERT INTO engram_embeddings (engram_id, embedding) VALUES (?, ?)",
                                 ("bad", bad))


class TestFTS5:
    async def test_insert_trigger_populates_fts(self, tmp_db):
        await tmp_db.execute("INSERT INTO documents (id, source_type, title, text) VALUES (?, ?, ?, ?)",
                             ("f1", "scribble", "AI Ethics", "artificial intelligence morality"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM documents_fts WHERE documents_fts MATCH 'artificial'")
        assert len(await cursor.fetchall()) == 1

    async def test_fts_search_by_title(self, tmp_db):
        await tmp_db.execute("INSERT INTO documents (id, source_type, title, text) VALUES (?, ?, ?, ?)",
                             ("f2", "file", "Latour Translation", "actor network theory"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM documents_fts WHERE documents_fts MATCH 'Latour'")
        assert len(await cursor.fetchall()) == 1

    async def test_update_trigger_syncs_fts(self, tmp_db):
        await tmp_db.execute("INSERT INTO documents (id, source_type, text) VALUES (?, ?, ?)",
                             ("fu", "scribble", "original content"))
        await tmp_db.commit()
        await tmp_db.execute("UPDATE documents SET text = ? WHERE id = ?",
                             ("new epistemology content", "fu"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM documents_fts WHERE documents_fts MATCH 'epistemology'")
        assert len(await cursor.fetchall()) == 1

    async def test_delete_trigger_removes_from_fts(self, tmp_db):
        await tmp_db.execute("INSERT INTO documents (id, source_type, text) VALUES (?, ?, ?)",
                             ("fd", "scribble", "unique xylophone word"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM documents_fts WHERE documents_fts MATCH 'xylophone'")
        assert len(await cursor.fetchall()) == 1
        await tmp_db.execute("DELETE FROM documents WHERE id = 'fd'")
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM documents_fts WHERE documents_fts MATCH 'xylophone'")
        assert len(await cursor.fetchall()) == 0

    async def test_fts_multiple_results(self, tmp_db):
        await tmp_db.execute("INSERT INTO documents (id, source_type, text) VALUES (?, ?, ?)",
                             ("fm1", "scribble", "machine learning transforms research"))
        await tmp_db.execute("INSERT INTO documents (id, source_type, text) VALUES (?, ?, ?)",
                             ("fm2", "scribble", "deep learning neural networks"))
        await tmp_db.execute("INSERT INTO documents (id, source_type, text) VALUES (?, ?, ?)",
                             ("fm3", "scribble", "classical statistics and regression"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM documents_fts WHERE documents_fts MATCH 'learning'")
        assert len(await cursor.fetchall()) == 2


class TestFeedSources:
    async def test_insert_feed_source(self, tmp_db):
        await tmp_db.execute("INSERT INTO feed_sources (id, name, feed_type, url) VALUES (?, ?, ?, ?)",
                             ("fs1", "ArXiv CS", "rss", "https://arxiv.org/rss/cs.AI"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM feed_sources WHERE id = 'fs1'")
        row = await cursor.fetchone()
        assert row["name"] == "ArXiv CS"
        assert row["active"] == 1
        assert row["schedule"] == "0 */6 * * *"
        assert row["last_fetched"] is None

    async def test_feed_type_check_constraint(self, tmp_db):
        with pytest.raises(Exception):
            await tmp_db.execute("INSERT INTO feed_sources (id, name, feed_type, url) VALUES (?, ?, ?, ?)",
                                 ("bad", "Bad", "email", "https://example.com"))

    async def test_from_row_model(self, tmp_db):
        await tmp_db.execute("INSERT INTO feed_sources (id, name, feed_type, url) VALUES (?, ?, ?, ?)",
                             ("fsm", "Test", "scrape", "https://example.com"))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM feed_sources WHERE id = 'fsm'")
        feed = FeedSource.from_row(await cursor.fetchone())
        assert feed.active is True
        assert feed.last_fetched is None


class TestProjections:
    async def test_insert_projection(self, tmp_db):
        await tmp_db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                             ("ep", "projected", "hp"))
        await tmp_db.execute("INSERT INTO projections (engram_id, x, y, z, cluster_id) VALUES (?, ?, ?, ?, ?)",
                             ("ep", 1.5, -2.3, 0.7, 0))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM projections WHERE engram_id = 'ep'")
        row = await cursor.fetchone()
        assert row["x"] == pytest.approx(1.5)
        assert row["y"] == pytest.approx(-2.3)

    async def test_fk_enforcement(self, tmp_db):
        with pytest.raises(Exception):
            await tmp_db.execute("INSERT INTO projections (engram_id, x, y, z) VALUES (?, ?, ?, ?)",
                                 ("nonexistent", 0.0, 0.0, 0.0))
            await tmp_db.commit()

    async def test_from_row_model(self, tmp_db):
        await tmp_db.execute("INSERT INTO engrams (id, canonical_name, concept_hash) VALUES (?, ?, ?)",
                             ("epm", "proj model", "hpm"))
        await tmp_db.execute("INSERT INTO projections (engram_id, x, y, z) VALUES (?, ?, ?, ?)",
                             ("epm", 3.14, 2.72, 1.41))
        await tmp_db.commit()
        cursor = await tmp_db.execute("SELECT * FROM projections WHERE engram_id = 'epm'")
        proj = Projection.from_row(await cursor.fetchone())
        assert proj.x == pytest.approx(3.14)
        assert proj.cluster_id is None
