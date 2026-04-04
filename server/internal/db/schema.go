package db

// Schema mirrors the Python SQLite schema exactly so both versions can share the same .db file.
const schema = `
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (source_type IN ('scribble','file','feed','url','synthesis')),
    title       TEXT,
    text        TEXT NOT NULL,
    mime_type   TEXT,
    source_uri  TEXT,
    metadata    TEXT,
    triaged     INTEGER DEFAULT 0,
    processed   INTEGER DEFAULT 0,
    revision    INTEGER DEFAULT 1,
    tidy_title  TEXT,
    tidy_text   TEXT,
    tidy_level  TEXT,
    annotation  TEXT,
    heat_score  REAL,
    heat_tier   TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_source_type ON documents(source_type);
CREATE INDEX IF NOT EXISTS idx_documents_processed  ON documents(processed);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at);
CREATE INDEX IF NOT EXISTS idx_documents_triaged    ON documents(triaged);
CREATE INDEX IF NOT EXISTS idx_documents_source_uri ON documents(source_uri);
CREATE INDEX IF NOT EXISTS idx_documents_heat_tier  ON documents(heat_tier);

CREATE TRIGGER IF NOT EXISTS documents_updated_at
    AFTER UPDATE ON documents
    FOR EACH ROW
    BEGIN
        UPDATE documents SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
        WHERE id = NEW.id;
    END;

-- FTS5 for keyword search
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title, text, annotation,
    content='documents',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS documents_fts_insert AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, text, annotation)
    VALUES (NEW.rowid, NEW.title, NEW.text, NEW.annotation);
END;
CREATE TRIGGER IF NOT EXISTS documents_fts_update AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, text, annotation)
    VALUES ('delete', OLD.rowid, OLD.title, OLD.text, OLD.annotation);
    INSERT INTO documents_fts(rowid, title, text, annotation)
    VALUES (NEW.rowid, NEW.title, NEW.text, NEW.annotation);
END;
CREATE TRIGGER IF NOT EXISTS documents_fts_delete AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, text, annotation)
    VALUES ('delete', OLD.rowid, OLD.title, OLD.text, OLD.annotation);
END;

CREATE TABLE IF NOT EXISTS engrams (
    id                 TEXT PRIMARY KEY,
    canonical_name     TEXT UNIQUE NOT NULL,
    concept_hash       TEXT UNIQUE,
    description        TEXT,
    article            TEXT,
    article_updated_at TEXT,
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS engram_aliases (
    engram_id  TEXT NOT NULL REFERENCES engrams(id),
    alias_key  TEXT NOT NULL,
    alias_kind TEXT NOT NULL,
    PRIMARY KEY (engram_id, alias_key)
);

CREATE TABLE IF NOT EXISTS edges (
    id                TEXT PRIMARY KEY,
    source_engram_id  TEXT NOT NULL REFERENCES engrams(id),
    target_engram_id  TEXT NOT NULL REFERENCES engrams(id),
    predicate         TEXT NOT NULL,
    confidence        REAL NOT NULL,
    source_document_id TEXT REFERENCES documents(id),
    created_at        TEXT NOT NULL,
    UNIQUE(source_engram_id, target_engram_id, predicate)
);

CREATE INDEX IF NOT EXISTS idx_edges_source    ON edges(source_engram_id);
CREATE INDEX IF NOT EXISTS idx_edges_target    ON edges(target_engram_id);
CREATE INDEX IF NOT EXISTS idx_edges_predicate ON edges(predicate);

CREATE TABLE IF NOT EXISTS document_engrams (
    document_id TEXT NOT NULL REFERENCES documents(id),
    engram_id   TEXT NOT NULL REFERENCES engrams(id),
    PRIMARY KEY (document_id, engram_id)
);

CREATE TABLE IF NOT EXISTS document_revisions (
    id          TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    revision    INTEGER NOT NULL,
    text        TEXT NOT NULL,
    annotation  TEXT,
    title       TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feed_sources (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    feed_type    TEXT NOT NULL CHECK (feed_type IN ('rss','scrape','youtube')),
    url          TEXT NOT NULL,
    schedule     TEXT DEFAULT '0 */6 * * *',
    active       INTEGER DEFAULT 1,
    last_fetched TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projections (
    engram_id  TEXT PRIMARY KEY REFERENCES engrams(id),
    x          REAL NOT NULL,
    y          REAL NOT NULL,
    z          REAL NOT NULL,
    cluster_id INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    encrypted  INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cluster_overviews (
    cluster_id   INTEGER PRIMARY KEY,
    label        TEXT NOT NULL,
    summary      TEXT NOT NULL,
    engram_count INTEGER NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lint_issues (
    id          TEXT PRIMARY KEY,
    issue_type  TEXT NOT NULL,
    engram_ids  TEXT NOT NULL,
    description TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'warning',
    resolved    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lint_issues_type ON lint_issues(issue_type);
CREATE INDEX IF NOT EXISTS idx_lint_issues_resolved ON lint_issues(resolved);
`
