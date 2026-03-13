"""Database schema — all DDL statements."""

import aiosqlite


async def create_core_tables(db: aiosqlite.Connection) -> None:
    """Create all core tables, indexes, FTS5, and triggers. Idempotent.

    Does NOT create vec0 virtual tables — call create_vec_tables() separately.
    """

    # ── Core tables ──────────────────────────────────────────

    await db.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
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
        CREATE TABLE IF NOT EXISTS engrams (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            canonical_name TEXT NOT NULL UNIQUE,
            concept_hash TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
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

    # ── Indexes ──────────────────────────────────────────────

    await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_source_type ON documents(source_type)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_processed ON documents(processed)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_edges_source_engram ON edges(source_engram_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_edges_target_engram ON edges(target_engram_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_edges_predicate ON edges(predicate)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_triaged ON documents(triaged)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_documents_source_uri ON documents(source_uri)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_projections_cluster ON projections(cluster_id)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_document_engrams_engram ON document_engrams(engram_id)")

    # ── FTS5 (external content synced via triggers) ──────────

    if not await _table_exists(db, "documents_fts"):
        await db.execute("""
            CREATE VIRTUAL TABLE documents_fts USING fts5(
                title, text,
                content='documents',
                content_rowid='rowid'
            )
        """)

    # ── FTS5 sync triggers (DELETE+INSERT pattern for safety) ─

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

    # ── Auto-update updated_at on documents ──────────────────
    # Safe: PRAGMA recursive_triggers defaults OFF, preventing infinite recursion

    await db.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_updated_at
        AFTER UPDATE ON documents BEGIN
            UPDATE documents SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = new.id;
        END
    """)

    await db.commit()


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


async def create_tables(db: aiosqlite.Connection, embedding_dim: int = 384) -> None:
    """Create all tables, virtual tables, indexes, and triggers. Idempotent."""
    await create_core_tables(db)
    await create_vec_tables(db, embedding_dim)


async def _table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    cursor = await db.execute(
        "SELECT count(*) FROM sqlite_master WHERE name = ?", (table_name,)
    )
    row = await cursor.fetchone()
    if row is None:
        return False
    return bool(row[0] > 0)
