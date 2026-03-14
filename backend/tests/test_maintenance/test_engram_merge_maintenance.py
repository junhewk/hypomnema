"""Tests for live-DB engram dedupe maintenance."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import numpy as np

from hypomnema.maintenance.engram_dedupe import apply_engram_dedupe_to_db, plan_engram_dedupe

if TYPE_CHECKING:
    from pathlib import Path


def _unit_vector(*values: float) -> bytes:
    vec = np.zeros(8, dtype=np.float32)
    vec[: len(values)] = np.array(values, dtype=np.float32)
    vec = vec / np.linalg.norm(vec)
    return vec.astype("<f4").tobytes()


def _seed_test_db(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("""
            CREATE TABLE engrams (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL UNIQUE,
                concept_hash TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE document_engrams (
                document_id TEXT NOT NULL,
                engram_id TEXT NOT NULL,
                PRIMARY KEY (document_id, engram_id)
            )
        """)
        connection.execute("""
            CREATE TABLE edges (
                id TEXT PRIMARY KEY,
                source_engram_id TEXT NOT NULL,
                target_engram_id TEXT NOT NULL,
                predicate TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                source_document_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(source_engram_id, target_engram_id, predicate)
            )
        """)
        connection.execute("""
            CREATE TABLE projections (
                engram_id TEXT PRIMARY KEY,
                x REAL NOT NULL,
                y REAL NOT NULL,
                z REAL NOT NULL,
                cluster_id INTEGER,
                updated_at TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE engram_embeddings (
                engram_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL
            )
        """)

        engrams = (
            ("eng_safety_en", "safety", "h1", None, "2026-03-13T07:55:35.263Z"),
            ("eng_safety_gloss", "안전성 (safety)", "h2", None, "2026-03-13T07:55:54.343Z"),
            ("eng_safety_ko", "안전성", "h3", "Canonical safety term", "2026-03-13T09:05:55.845Z"),
            ("eng_target_x", "임상 결과", "hx", None, "2026-03-13T09:05:55.846Z"),
            ("eng_target_y", "환자 안전", "hy", None, "2026-03-13T09:05:55.847Z"),
        )
        connection.executemany(
            "INSERT INTO engrams (id, canonical_name, concept_hash, description, created_at) VALUES (?, ?, ?, ?, ?)",
            engrams,
        )
        connection.executemany(
            "INSERT INTO engram_embeddings (engram_id, embedding) VALUES (?, ?)",
            (
                ("eng_safety_en", _unit_vector(1, 0, 0.9, 0.7)),
                ("eng_safety_gloss", _unit_vector(1, 0, 0.5, 1.0)),
                ("eng_safety_ko", _unit_vector(1, 0, 0, 1)),
                ("eng_target_x", _unit_vector(0, 1, 0, 1)),
                ("eng_target_y", _unit_vector(0, 1, 1, 0)),
            ),
        )
        connection.execute(
            "INSERT INTO document_engrams (document_id, engram_id) VALUES (?, ?)",
            ("doc-1", "eng_safety_ko"),
        )
        connection.executemany(
            "INSERT INTO edges "
            "(id, source_engram_id, target_engram_id, predicate, confidence, source_document_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ("edge-1", "eng_safety_en", "eng_target_x", "supports", 0.7, None, "2026-03-13T10:00:00.000Z"),
                ("edge-2", "eng_safety_gloss", "eng_target_x", "supports", 0.9, "doc-1", "2026-03-13T10:00:01.000Z"),
                ("edge-3", "eng_safety_ko", "eng_target_y", "supports", 0.8, "doc-1", "2026-03-13T10:00:02.000Z"),
                ("edge-4", "eng_safety_en", "eng_safety_gloss", "related_to", 0.5, None, "2026-03-13T10:00:03.000Z"),
            ),
        )
        connection.execute(
            "INSERT INTO projections (engram_id, x, y, z, cluster_id, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("eng_safety_ko", 1.0, 2.0, 3.0, 7, "2026-03-13T10:00:04.000Z"),
        )
        connection.commit()
    finally:
        connection.close()


class TestPlanEngramDedupe:
    def test_prefers_clean_korean_survivor(self, tmp_path: Path) -> None:
        db_path = tmp_path / "maintenance.db"
        _seed_test_db(db_path)

        report = plan_engram_dedupe(db_path)

        assert report.family_count == 1
        assert report.merged_engram_count == 2
        assert report.engram_count_before == 5
        assert report.engram_count_after == 3
        assert report.families[0].survivor.canonical_name == "안전성"
        assert {member.canonical_name for member in report.families[0].merged_members} == {
            "safety",
            "안전성 (safety)",
        }


class TestApplyEngramDedupe:
    def test_merges_rows_and_remaps_links(self, tmp_path: Path) -> None:
        db_path = tmp_path / "maintenance.db"
        _seed_test_db(db_path)

        report = apply_engram_dedupe_to_db(db_path, create_backup=False)

        assert report.family_count == 1
        assert report.engram_count_before == 5
        assert report.engram_count_after == 3

        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        try:
            engrams = connection.execute(
                "SELECT id, canonical_name FROM engrams ORDER BY canonical_name"
            ).fetchall()
            assert [row["canonical_name"] for row in engrams] == ["안전성", "임상 결과", "환자 안전"]

            doc_links = connection.execute(
                "SELECT document_id, engram_id FROM document_engrams ORDER BY document_id, engram_id"
            ).fetchall()
            assert len(doc_links) == 1
            assert doc_links[0]["document_id"] == "doc-1"
            assert doc_links[0]["engram_id"] == report.families[0].survivor.id

            edges = connection.execute(
                "SELECT source_engram_id, target_engram_id, predicate, confidence, source_document_id "
                "FROM edges ORDER BY target_engram_id"
            ).fetchall()
            assert len(edges) == 2
            assert edges[0]["source_engram_id"] == report.families[0].survivor.id
            assert edges[0]["target_engram_id"] == "eng_target_x"
            assert edges[0]["predicate"] == "supports"
            assert float(edges[0]["confidence"]) == 0.9
            assert edges[0]["source_document_id"] == "doc-1"
            assert edges[1]["source_engram_id"] == report.families[0].survivor.id
            assert edges[1]["target_engram_id"] == "eng_target_y"

            aliases = connection.execute(
                "SELECT alias_key FROM engram_aliases WHERE engram_id = ? ORDER BY alias_key",
                (report.families[0].survivor.id,),
            ).fetchall()
            alias_keys = {row["alias_key"] for row in aliases}
            assert "안전성" in alias_keys
            assert "safety" in alias_keys

            projection = connection.execute(
                "SELECT cluster_id FROM projections WHERE engram_id = ?",
                (report.families[0].survivor.id,),
            ).fetchone()
            assert projection is not None
            assert projection["cluster_id"] == 7

            old_rows = connection.execute(
                "SELECT COUNT(*) AS count FROM engrams WHERE id IN (?, ?)",
                ("eng_safety_en", "eng_safety_gloss"),
            ).fetchone()
            assert old_rows["count"] == 0
        finally:
            connection.close()
