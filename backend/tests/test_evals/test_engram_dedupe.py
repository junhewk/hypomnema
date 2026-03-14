"""Tests for the engram dedupe evaluation harness."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import TYPE_CHECKING

import numpy as np
import pytest

from hypomnema.config import Settings
from hypomnema.evals.engram_dedupe import (
    audit_existing_engrams,
    build_markdown_summary,
    load_eval_cases,
    run_engram_dedupe_eval,
    write_eval_report,
)

if TYPE_CHECKING:
    from pathlib import Path


class StaticEmbeddingModel:
    def __init__(self, mapping: dict[str, np.ndarray[object, np.dtype[np.float32]]], dimension: int = 4) -> None:
        self._mapping = mapping
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> np.ndarray[object, np.dtype[np.float32]]:
        return np.stack([self._mapping[text] for text in texts]).astype(np.float32)


def _unit_vector(*values: float) -> np.ndarray[object, np.dtype[np.float32]]:
    vec = np.array(values, dtype=np.float32)
    return vec / np.linalg.norm(vec)


def _eval_embeddings(dataset: str) -> StaticEmbeddingModel:
    merge_left = _unit_vector(1, 0, 0, 0)
    merge_right = _unit_vector(0, -1, 0, 0)
    separate_left = _unit_vector(0, 0, 1, 0)
    separate_right = _unit_vector(0, 0, 0, -1)
    bioethics_short = _unit_vector(1, -1, 1, -1)
    bioethics_full = _unit_vector(-1, 1, 1, -1)
    bioethics_bridge = _unit_vector(-1, -1, 1, 1)
    bioethics_distractor = _unit_vector(1, 1, -1, -1)
    safety_base = _unit_vector(1, -1, 1, -1)
    safety_english = _unit_vector(-1, 1, 1, -1)
    safety_bridge = _unit_vector(-1, -1, -1, 1)
    safety_distractor = _unit_vector(1, 1, -1, -1)
    special_vectors = {
        "생명윤리법": bioethics_short,
        "생명윤리및안전에관한법률": bioethics_full,
        "생명윤리및안전에관한법률 (bioethics and safety law)": bioethics_bridge,
        "bioethics and safety law": bioethics_full,
        "bioethics and safety guideline": separate_right,
        "안전성": safety_base,
        "안전성 (safety)": safety_bridge,
        "safety": safety_english,
        "의료법": separate_right,
    }

    mapping: dict[str, np.ndarray[object, np.dtype[np.float32]]] = {}
    for case in load_eval_cases(dataset):
        mapping.setdefault(
            case.left_name,
            special_vectors.get(case.left_name, merge_left if case.expected == "merge" else separate_left),
        )
        mapping.setdefault(
            case.right_name,
            special_vectors.get(case.right_name, merge_right if case.expected == "merge" else separate_right),
        )
        for seed_name in case.seed_names:
            if seed_name == "생명윤리및안전에관한법률 (bioethics and safety law)":
                mapping.setdefault(seed_name, bioethics_bridge)
            elif seed_name.startswith("bioethics_bridge_distractor_"):
                mapping.setdefault(seed_name, bioethics_distractor)
            elif seed_name == "안전성 (safety)":
                mapping.setdefault(seed_name, safety_bridge)
            elif seed_name.startswith("safety_bridge_distractor_"):
                mapping.setdefault(seed_name, safety_distractor)
            else:
                mapping.setdefault(seed_name, separate_left)
    return StaticEmbeddingModel(mapping)


def _seed_audit_db(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("""
            CREATE TABLE engrams (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL UNIQUE,
                concept_hash TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
        """)
        for name in (
            "최지연 (prof. choi ji-yeon)",
            "최지연 교수님 (professor choi ji-yeon)",
            "기술 수용성",
            "기술수용성",
        ):
            concept_hash = hashlib.sha256(name.encode("utf-8")).hexdigest()
            connection.execute(
                "INSERT INTO engrams (id, canonical_name, concept_hash, description) VALUES (?, ?, ?, ?)",
                (concept_hash[:16], name, concept_hash, f"Seed {name}"),
            )
        connection.commit()
    finally:
        connection.close()


class TestLoadEvalCases:
    def test_loads_smoke_and_full_sets(self) -> None:
        smoke = load_eval_cases("smoke")
        full = load_eval_cases("full")
        assert len(smoke) == 13
        assert len(full) == 22
        assert smoke[0].expected == "merge"
        assert full[-1].expected == "separate"
        safety_bridge = next(case for case in smoke if case.id == "safety_english_bridge")
        assert safety_bridge.seed_names[0] == "안전성 (safety)"


class TestAuditExistingEngrams:
    @pytest.mark.asyncio
    async def test_groups_current_engrams_by_alias_key(self, tmp_path: Path) -> None:
        db_path = tmp_path / "audit.db"
        _seed_audit_db(db_path)

        families = await audit_existing_engrams(db_path)

        assert any(family.base_key == "최지연" for family in families)
        assert any(family.base_key == "기술수용성" for family in families)


class TestRunEngramDedupeEval:
    @pytest.mark.asyncio
    async def test_smoke_eval_compares_baseline_adjusted_and_hardened(self, tmp_path: Path) -> None:
        embeddings = _eval_embeddings("smoke")
        db_path = tmp_path / "audit.db"
        _seed_audit_db(db_path)
        settings = Settings(
            db_path=db_path,
            embedding_provider="local",
            embedding_model="unit-test",
            embedding_dim=embeddings.dimension,
        )

        report = await run_engram_dedupe_eval(
            dataset="smoke",
            base_settings=settings,
            embeddings=embeddings,
            audit_db_path=db_path,
        )

        assert report.baseline.case_count == 13
        assert report.baseline.passed_count == 4
        assert report.baseline.missed_merge_count == 9
        assert report.adjusted.passed_count == 10
        assert report.adjusted.missed_merge_count == 3
        assert report.adjusted.false_merge_count == 0
        assert report.hardened.passed_count == 13
        assert report.hardened.missed_merge_count == 0
        assert report.hardened.false_merge_count == 0
        assert any(
            case.case_id == "choi_honorific_gloss" and case.adjusted.reason == "alias_key"
            for case in report.cases
        )
        assert any(
            case.case_id == "bioethics_law_short_full"
            and not case.adjusted.passed
            and case.hardened.reason == "alias_index"
            for case in report.cases
        )
        assert any(
            case.case_id == "safety_english_bridge"
            and not case.adjusted.passed
            and case.hardened.reason == "alias_index"
            for case in report.cases
        )
        assert any(family.base_key == "최지연" for family in report.audit_families)

    @pytest.mark.asyncio
    async def test_full_eval_exercises_seeded_bridge_cases(self, tmp_path: Path) -> None:
        embeddings = _eval_embeddings("full")
        db_path = tmp_path / "audit.db"
        _seed_audit_db(db_path)
        settings = Settings(
            db_path=db_path,
            embedding_provider="local",
            embedding_model="unit-test",
            embedding_dim=embeddings.dimension,
        )

        report = await run_engram_dedupe_eval(
            dataset="full",
            base_settings=settings,
            embeddings=embeddings,
            audit_db_path=db_path,
        )

        assert report.adjusted.passed_count == 18
        assert report.hardened.passed_count == 22
        assert any(
            case.case_id == "bioethics_law_short_english_bridge"
            and not case.adjusted.passed
            and case.hardened.passed
            and case.hardened.reason == "alias_index"
            for case in report.cases
        )
        assert any(
            case.case_id == "bioethics_law_vs_guideline"
            and not case.hardened.merged
            for case in report.cases
        )

    @pytest.mark.asyncio
    async def test_writes_json_and_markdown_reports(self, tmp_path: Path) -> None:
        embeddings = _eval_embeddings("smoke")
        db_path = tmp_path / "audit.db"
        _seed_audit_db(db_path)
        settings = Settings(
            db_path=db_path,
            embedding_provider="local",
            embedding_model="unit-test",
            embedding_dim=embeddings.dimension,
        )
        report = await run_engram_dedupe_eval(
            dataset="smoke",
            base_settings=settings,
            embeddings=embeddings,
            audit_db_path=db_path,
        )

        json_path, md_path = write_eval_report(report, tmp_path)

        assert json_path.exists()
        assert md_path.exists()
        summary = build_markdown_summary(report)
        assert "Engram Dedupe Eval" in summary
        assert "choi_honorific_gloss" in summary
        assert "Hardened" in summary
