"""Database schema — all DDL statements and migration framework."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Coroutine
from contextlib import suppress
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_VEC_DIM_RE = re.compile(r"embedding\s+float\[(\d+)\]", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Migration framework
# ---------------------------------------------------------------------------

_MigrationFn = Callable[[aiosqlite.Connection], Coroutine[Any, Any, None]]
_MIGRATIONS: list[tuple[int, str, _MigrationFn]] = []
# Populated after function definitions below.  See _register_migrations().


async def run_migrations(db: aiosqlite.Connection) -> None:
    """Run all pending schema migrations.  Idempotent.

    For fresh databases every migration runs in order.  For existing databases
    that predate the migration framework the baseline migration is marked as
    already applied and only newer migrations execute.
    """
    await db.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)
    await db.commit()

    cursor = await db.execute("SELECT version FROM _migrations ORDER BY version")
    applied = {row["version"] for row in await cursor.fetchall()}
    await cursor.close()

    # Bootstrap: pre-migration database (tables exist, no _migrations rows).
    # Run the baseline migration anyway (it's idempotent) to pick up any
    # tables or fixups added since the database was originally created.
    if not applied and await _table_exists(db, "documents"):
        logger.info("Bootstrapping migration framework on existing database")
        await _migration_001_baseline(db)
        await db.execute(
            "INSERT INTO _migrations (version, name) VALUES (?, ?)",
            (1, "baseline_schema"),
        )
        await db.commit()
        applied.add(1)

    for version, name, fn in _MIGRATIONS:
        if version in applied:
            continue
        logger.info("Running migration %d: %s", version, name)
        await fn(db)
        await db.execute(
            "INSERT INTO _migrations (version, name) VALUES (?, ?)",
            (version, name),
        )
        await db.commit()
        logger.info("Migration %d applied", version)

    # Post-migration maintenance (always runs, idempotent)
    from hypomnema.ontology.engram import backfill_engram_aliases

    await backfill_engram_aliases(db)
    await db.commit()


# ---------------------------------------------------------------------------
# Migration 1 — baseline schema (the complete v0.1.0 schema)
# ---------------------------------------------------------------------------


async def _migration_001_baseline(db: aiosqlite.Connection) -> None:
    """Complete baseline: all tables, columns, indexes, FTS5, triggers."""
    await _create_core_tables_impl(db)


async def _create_core_tables_impl(db: aiosqlite.Connection) -> None:
    """Create all core tables, indexes, FTS5, and triggers. Idempotent.

    Does NOT create vec0 virtual tables — call create_vec_tables() separately.
    """

    # ── Core tables ──────────────────────────────────────────

    await db.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
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
            tidy_level TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS engrams (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            canonical_name TEXT NOT NULL UNIQUE,
            concept_hash TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS engram_aliases (
            engram_id TEXT NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
            alias_key TEXT NOT NULL,
            alias_kind TEXT NOT NULL,
            PRIMARY KEY (engram_id, alias_key)
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS edges (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
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
        CREATE TABLE IF NOT EXISTS document_engrams (
            document_id TEXT NOT NULL REFERENCES documents(id),
            engram_id TEXT NOT NULL REFERENCES engrams(id),
            PRIMARY KEY (document_id, engram_id)
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS feed_sources (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            name TEXT NOT NULL,
            feed_type TEXT NOT NULL CHECK (feed_type IN ('rss', 'scrape', 'youtube')),
            url TEXT NOT NULL,
            schedule TEXT NOT NULL DEFAULT '0 */6 * * *',
            active INTEGER NOT NULL DEFAULT 1,
            last_fetched TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS projections (
            engram_id TEXT PRIMARY KEY REFERENCES engrams(id),
            x REAL NOT NULL,
            y REAL NOT NULL,
            z REAL NOT NULL,
            cluster_id INTEGER,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            encrypted INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    await _migrate_add_columns(db)
    documents_rebuilt = await _migrate_source_type_url(db)

    # ── Indexes ──────────────────────────────────────────────

    await _ensure_core_indexes(db)

    # ── FTS5 (external content synced via triggers) ──────────

    if not await _table_exists(db, "documents_fts"):
        await db.execute("""
            CREATE VIRTUAL TABLE documents_fts USING fts5(
                title, text,
                content='documents',
                content_rowid='rowid'
            )
        """)

    # ── FTS5 sync triggers + updated_at trigger ──────────────

    await _ensure_documents_triggers(db)
    if documents_rebuilt:
        await db.execute("INSERT INTO documents_fts(documents_fts) VALUES ('rebuild')")

    await db.commit()


async def _migrate_add_columns(db: aiosqlite.Connection) -> None:
    """Add columns introduced after initial schema (idempotent)."""
    columns = {
        "tidy_title": "TEXT",
        "tidy_text": "TEXT",
        "tidy_level": "TEXT",
        "revision": "INTEGER NOT NULL DEFAULT 1",
        "heat_score": "REAL",
        "heat_tier": "TEXT",
    }
    for col, definition in columns.items():
        with suppress(Exception):
            await db.execute(f"ALTER TABLE documents ADD COLUMN {col} {definition}")  # noqa: S608


async def _migrate_source_type_url(db: aiosqlite.Connection) -> bool:
    """Repair the documents schema and migrate it to accept the 'url' source type."""
    cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'documents'")
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return False
    ddl = str(row["sql"]) if row["sql"] else ""
    needs_url_upgrade = "'url'" not in ddl
    has_legacy_documents = await _table_exists(db, "_documents_old")
    has_legacy_document_refs = await _table_references_parent(
        db, "edges", "_documents_old"
    ) or await _table_references_parent(db, "document_engrams", "_documents_old")
    has_legacy_document_objects = await _objects_bound_to_table(
        db,
        names=[
            "idx_documents_source_type",
            "idx_documents_processed",
            "idx_documents_created_at",
            "idx_documents_triaged",
            "idx_documents_source_uri",
            "documents_fts_insert",
            "documents_fts_update",
            "documents_fts_delete",
            "documents_updated_at",
        ],
        table_name="_documents_old",
    )

    if not (needs_url_upgrade or has_legacy_documents or has_legacy_document_refs or has_legacy_document_objects):
        return False

    await db.commit()
    await db.execute("PRAGMA foreign_keys=OFF")

    try:
        documents_source_table = await _move_table_aside(
            db,
            table_name="documents",
            temp_base="_documents_migration_source",
        )
        legacy_documents_table = (
            "_documents_old" if has_legacy_documents and documents_source_table != "_documents_old" else None
        )

        await _drop_documents_objects(db)
        await db.execute(_documents_table_sql("documents"))
        if documents_source_table is not None:
            await _copy_documents_rows(
                db,
                source_table=documents_source_table,
                destination_table="documents",
                or_ignore=False,
            )
        if legacy_documents_table is not None:
            await _copy_documents_rows(
                db,
                source_table=legacy_documents_table,
                destination_table="documents",
                or_ignore=True,
            )

        await _rebuild_edges_table(db)
        await _rebuild_document_engrams_table(db)

        if documents_source_table is not None:
            await db.execute(f"DROP TABLE {documents_source_table}")  # noqa: S608
        if legacy_documents_table is not None:
            await db.execute(f"DROP TABLE {legacy_documents_table}")  # noqa: S608

        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.execute("PRAGMA foreign_keys=ON")

    return True


async def create_vec_tables(db: aiosqlite.Connection, embedding_dim: int = 384) -> None:
    """Create vec0 virtual tables for embeddings. Idempotent."""

    if not await _table_exists(db, "engram_embeddings"):
        await db.execute(
            f"CREATE VIRTUAL TABLE engram_embeddings USING vec0("
            f"engram_id TEXT PRIMARY KEY, embedding float[{embedding_dim}])"
        )

    if not await _table_exists(db, "document_embeddings"):
        await db.execute(
            f"CREATE VIRTUAL TABLE document_embeddings USING vec0("
            f"document_id TEXT PRIMARY KEY, embedding float[{embedding_dim}])"
        )

    await db.commit()


async def get_vec_table_embedding_dim(
    db: aiosqlite.Connection,
    table_name: str,
) -> int | None:
    """Return the configured vector dimension for a vec table, if present."""
    cursor = await db.execute(
        "SELECT sql FROM sqlite_master WHERE name = ?",
        (table_name,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None or row["sql"] is None:
        return None
    match = _VEC_DIM_RE.search(str(row["sql"]))
    if match is None:
        return None
    return int(match.group(1))


async def _get_vec_table_dims(
    db: aiosqlite.Connection,
    table_names: list[str],
) -> dict[str, int | None]:
    """Return the configured vector dimensions for multiple vec tables in one query."""
    placeholders = ",".join("?" for _ in table_names)
    cursor = await db.execute(
        f"SELECT name, sql FROM sqlite_master WHERE name IN ({placeholders})",  # noqa: S608
        table_names,
    )
    rows = {row["name"]: row["sql"] for row in await cursor.fetchall()}
    await cursor.close()
    result: dict[str, int | None] = {}
    for name in table_names:
        sql = rows.get(name)
        if sql is None:
            result[name] = None
            continue
        match = _VEC_DIM_RE.search(str(sql))
        result[name] = int(match.group(1)) if match else None
    return result


async def ensure_vec_tables(db: aiosqlite.Connection, embedding_dim: int = 384) -> bool:
    """Ensure vec tables exist and match the configured embedding dimension.

    Returns True if an incompatible existing vec schema was rebuilt, which
    implies the knowledge graph was reset and documents need reprocessing.
    """
    existing_dims = await _get_vec_table_dims(db, ["engram_embeddings", "document_embeddings"])
    needs_rebuild = any(dim is not None and dim != embedding_dim for dim in existing_dims.values())
    if needs_rebuild:
        await reset_knowledge_graph(db)
        await drop_vec_tables(db)
    await create_vec_tables(db, embedding_dim)
    return needs_rebuild


async def drop_vec_tables(db: aiosqlite.Connection) -> None:
    """Drop vec0 virtual tables for embeddings."""
    for table in ("engram_embeddings", "document_embeddings"):
        if await _table_exists(db, table):
            await db.execute(f"DROP TABLE {table}")  # noqa: S608
    await db.commit()


async def reset_knowledge_graph(db: aiosqlite.Connection) -> None:
    """Delete all engrams, edges, projections, and document-engram links.

    Preserves raw documents but resets their processed/triaged flags so they
    will be re-ingested through the ontology pipeline.
    """
    await db.execute("DELETE FROM edges")
    await db.execute("DELETE FROM document_engrams")
    await db.execute("DELETE FROM projections")
    await db.execute("DELETE FROM engram_aliases")
    await db.execute("DELETE FROM engrams")
    await db.execute("UPDATE documents SET processed = 0, triaged = 0")
    await db.commit()


async def create_tables(db: aiosqlite.Connection, embedding_dim: int = 384) -> None:
    """Create all tables, virtual tables, indexes, and triggers. Idempotent."""
    await create_core_tables(db)
    await create_vec_tables(db, embedding_dim)


async def _table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    cursor = await db.execute("SELECT count(*) FROM sqlite_master WHERE name = ?", (table_name,))
    row = await cursor.fetchone()
    if row is None:
        return False
    return bool(row[0] > 0)


async def _ensure_core_indexes(db: aiosqlite.Connection) -> None:
    await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_source_type ON documents(source_type)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_processed ON documents(processed)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_triaged ON documents(triaged)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_source_uri ON documents(source_uri)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_edges_source_engram ON edges(source_engram_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_edges_target_engram ON edges(target_engram_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_edges_predicate ON edges(predicate)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_projections_cluster ON projections(cluster_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_document_engrams_engram ON document_engrams(engram_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_document_engrams_document ON document_engrams(document_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_engram_aliases_key ON engram_aliases(alias_key)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_heat_tier ON documents(heat_tier)")


async def _ensure_documents_triggers(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_fts_insert
        AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, title, text)
            VALUES (new.rowid, new.title, new.text);
        END
    """)
    await db.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_fts_update
        AFTER UPDATE OF title, text ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, title, text)
            VALUES ('delete', old.rowid, old.title, old.text);
            INSERT INTO documents_fts(rowid, title, text)
            VALUES (new.rowid, new.title, new.text);
        END
    """)
    await db.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_fts_delete
        BEFORE DELETE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, title, text)
            VALUES ('delete', old.rowid, old.title, old.text);
        END
    """)
    # Safe: PRAGMA recursive_triggers defaults OFF, preventing infinite recursion
    await db.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_updated_at
        AFTER UPDATE ON documents BEGIN
            UPDATE documents SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = new.id;
        END
    """)


def _documents_table_sql(table_name: str) -> str:
    return f"""
        CREATE TABLE {table_name} (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
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
            tidy_level TEXT,
            heat_score REAL,
            heat_tier TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """


async def _table_references_parent(
    db: aiosqlite.Connection,
    child_table: str,
    parent_table: str,
) -> bool:
    cursor = await db.execute(f"PRAGMA foreign_key_list({child_table})")  # noqa: S608
    rows = await cursor.fetchall()
    await cursor.close()
    return any(str(row["table"]) == parent_table for row in rows)


async def _objects_bound_to_table(
    db: aiosqlite.Connection,
    *,
    names: list[str],
    table_name: str,
) -> bool:
    placeholders = ",".join("?" for _ in names)
    cursor = await db.execute(
        f"SELECT count(*) FROM sqlite_master WHERE name IN ({placeholders}) AND tbl_name = ?",  # noqa: S608
        (*names, table_name),
    )
    row = await cursor.fetchone()
    await cursor.close()
    return bool(row and row[0] > 0)


async def _drop_documents_objects(db: aiosqlite.Connection) -> None:
    for trigger_name in (
        "documents_fts_insert",
        "documents_fts_update",
        "documents_fts_delete",
        "documents_updated_at",
    ):
        await db.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")  # noqa: S608
    for index_name in (
        "idx_documents_source_type",
        "idx_documents_processed",
        "idx_documents_created_at",
        "idx_documents_triaged",
        "idx_documents_source_uri",
    ):
        await db.execute(f"DROP INDEX IF EXISTS {index_name}")  # noqa: S608


async def _move_table_aside(
    db: aiosqlite.Connection,
    *,
    table_name: str,
    temp_base: str,
) -> str | None:
    if not await _table_exists(db, table_name):
        return None
    temp_name = temp_base
    suffix = 0
    while await _table_exists(db, temp_name):
        suffix += 1
        temp_name = f"{temp_base}_{suffix}"
    await db.execute(f"ALTER TABLE {table_name} RENAME TO {temp_name}")  # noqa: S608
    return temp_name


async def _copy_documents_rows(
    db: aiosqlite.Connection,
    *,
    source_table: str,
    destination_table: str,
    or_ignore: bool,
) -> None:
    all_columns = [
        "id",
        "source_type",
        "title",
        "text",
        "mime_type",
        "source_uri",
        "metadata",
        "triaged",
        "processed",
        "revision",
        "tidy_title",
        "tidy_text",
        "tidy_level",
        "heat_score",
        "heat_tier",
        "created_at",
        "updated_at",
    ]
    cursor = await db.execute(f"PRAGMA table_info({source_table})")  # noqa: S608
    source_columns = {str(row["name"]) for row in await cursor.fetchall()}
    await cursor.close()
    select_exprs = [col if col in source_columns else f"NULL AS {col}" for col in all_columns]
    insert_mode = "INSERT OR IGNORE" if or_ignore else "INSERT"
    await db.execute(
        f"{insert_mode} INTO {destination_table} ("  # noqa: S608
        f"{', '.join(all_columns)}"
        f") SELECT {', '.join(select_exprs)} "  # noqa: S608
        f"FROM {source_table}"  # noqa: S608
    )


async def _rebuild_document_engrams_table(db: aiosqlite.Connection) -> None:
    temp_name = await _move_table_aside(
        db,
        table_name="document_engrams",
        temp_base="_document_engrams_migration_source",
    )
    await db.execute("""
        CREATE TABLE document_engrams (
            document_id TEXT NOT NULL REFERENCES documents(id),
            engram_id TEXT NOT NULL REFERENCES engrams(id),
            PRIMARY KEY (document_id, engram_id)
        )
    """)
    if temp_name is not None:
        await db.execute(
            f"INSERT INTO document_engrams (document_id, engram_id) "  # noqa: S608
            f"SELECT document_id, engram_id FROM {temp_name}"  # noqa: S608
        )
        await db.execute(f"DROP TABLE {temp_name}")  # noqa: S608


async def _rebuild_edges_table(db: aiosqlite.Connection) -> None:
    temp_name = await _move_table_aside(
        db,
        table_name="edges",
        temp_base="_edges_migration_source",
    )
    await db.execute("""
        CREATE TABLE edges (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            source_engram_id TEXT NOT NULL REFERENCES engrams(id),
            target_engram_id TEXT NOT NULL REFERENCES engrams(id),
            predicate TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            source_document_id TEXT REFERENCES documents(id),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            UNIQUE(source_engram_id, target_engram_id, predicate)
        )
    """)
    if temp_name is not None:
        await db.execute(
            f"INSERT INTO edges ("  # noqa: S608
            "id, source_engram_id, target_engram_id, predicate, confidence, source_document_id, created_at"
            f") SELECT id, source_engram_id, target_engram_id, predicate, confidence, source_document_id, created_at "  # noqa: S608
            f"FROM {temp_name}"  # noqa: S608
        )
        await db.execute(f"DROP TABLE {temp_name}")  # noqa: S608


# ---------------------------------------------------------------------------
# Migration 2 — add document heat columns
# ---------------------------------------------------------------------------


async def _migration_002_heat_columns(db: aiosqlite.Connection) -> None:
    """Add heat_score and heat_tier columns to documents table."""
    for col, definition in (("heat_score", "REAL"), ("heat_tier", "TEXT")):
        with suppress(Exception):
            await db.execute(f"ALTER TABLE documents ADD COLUMN {col} {definition}")  # noqa: S608
    await db.commit()


# ---------------------------------------------------------------------------
# Migration registry — keep at bottom so all functions are defined
# ---------------------------------------------------------------------------


def _register_migrations() -> None:
    _MIGRATIONS.clear()
    _MIGRATIONS.append((1, "baseline_schema", _migration_001_baseline))
    _MIGRATIONS.append((2, "heat_columns", _migration_002_heat_columns))


_register_migrations()


# ---------------------------------------------------------------------------
# Public API (backward-compatible wrappers)
# ---------------------------------------------------------------------------


async def create_core_tables(db: aiosqlite.Connection) -> None:
    """Create all core tables via the migration framework.  Idempotent.

    Prefer ``run_migrations`` for new code.
    """
    await run_migrations(db)
