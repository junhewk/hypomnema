"""Maintenance utility for collapsing duplicate engrams in an existing DB."""

from __future__ import annotations

import dataclasses
import shutil
import sqlite3
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np
import sqlite_vec

from hypomnema.ontology.engram import (
    _HANGUL_RE,
    _HONORIFIC_SUFFIXES,
    bytes_to_embedding,
    compute_index_alias_entries,
    cosine_similarity,
)
from hypomnema.ontology.normalizer import normalize

if TYPE_CHECKING:
    from pathlib import Path
_MIN_ALIAS_COMPONENT_COSINE = 0.65


@dataclasses.dataclass(frozen=True)
class EngramMergeMember:
    id: str
    canonical_name: str
    description: str | None
    created_at: str
    doc_count: int
    edge_count: int


@dataclasses.dataclass(frozen=True)
class EngramMergeFamily:
    survivor: EngramMergeMember
    merged_members: tuple[EngramMergeMember, ...]
    alias_keys: tuple[str, ...]
    mincosine_similarity: float | None


@dataclasses.dataclass(frozen=True)
class EngramDedupeMaintenanceReport:
    db_path: Path
    backup_path: Path | None
    started_at: str
    family_count: int
    merged_engram_count: int
    engram_count_before: int
    engram_count_after: int
    families: tuple[EngramMergeFamily, ...]


def plan_engram_dedupe(db_path: Path) -> EngramDedupeMaintenanceReport:
    """Return the merge plan for an existing DB without mutating it."""
    connection = _connect(db_path)
    try:
        _ensure_alias_schema(connection)
        _backfill_aliases(connection)
        families = tuple(_scan_merge_families(connection))
        engram_count = _count_rows(connection, "engrams")
    finally:
        connection.close()
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return EngramDedupeMaintenanceReport(
        db_path=db_path,
        backup_path=None,
        started_at=started_at,
        family_count=len(families),
        merged_engram_count=sum(len(family.merged_members) for family in families),
        engram_count_before=engram_count,
        engram_count_after=engram_count - sum(len(family.merged_members) for family in families),
        families=families,
    )


def apply_engram_dedupe_to_db(
    db_path: Path,
    *,
    create_backup: bool = True,
) -> EngramDedupeMaintenanceReport:
    """Apply deterministic engram merges to an existing DB."""
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    backup_path = _backup_db(db_path, started_at) if create_backup else None
    connection = _connect(db_path)
    try:
        _ensure_alias_schema(connection)
        _backfill_aliases(connection)
        families = tuple(_scan_merge_families(connection))
        engram_count_before = _count_rows(connection, "engrams")
        connection.execute("BEGIN IMMEDIATE")
        for family in families:
            _apply_family_merge(connection, family)
        connection.commit()
        engram_count_after = _count_rows(connection, "engrams")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return EngramDedupeMaintenanceReport(
        db_path=db_path,
        backup_path=backup_path,
        started_at=started_at,
        family_count=len(families),
        merged_engram_count=sum(len(family.merged_members) for family in families),
        engram_count_before=engram_count_before,
        engram_count_after=engram_count_after,
        families=families,
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.enable_load_extension(True)
    connection.load_extension(sqlite_vec.loadable_path())
    connection.enable_load_extension(False)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _ensure_alias_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS engram_aliases (
            engram_id TEXT NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
            alias_key TEXT NOT NULL,
            alias_kind TEXT NOT NULL,
            PRIMARY KEY (engram_id, alias_key)
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_engram_aliases_key ON engram_aliases(alias_key)"
    )
    connection.commit()


def _backfill_aliases(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT id, canonical_name FROM engrams ORDER BY created_at, canonical_name"
    ).fetchall()
    for row in rows:
        _store_aliases(connection, str(row["id"]), str(row["canonical_name"]))
    connection.commit()


def _store_aliases(
    connection: sqlite3.Connection,
    engram_id: str,
    canonical_name: str,
) -> None:
    for entry in compute_index_alias_entries(canonical_name):
        connection.execute(
            "INSERT OR IGNORE INTO engram_aliases (engram_id, alias_key, alias_kind) VALUES (?, ?, ?)",
            (engram_id, entry.alias_key, entry.alias_kind),
        )


def _scan_merge_families(connection: sqlite3.Connection) -> list[EngramMergeFamily]:
    members = _load_members(connection)
    embeddings = _load_embeddings(connection)

    alias_to_ids: dict[str, set[str]] = defaultdict(set)
    member_ids = {member.id for member in members}
    for member in members:
        for entry in compute_index_alias_entries(member.canonical_name):
            alias_to_ids[entry.alias_key].add(member.id)

    graph: dict[str, set[str]] = defaultdict(set)
    for ids in alias_to_ids.values():
        if len(ids) < 2:
            continue
        id_list = sorted(ids)
        for index, left_id in enumerate(id_list):
            for right_id in id_list[index + 1 :]:
                graph[left_id].add(right_id)
                graph[right_id].add(left_id)

    member_map = {member.id: member for member in members}
    families: list[EngramMergeFamily] = []
    visited: set[str] = set()
    for member_id in sorted(graph):
        if member_id in visited:
            continue
        component_ids: list[str] = []
        queue: deque[str] = deque([member_id])
        visited.add(member_id)
        while queue:
            current_id = queue.popleft()
            component_ids.append(current_id)
            for neighbor_id in sorted(graph[current_id]):
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                queue.append(neighbor_id)

        component_members = [member_map[item] for item in component_ids if item in member_ids]
        if len(component_members) < 2:
            continue

        survivor = min(component_members, key=_survivor_rank)
        component_id_set = {member.id for member in component_members}
        mincosine_similarity = _min_component_alias_edge_similarity(
            component_id_set,
            graph,
            embeddings,
        )
        if mincosine_similarity is not None and mincosine_similarity < _MIN_ALIAS_COMPONENT_COSINE:
            continue

        alias_keys = sorted(
            alias_key
            for alias_key, ids in alias_to_ids.items()
            if len(ids & component_id_set) > 1
        )
        merged_members = tuple(
            member
            for member in sorted(component_members, key=_survivor_rank)
            if member.id != survivor.id
        )
        families.append(
            EngramMergeFamily(
                survivor=survivor,
                merged_members=merged_members,
                alias_keys=tuple(alias_keys),
                mincosine_similarity=mincosine_similarity,
            )
        )

    families.sort(key=lambda family: (family.survivor.created_at, family.survivor.canonical_name))
    return families


def _load_members(connection: sqlite3.Connection) -> list[EngramMergeMember]:
    rows = connection.execute("""
        SELECT
            e.id,
            e.canonical_name,
            e.description,
            e.created_at,
            COALESCE(d.doc_count, 0) AS doc_count,
            COALESCE(ed.edge_count, 0) AS edge_count
        FROM engrams e
        LEFT JOIN (
            SELECT engram_id, COUNT(*) AS doc_count
            FROM document_engrams
            GROUP BY engram_id
        ) d ON d.engram_id = e.id
        LEFT JOIN (
            SELECT engram_id, COUNT(*) AS edge_count
            FROM (
                SELECT source_engram_id AS engram_id FROM edges
                UNION ALL
                SELECT target_engram_id AS engram_id FROM edges
            )
            GROUP BY engram_id
        ) ed ON ed.engram_id = e.id
        ORDER BY e.created_at, e.canonical_name
    """).fetchall()
    return [
        EngramMergeMember(
            id=str(row["id"]),
            canonical_name=str(row["canonical_name"]),
            description=str(row["description"]) if row["description"] is not None else None,
            created_at=str(row["created_at"]),
            doc_count=int(row["doc_count"]),
            edge_count=int(row["edge_count"]),
        )
        for row in rows
    ]


def _load_embeddings(connection: sqlite3.Connection) -> dict[str, np.ndarray[Any, np.dtype[np.float32]]]:
    if not _table_exists(connection, "engram_embeddings"):
        return {}
    rows = connection.execute(
        "SELECT engram_id, embedding FROM engram_embeddings"
    ).fetchall()
    return {
        str(row["engram_id"]): bytes_to_embedding(row["embedding"])
        for row in rows
        if row["embedding"] is not None
    }


def _survivor_rank(member: EngramMergeMember) -> tuple[int, ... | str]:
    normalized = normalize(member.canonical_name)
    english_only = int(not _contains_hangul(normalized))
    has_honorific = int(_has_honorific(member.canonical_name))
    has_parenthetical = int("(" in normalized and normalized.endswith(")"))
    compact_hangul = int(_contains_hangul(normalized) and " " not in normalized and "(" not in normalized)
    legal_shortform = int(normalized.endswith("법") and not normalized.endswith("법률"))
    return (
        english_only,
        has_honorific,
        has_parenthetical,
        compact_hangul,
        legal_shortform,
        _timestamp_sort_key(member.created_at),
        len(normalized),
        member.id,
    )


def _contains_hangul(text: str) -> bool:
    return _HANGUL_RE.search(text) is not None


def _has_honorific(name: str) -> bool:
    normalized = normalize(name)
    if "(" in normalized and normalized.endswith(")"):
        normalized = normalized[: normalized.rfind("(")].rstrip()
    return any(normalized.endswith(suffix) for suffix in _HONORIFIC_SUFFIXES)


def _timestamp_sort_key(timestamp: str) -> str:
    return timestamp


def _min_component_alias_edge_similarity(
    component_ids: set[str],
    graph: dict[str, set[str]],
    embeddings: dict[str, np.ndarray[Any, np.dtype[np.float32]]],
) -> float | None:
    cosine_values: list[float] = []
    seen_edges: set[tuple[str, str]] = set()
    for left_id in component_ids:
        left_embedding = embeddings.get(left_id)
        if left_embedding is None:
            continue
        for right_id in graph[left_id]:
            if right_id not in component_ids:
                continue
            edge_key = tuple(sorted((left_id, right_id)))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            right_embedding = embeddings.get(right_id)
            if right_embedding is None:
                continue
            cosine_values.append(cosine_similarity(left_embedding, right_embedding))
    if not cosine_values:
        return None
    return round(min(cosine_values), 4)


def _apply_family_merge(
    connection: sqlite3.Connection,
    family: EngramMergeFamily,
) -> None:
    survivor = family.survivor
    merged_members = family.merged_members
    merged_ids = [member.id for member in merged_members]
    component_ids = [survivor.id, *merged_ids]
    id_map = {engram_id: survivor.id for engram_id in component_ids}

    _fill_survivor_description(connection, survivor, merged_members)
    for member in (survivor, *merged_members):
        _store_aliases(connection, survivor.id, member.canonical_name)
        connection.execute(
            "INSERT OR IGNORE INTO engram_aliases (engram_id, alias_key, alias_kind) "
            "SELECT ?, alias_key, alias_kind FROM engram_aliases WHERE engram_id = ?",
            (survivor.id, member.id),
        )

    if merged_ids:
        placeholders = ", ".join("?" for _ in merged_ids)
        connection.execute(
            f"INSERT OR IGNORE INTO document_engrams (document_id, engram_id) "
            f"SELECT document_id, ? FROM document_engrams WHERE engram_id IN ({placeholders})",
            (survivor.id, *merged_ids),
        )
        connection.execute(
            f"DELETE FROM document_engrams WHERE engram_id IN ({placeholders})",
            merged_ids,
        )

    _merge_component_edges(connection, component_ids, id_map)
    _merge_component_projection(connection, survivor.id, merged_ids)
    _merge_component_embedding(connection, survivor.id, merged_ids)

    if merged_ids:
        placeholders = ", ".join("?" for _ in merged_ids)
        connection.execute(
            f"DELETE FROM engram_aliases WHERE engram_id IN ({placeholders})",
            merged_ids,
        )
        connection.execute(
            f"DELETE FROM engrams WHERE id IN ({placeholders})",
            merged_ids,
        )


def _fill_survivor_description(
    connection: sqlite3.Connection,
    survivor: EngramMergeMember,
    merged_members: tuple[EngramMergeMember, ...],
) -> None:
    if survivor.description:
        return
    replacement = next((member.description for member in merged_members if member.description), None)
    if replacement is None:
        return
    connection.execute(
        "UPDATE engrams SET description = ? WHERE id = ?",
        (replacement, survivor.id),
    )


def _merge_component_edges(
    connection: sqlite3.Connection,
    component_ids: list[str],
    id_map: dict[str, str],
) -> None:
    placeholders = ", ".join("?" for _ in component_ids)
    rows = connection.execute(
        f"SELECT * FROM edges WHERE source_engram_id IN ({placeholders}) "
        f"OR target_engram_id IN ({placeholders})",
        (*component_ids, *component_ids),
    ).fetchall()
    if not rows:
        return

    edge_ids = [str(row["id"]) for row in rows]
    delete_placeholders = ", ".join("?" for _ in edge_ids)
    connection.execute(
        f"DELETE FROM edges WHERE id IN ({delete_placeholders})",
        edge_ids,
    )

    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        source_engram_id = id_map.get(str(row["source_engram_id"]), str(row["source_engram_id"]))
        target_engram_id = id_map.get(str(row["target_engram_id"]), str(row["target_engram_id"]))
        if source_engram_id == target_engram_id:
            continue

        key = (source_engram_id, target_engram_id, str(row["predicate"]))
        existing = deduped.get(key)
        row_confidence = float(row["confidence"])
        row_created_at = str(row["created_at"])
        if existing is None:
            deduped[key] = {
                "id": str(row["id"]),
                "source_engram_id": source_engram_id,
                "target_engram_id": target_engram_id,
                "predicate": str(row["predicate"]),
                "confidence": row_confidence,
                "source_document_id": row["source_document_id"],
                "created_at": row_created_at,
            }
            continue

        existing["confidence"] = max(float(existing["confidence"]), row_confidence)
        if existing["source_document_id"] is None and row["source_document_id"] is not None:
            existing["source_document_id"] = row["source_document_id"]
        if row_created_at < str(existing["created_at"]):
            existing["created_at"] = row_created_at

    for edge in deduped.values():
        connection.execute(
            "INSERT INTO edges "
            "(id, source_engram_id, target_engram_id, predicate, confidence, source_document_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                edge["id"],
                edge["source_engram_id"],
                edge["target_engram_id"],
                edge["predicate"],
                edge["confidence"],
                edge["source_document_id"],
                edge["created_at"],
            ),
        )


def _merge_component_projection(
    connection: sqlite3.Connection,
    survivor_id: str,
    merged_ids: list[str],
) -> None:
    if not _table_exists(connection, "projections"):
        return
    survivor_projection = connection.execute(
        "SELECT * FROM projections WHERE engram_id = ?",
        (survivor_id,),
    ).fetchone()
    if survivor_projection is None and merged_ids:
        placeholders = ", ".join("?" for _ in merged_ids)
        fallback_projection = connection.execute(
            f"SELECT * FROM projections WHERE engram_id IN ({placeholders}) ORDER BY updated_at, engram_id LIMIT 1",
            merged_ids,
        ).fetchone()
        if fallback_projection is not None:
            connection.execute(
                "INSERT OR REPLACE INTO projections "
                "(engram_id, x, y, z, cluster_id, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    survivor_id,
                    fallback_projection["x"],
                    fallback_projection["y"],
                    fallback_projection["z"],
                    fallback_projection["cluster_id"],
                    fallback_projection["updated_at"],
                ),
            )
    if merged_ids:
        placeholders = ", ".join("?" for _ in merged_ids)
        connection.execute(
            f"DELETE FROM projections WHERE engram_id IN ({placeholders})",
            merged_ids,
        )


def _merge_component_embedding(
    connection: sqlite3.Connection,
    survivor_id: str,
    merged_ids: list[str],
) -> None:
    if not _table_exists(connection, "engram_embeddings"):
        return
    survivor_embedding = connection.execute(
        "SELECT embedding FROM engram_embeddings WHERE engram_id = ?",
        (survivor_id,),
    ).fetchone()
    if survivor_embedding is None and merged_ids:
        placeholders = ", ".join("?" for _ in merged_ids)
        fallback_embedding = connection.execute(
            f"SELECT embedding FROM engram_embeddings WHERE engram_id IN ({placeholders}) LIMIT 1",
            merged_ids,
        ).fetchone()
        if fallback_embedding is not None:
            connection.execute(
                "INSERT INTO engram_embeddings (engram_id, embedding) VALUES (?, ?)",
                (survivor_id, fallback_embedding["embedding"]),
            )
    if merged_ids:
        placeholders = ", ".join("?" for _ in merged_ids)
        connection.execute(
            f"DELETE FROM engram_embeddings WHERE engram_id IN ({placeholders})",
            merged_ids,
        )


def _count_rows(connection: sqlite3.Connection, table_name: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()  # noqa: S608
    return int(row["count"]) if row is not None else 0


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT count(*) AS count FROM sqlite_master WHERE name = ?",
        (table_name,),
    ).fetchone()
    return bool(row is not None and row["count"] > 0)


def _backup_db(db_path: Path, started_at: str) -> Path:
    stamp = started_at.replace(":", "").replace("+00:00", "Z")
    backup_path = db_path.with_name(f"{db_path.stem}-{stamp}.backup{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    return backup_path
