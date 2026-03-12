# Hypomnema — Phased TDD Implementation Plan

## Context

Hypomnema is a greenfield project (only SPEC.md exists). It's an Automated Ontological Synthesizer that builds a knowledge graph from zero-friction inputs, extracts deduplicated concept nodes (Engrams), generates typed relational edges, and visualizes structural gaps. This plan breaks the full build into dependency-ordered phases, each driven by tests written first.

**Stack:** Python/FastAPI backend, SQLite (WAL + sqlite-vec) database, Next.js PWA frontend.

## Progress

| Phase | Status | Tests | Notes |
|-------|--------|-------|-------|
| P0 — Scaffold | Done | 23 backend + 8 frontend | ruff, mypy strict, eslint, tsc all clean |
| P1 — Database | Done | 50 backend | WAL, sqlite-vec, FTS5, all triggers verified |
| P2 — LLM + Embeddings | Done | 29 backend (28 pass, 1 skip) | Protocol-based LLM + embedding abstractions, mock + real clients |
| P3 — Manual Ingestion | Done | 25 backend (125 pass, 1 skip total) | Scribble + file parsing (PDF/DOCX/MD), RETURNING * pattern |
| P4 — Entity Extraction | Not started | — | |
| P5 — Edge Generation | Not started | — | |
| P6 — Triage | Not started | — | |
| P7 — Feeds + Scheduler | Not started | — | |
| P8 — Search | Not started | — | |
| P9 — API Layer | Not started | — | |
| P10 — Viz Pipeline | Not started | — | |
| P11–14 — Frontend | Not started | — | |
| P15 — Deployment | Not started | — | |

### Implementation Notes (P0+P1+P2+P3)

- **Dev tooling added beyond plan:** `ruff` (lint), `mypy` strict with pydantic plugin (typecheck), `tsc --noEmit` (frontend typecheck). Dev deps use `[dependency-groups]` not `[project.optional-dependencies]`.
- **FTS5 trigger pattern:** Plan specified `DELETE FROM documents_fts` in update/delete triggers. This causes "database disk image is malformed" with external content FTS5. Fixed to use the correct `INSERT INTO fts(fts, ...) VALUES('delete', ...)` pattern.
- **vec0 idempotency:** `CREATE VIRTUAL TABLE ... USING vec0` does not support `IF NOT EXISTS`. Schema uses `_table_exists()` helper querying `sqlite_master`.
- **Models simplified:** Shared `_parse_iso_datetime()` helper and generic `_from_row(cls, row)` using `dict(row)` unpacking instead of per-model field-by-field constructors.
- **Frontend:** Next.js 16.1.6 (latest stable), vitest 4, `ApiClient.request()` detects `FormData` body to skip `Content-Type: application/json` header.
- **Line length:** 120 (not 100) — practical for SQL strings in tests.
- **LLM async, embeddings sync:** LLM methods are async (network I/O); embedding methods are sync (CPU-bound local compute). `complete_json()` parses text output as JSON — no provider-specific structured output modes.
- **mypy strict compliance:** `json.loads()` returns `Any`, so `complete_json()` uses `dict(json.loads(text))` to satisfy `no-any-return`. Runtime validation uses proper exceptions (not `assert`) since asserts are stripped with `-O`.
- **GPU test gated:** `LocalEmbeddingModel` test requires `HYPOMNEMA_TEST_GPU=1` env var; skipped otherwise.
- **Ingestion separation of concerns:** `scribble.py` handles text-only input; `file_parser.py` handles file text extraction (sync, CPU-bound) and file ingestion (async, DB insert). Parsing is pure sync; storage is async.
- **RETURNING * for row retrieval:** Confirmed working with aiosqlite + SQLite 3.41+. Avoids separate SELECT after INSERT.
- **Test fixtures programmatic:** PDF fixtures created via `pypdf.PdfWriter` with raw content streams (no `fpdf2` dep). DOCX via `python-docx`. MD is plaintext. All in `tests/test_ingestion/conftest.py`.
- **No TOCTOU in file parsing:** `parse_file()` lets underlying libraries raise `FileNotFoundError` naturally rather than pre-checking `path.exists()`.

---

## Project Structure

```
hypomnema/
├── backend/
│   ├── pyproject.toml                    # uv-managed
│   ├── src/hypomnema/
│   │   ├── main.py                       # FastAPI app factory + lifespan
│   │   ├── config.py                     # Pydantic Settings
│   │   ├── db/
│   │   │   ├── engine.py                 # get_db(), PRAGMAs, sqlite-vec loading
│   │   │   ├── schema.py                 # CREATE TABLE/VIRTUAL TABLE, FTS5
│   │   │   └── models.py                 # Pydantic models
│   │   ├── llm/
│   │   │   ├── base.py                   # LLMClient Protocol
│   │   │   ├── claude.py                 # Anthropic implementation
│   │   │   ├── google.py                 # Gemini implementation
│   │   │   └── mock.py                   # Deterministic mock for tests
│   │   ├── embeddings/
│   │   │   ├── base.py                   # EmbeddingModel Protocol
│   │   │   ├── local_gpu.py              # sentence-transformers
│   │   │   └── mock.py                   # Hash-seeded PRNG vectors
│   │   ├── ingestion/
│   │   │   ├── scribble.py               # Text input handler
│   │   │   ├── file_parser.py            # PDF/DOCX/MD extraction
│   │   │   └── feeds.py                  # RSS, scrape, YouTube transcript
│   │   ├── triage/
│   │   │   └── bouncer.py                # Cheap relevance filter
│   │   ├── ontology/
│   │   │   ├── extractor.py              # LLM entity extraction
│   │   │   ├── normalizer.py             # Canonical string normalization
│   │   │   ├── engram.py                 # Concept hash, dedup, creation
│   │   │   ├── linker.py                 # Top-K retrieval + predicate assignment
│   │   │   └── pipeline.py              # Orchestrates extract → link flow
│   │   ├── search/
│   │   │   ├── doc_search.py             # Semantic + lexical (FTS5) hybrid
│   │   │   └── knowledge_search.py       # Graph edge/predicate queries
│   │   ├── visualization/
│   │   │   └── projection.py             # UMAP, clustering, gap detection
│   │   ├── scheduler/
│   │   │   └── cron.py                   # APScheduler within FastAPI lifespan
│   │   └── api/
│   │       ├── documents.py
│   │       ├── engrams.py
│   │       ├── search.py
│   │       ├── visualization.py
│   │       └── feeds.py
│   └── tests/
│       ├── conftest.py                   # Shared fixtures: tmp_db, mock_llm, mock_embeddings
│       ├── fixtures/                     # sample.pdf, sample.docx, sample.md
│       └── test_*/                       # Mirror of src/ structure
├── frontend/
│   ├── package.json                      # Next.js 16+, vitest, playwright, tailwind
│   ├── src/
│   │   ├── app/                          # App Router pages
│   │   ├── components/                   # ScribbleInput, DocumentCard, NetworkPanel, VizCanvas, etc.
│   │   ├── lib/api.ts                    # Typed fetch wrapper
│   │   ├── lib/types.ts                  # TS types matching backend models
│   │   └── hooks/                        # useDocuments, useEngrams, useSearch
│   ├── __tests__/
│   └── e2e/
├── start-web.sh                          # Local mode: localhost, auto-open browser
└── start-server.sh                       # Server mode: Tailscale bind, 24/7
```

---

## Database Schema

```sql
CREATE TABLE documents (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    source_type TEXT NOT NULL CHECK (source_type IN ('scribble','file','feed')),
    title TEXT,
    text TEXT NOT NULL,
    mime_type TEXT,
    source_uri TEXT,
    metadata TEXT,                         -- JSON blob
    triaged INTEGER NOT NULL DEFAULT 0,    -- 0=untriaged, 1=accepted, -1=rejected
    processed INTEGER NOT NULL DEFAULT 0,  -- 0=pending, 1=extracted, 2=linked
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE engrams (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    canonical_name TEXT NOT NULL UNIQUE,
    concept_hash TEXT NOT NULL UNIQUE,     -- LSH of embedding for O(1) dedup
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE edges (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    source_engram_id TEXT NOT NULL REFERENCES engrams(id),
    target_engram_id TEXT NOT NULL REFERENCES engrams(id),
    predicate TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_document_id TEXT REFERENCES documents(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(source_engram_id, target_engram_id, predicate)
);

CREATE TABLE document_engrams (
    document_id TEXT NOT NULL REFERENCES documents(id),
    engram_id TEXT NOT NULL REFERENCES engrams(id),
    PRIMARY KEY (document_id, engram_id)
);

CREATE VIRTUAL TABLE engram_embeddings USING vec0(
    engram_id TEXT PRIMARY KEY, embedding float[{dim}]
);
CREATE VIRTUAL TABLE document_embeddings USING vec0(
    document_id TEXT PRIMARY KEY, embedding float[{dim}]
);
CREATE VIRTUAL TABLE documents_fts USING fts5(title, text, content='documents', content_rowid='rowid');

CREATE TABLE feed_sources (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    name TEXT NOT NULL, feed_type TEXT NOT NULL CHECK (feed_type IN ('rss','scrape','youtube')),
    url TEXT NOT NULL, schedule TEXT NOT NULL DEFAULT '0 */6 * * *',
    active INTEGER NOT NULL DEFAULT 1, last_fetched TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE projections (
    engram_id TEXT PRIMARY KEY REFERENCES engrams(id),
    x REAL NOT NULL, y REAL NOT NULL, cluster_id INTEGER,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

---

## Key Architectural Decisions

**LLM Abstraction:** `Protocol`-based — `LLMClient` with `complete()` and `complete_json()`. Implementations: Claude (anthropic SDK), Google (google-genai SDK), Mock (deterministic, canned responses keyed by input substring).

**Embedding Abstraction:** `EmbeddingModel` Protocol with `dimension` property and `embed(texts)`. Mock uses hash-seeded PRNG for deterministic, unit-normalized vectors.

**Concept Hash (O(1) dedup):** Binarize embedding by sign → SHA-256 hash the bit-string. Similar embeddings collide = dedup.

**Predicate Vocabulary:** Enum — `contradicts`, `supports`, `extends`, `provides_methodology_for`, `is_example_of`, `is_prerequisite_for`, `generalizes`, `specializes`, `is_analogous_to`, `critiques`, `applies_to`, `derives_from`. LLM prompt constrained to this set.

**Background Processing:** `asyncio.create_task` / FastAPI `BackgroundTasks` after ingestion triggers ontology pipeline.

**Cronjobs:** APScheduler (async) within FastAPI lifespan, registered from `feed_sources` table.

**Frontend API Mocking:** `msw` (Mock Service Worker) for vitest; Playwright e2e runs against real backend with `HYPOMNEMA_LLM_PROVIDER=mock`.

---

## Phase Dependency Graph

```
P0 (Scaffold)
 └─ P1 (Database)
     ├─ P2 (LLM + Embedding Abstractions)
     │   ├─ P3 (Manual Ingestion)
     │   │   └─ P4 (Entity Extraction + Engrams)
     │   │       └─ P5 (Edge Generation)
     │   │           ├─ P6 (Triage)          ← can parallel with P8, P10
     │   │           │   └─ P7 (Feeds + Scheduler)
     │   │           ├─ P8 (Search)          ← can parallel with P6, P10
     │   │           └─ P10 (Viz Pipeline)   ← can parallel with P6, P8
     │   └─ P6 (also needs embeddings directly)
     └─ P9 (API Layer — needs all backend modules)
         ├─ P11 (Frontend: Stream)
         │   └─ P12 (Frontend: Doc Detail + Network)
         │       └─ P13 (Frontend: Search + Clusters)
         │           └─ P14 (Frontend: Viz Canvas)
         └─ P15 (Deployment + Integration)
```

---

## Phases

### Phase 0 — Project Scaffolding

**Goal:** Monorepo skeleton, dependency management, config system, test harnesses.

**Tests first:**
- `tests/test_config.py` — `Settings()` loads defaults; env vars override; mode validates to `local`|`server`
- `frontend/__tests__/lib/api.test.ts` — API client defaults to `localhost:8000`; env override works

**Build:**
- `backend/pyproject.toml` (uv) with all deps: `fastapi`, `uvicorn`, `aiosqlite`, `sqlite-vec`, `anthropic`, `google-genai`, `sentence-transformers`, `apscheduler`, `pydantic-settings`, `python-multipart`, `pypdf`, `python-docx`, `feedparser`, `youtube-transcript-api`, `umap-learn`, `scikit-learn`, `httpx`; dev: `pytest`, `pytest-asyncio`
- `backend/src/hypomnema/config.py` — Pydantic `Settings`
- `frontend/package.json` — Next.js 16+, TS, vitest, playwright, tailwind
- `frontend/src/lib/api.ts` — skeleton typed fetch wrapper

**Acceptance:** `uv run pytest` and `npm test` both green, zero import errors.

---

### Phase 1 — Database Layer

**Goal:** SQLite engine with WAL, sqlite-vec, full schema.

**Tests first** (`tests/test_db/`):
- `test_engine.py` — DB file created; WAL enabled; sqlite-vec loaded (`vec_version()`); foreign keys on
- `test_schema.py` — `create_tables()` idempotent; each table insertable/queryable; FK constraints enforced; vec virtual tables accept/return vectors; concept_hash unique constraint

**Shared fixture** (`conftest.py`): `tmp_db` — fresh temp SQLite with schema applied per test.

**Build:** `db/engine.py`, `db/schema.py`, `db/models.py`

---

### Phase 2 — LLM & Embedding Abstractions

**Goal:** Protocol interfaces + mock implementations for deterministic testing.

**Tests first:**
- `test_llm/test_clients.py` — Mock returns string/dict deterministically; same input → same output; Claude/Google instantiate without error; all three satisfy `LLMClient` Protocol
- `test_embeddings/test_models.py` — Mock dimension correct; deterministic vectors; different texts differ; batch works; vectors unit-normalized; LocalGPU model loads (skip if no GPU)

**Key mock design:** `MockLLMClient` accepts a `responses: dict[str, str|dict]` for canned replies keyed by substring match. `MockEmbeddingModel` hashes input text → seeds PRNG → generates normalized vector.

**Build:** `llm/base.py`, `llm/claude.py`, `llm/google.py`, `llm/mock.py`, `embeddings/base.py`, `embeddings/local_gpu.py`, `embeddings/mock.py`

---

### Phase 3 — Manual Ingestion

**Goal:** Scribble creation + file parsing (PDF/DOCX/MD) → stored in documents table. No ontology yet.

**Tests first:**
- `test_ingestion/test_scribble.py` — stores with `source_type='scribble'`; returns Document model; empty text rejected; optional title stored
- `test_ingestion/test_file_parser.py` — PDF/DOCX/MD extracts text; unsupported format raises; file throw stores document with correct `mime_type`

**Test fixtures:** `tests/fixtures/sample.pdf`, `sample.docx`, `sample.md`

**Build:** `ingestion/scribble.py`, `ingestion/file_parser.py` (uses `pypdf`, `python-docx`)

---

### Phase 4 — Entity Extraction & Engram Creation

**Goal:** LLM extracts entities → normalize → embed → concept hash → dedup → store Engrams.

**Tests first:**
- `test_ontology/test_extractor.py` — mock LLM returns entity list; empty text → empty list; JSON parsing correct
- `test_ontology/test_normalizer.py` — whitespace stripped; lowercased; LLM maps synonyms to same canonical form
- `test_ontology/test_engram.py` — concept hash deterministic; similar embeddings collide; distant differ; new concept creates engram + embedding row; duplicate returns existing; `document_engrams` junction created
- `test_ontology/test_pipeline.py` — end-to-end: text → engrams, doc marked `processed=1`; idempotent

**Build:** `ontology/extractor.py`, `ontology/normalizer.py`, `ontology/engram.py`, `ontology/pipeline.py`

---

### Phase 5 — Edge Generation

**Goal:** Top-K vector retrieval → LLM assigns typed predicates → edges stored.

**Tests first:**
- `test_ontology/test_linker.py` — top-K returns K nearest; excludes self; empty DB → empty; predicates from controlled vocabulary; edges stored with correct FKs; UNIQUE prevents duplicates; full linking flow works
- `test_ontology/test_pipeline.py` (extended) — two related docs produce edges; doc marked `processed=2`

**Build:** `ontology/linker.py` (Top-K via sqlite-vec KNN, predicate assignment), extend `pipeline.py`

---

### Phase 6 — Triage ("The Bouncer")

**Goal:** Cheap embedding similarity filter for automated feeds.

**Tests first** (`test_triage/test_bouncer.py`):
- Relevant content accepted; irrelevant rejected; threshold configurable; empty graph accepts all (bootstrap); `triaged` flag updated; rejected docs skip ontology

**Build:** `triage/bouncer.py` — embed text, max cosine sim against existing engrams, accept if > threshold

---

### Phase 7 — Automated Feed Ingestion

**Goal:** RSS, web scrape, YouTube transcript fetching + cronjob scheduling.

**Tests first:**
- `test_ingestion/test_feeds.py` — RSS XML parsed; URL dedup; HTML scrape extracts text; YouTube transcript extracted; creates `source_type='feed'` docs; passes through triage
- `test_scheduler/test_cron.py` — jobs registered from DB; respects `active` flag; updates `last_fetched`

**Build:** `ingestion/feeds.py` (feedparser, httpx, youtube-transcript-api), `scheduler/cron.py` (APScheduler async)

---

### Phase 8 — Search (parallelizable with P6, P10)

**Goal:** Doc Search (hybrid semantic + FTS5 lexical) and Knowledge Search (graph traversal).

**Tests first:**
- `test_search/test_doc_search.py` — semantic finds similar; keyword finds exact; hybrid merges+dedupes+ranks; pagination works
- `test_search/test_knowledge_search.py` — edges by engram; intersection of two engrams; filter by predicate; n-hop neighborhood

**Build:** `search/doc_search.py`, `search/knowledge_search.py`

---

### Phase 9 — Backend API Layer

**Goal:** FastAPI endpoints exposing all functionality.

**API contract:**
```
POST   /api/documents/scribbles       → Document
POST   /api/documents/files           → Document (multipart)
GET    /api/documents                 → PaginatedList[Document]
GET    /api/documents/{id}            → DocumentDetail (with engrams)
GET    /api/engrams                   → PaginatedList[Engram]
GET    /api/engrams/{id}              → EngramDetail (with edges, docs)
GET    /api/engrams/{id}/cluster      → list[Document]
GET    /api/search/documents?q=       → list[ScoredDocument]
GET    /api/search/knowledge?q=       → list[Edge]
GET    /api/viz/projections           → list[ProjectionPoint]
GET    /api/viz/clusters              → list[Cluster]
GET    /api/viz/gaps                  → list[GapRegion]
POST   /api/feeds                     → FeedSource
GET    /api/feeds                     → list[FeedSource]
PATCH  /api/feeds/{id}                → FeedSource
DELETE /api/feeds/{id}                → 204
```

**Tests first** (`test_api/`): One test file per router — correct status codes, response shapes, error cases. All use `httpx.AsyncClient` with mock LLM/embeddings via FastAPI dependency override.

**Build:** `api/*.py`, finalize `main.py` (routers, lifespan, dependency injection)

---

### Phase 10 — Visualization Pipeline (parallelizable with P6, P8)

**Goal:** UMAP projection, HDBSCAN clustering, gap detection.

**Tests first** (`test_visualization/test_projection.py`):
- UMAP returns 2D; handles < 5 engrams gracefully; clustering assigns labels; gaps found between dense clusters; results stored in `projections` table; reproducible with fixed seed

**Build:** `visualization/projection.py` — UMAP + HDBSCAN + density-based gap detection

---

### Phases 11–14 — Frontend (sequential)

**P11 — Core Layout + Chronological Stream:**
Tests: API client deserialization, ScribbleInput submit/clear, DocumentCard rendering, useDocuments hook, Playwright e2e for landing page.
Build: `app/page.tsx`, `ScribbleInput`, `DocumentCard`, `FileDropZone`, `useDocuments`, `lib/api.ts`

**P12 — Document Detail + Actor-Network View:**
Tests: NetworkPanel renders engram badges + edge labels, click navigation, Playwright e2e.
Build: `app/documents/[id]/page.tsx`, `NetworkPanel`, `EngramBadge`, `useEngrams`

**P13 — Search + Engram Cluster Views:**
Tests: SearchBar mode toggle, doc/knowledge results rendering, Playwright e2e.
Build: `app/search/page.tsx`, `app/engrams/[id]/page.tsx`, `SearchBar`, `useSearch`

**P14 — Visualization Canvas:**
Tests: Canvas renders points colored by cluster, gap regions highlighted, click tooltip, Playwright zoom/pan.
Build: `app/viz/page.tsx`, `VizCanvas` (d3 or canvas2d — start 2D, not Three.js)

---

### Phase 15 — Deployment + Integration

**Goal:** Startup scripts, end-to-end smoke tests.

**Tests first** (`test_integration/test_full_pipeline.py`):
- Scribble → engrams → edges; two related docs create edges; file upload → engrams; search returns results after ingestion; projections computed

**Build:** `start-web.sh` (uvicorn localhost + next dev + browser open), `start-server.sh` (bind 0.0.0.0/Tailscale + next start)

---

## Verification

After each phase, run:
- **Backend:** `cd backend && uv run pytest tests/test_<phase>/ -v`
- **Frontend:** `cd frontend && npm test` (vitest) and `npx playwright test` (e2e)
- **Full suite:** `cd backend && uv run pytest` — all prior phases' tests must stay green (regression)

Final integration: `./start-web.sh`, create a scribble, verify engrams appear, search returns it, visualization canvas renders.
