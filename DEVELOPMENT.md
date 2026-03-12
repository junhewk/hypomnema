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
| P4 — Entity Extraction | Done | 46 backend (172 pass, 1 skip total) | Multi-tier engram dedup, LLM extraction, atomic pipeline |
| P5 — Edge Generation | Done | 28 backend (200 pass, 1 skip total) | Top-K neighbor retrieval, 12-predicate vocabulary, batched KNN, idempotent edges |
| P6 — Triage | Done | 20 backend (220 pass, 1 skip total) | Embedding-based bouncer, bootstrap auto-accept, document_embeddings storage, pipeline triaged!=-1 filter |
| P7 — Feeds + Scheduler | Done | 52 backend (272 pass, 1 skip total) | RSS/scrape/YouTube fetchers, FetchedItem dataclass, feed source CRUD, APScheduler 3.x cron, batched source_uri dedup |
| P8 — Search | Done | 40 backend (312 pass, 1 skip total) | Hybrid doc search (FTS5 + semantic + RRF fusion), knowledge graph BFS neighborhood, edge queries by engram/predicate/pair |
| P9 — API Layer | Done | 36 backend (348 pass, 1 skip total) | FastAPI app factory, lifespan DI, CORS, all routers, background ontology pipeline, batch edge query for knowledge search |
| P10 — Viz Pipeline | Done | 23 backend (371 pass, 1 skip total) | 3D UMAP projection, HDBSCAN clustering, gap detection |
| P11 — Frontend: Stream | Done | 37 frontend (45 total) + 3 e2e | ScribbleInput, FileDropZone, DocumentCard, useDocuments hook, StreamPage, Playwright e2e |
| P12 — Frontend: Doc Detail | Done | 33 frontend (78 total) + 6 e2e | DocumentDetailPage, NetworkPanel, EngramBadge, useDocument, useEngrams hooks |
| P13 — Frontend: Search + Engrams | Done | 29 frontend (107 total) + 12 e2e | SearchPage, SearchBar, EngramDetailPage, useSearch, useEngram hooks, shared resolveEngram + mockResponse helpers |
| P14 — Frontend: Viz Canvas | Not started | — | |
| P15 — Deployment | Not started | — | |

### Implementation Notes (P0+P1+P2+P3+P4)

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
- **Multi-tier engram dedup:** 3-tier approach inspired by `email-bot/kgengram.py`: (1) exact canonical_name match, (2) cosine similarity via sqlite-vec KNN (threshold 0.92, auto-merge), (3) concept hash as belt-and-suspenders UNIQUE safeguard. LLM verification for ambiguous range (0.80–0.92) deferred to future phase.
- **Cosine from L2 distance:** sqlite-vec returns L2 distance; unit-normalized embeddings allow conversion via `cosine_sim = 1 - (l2² / 2)`. Threshold 0.92 corresponds to L2 ≈ 0.40.
- **Cursor lifecycle with aiosqlite:** `RETURNING *` and `SELECT` cursors must be explicitly closed (`await cursor.close()`) before `db.commit()` to avoid `OperationalError: cannot commit transaction - SQL statements in progress`. Existing ingestion code (scribble.py, file_parser.py) avoids this by fetching before committing without intermediate queries; ontology code requires explicit closes due to multi-query-then-commit patterns.
- **Embedding binary serialization:** `np.asarray(embedding, dtype="<f4").tobytes()` — explicit little-endian float32, direct memory copy (no intermediate Python list). Same binary format as `struct.pack("<Nf", ...)` but faster.
- **Atomic per-document processing:** Single `db.commit()` after all engrams created + document marked `processed=1`. If LLM fails mid-extraction, document stays `processed=0` for retry. Empty documents (no extractable entities) still get `processed=1`.
- **Synonym resolution:** Two-step normalization: sync `normalize()` (lowercase, strip, collapse whitespace, strip trailing punctuation) always applied; async `resolve_synonyms()` uses LLM to merge synonyms within a single extraction batch. Cross-document dedup handled by embedding cosine similarity in `get_or_create_engram`.
- **Text truncation:** Extractor truncates input to 12000 chars (configurable) to protect against context window overflow.
- **Edge generation separated from extraction:** `ontology/linker.py` owns neighbor retrieval, predicate assignment, and edge creation. Pipeline orchestrates. This keeps phases testable and allows re-running edge generation independently.
- **Controlled predicate vocabulary:** 12 predicates in `VALID_PREDICATES` frozenset. LLM system prompt generated from the constant to avoid drift. Invalid predicates silently dropped.
- **Top-K neighbor retrieval:** `find_neighbors()` uses sqlite-vec KNN with batched engram fetch (single `SELECT ... WHERE id IN (...)` instead of N+1). Returns `(Engram, cosine_similarity)` tuples.
- **`ProposedEdge` dataclass:** Frozen intermediate representation between LLM output and DB insert. Pipeline attaches `source_document_id` via `dataclasses.replace()`.
- **`processed=1→2` transition:** `link_document()` only processes `processed=1` docs. Sets `processed=2` after edge generation. No `EmbeddingModel` needed — embeddings already stored from Phase 4.
- **Document fetch helper:** `_fetch_document()` shared by `process_document()` and `link_document()` to avoid duplicated fetch-or-raise logic.
- **Triage compares against engram embeddings:** `triage_document()` embeds the document text and queries Top-1 KNN against `engram_embeddings` (not `document_embeddings`). Checks relevance to *concepts we already know about*.
- **Bootstrap auto-accept:** If `SELECT COUNT(*) FROM engrams` returns 0, all documents are accepted to seed the knowledge graph.
- **Document embeddings stored regardless of outcome:** Both accepted and rejected documents get their embedding stored in `document_embeddings` via `INSERT OR IGNORE`. Supports future document-level semantic search (Phase 8).
- **Manual docs bypass triage:** Scribbles and file uploads keep `triaged=0` (default). Pipeline filter uses `triaged != -1`, so `triaged=0` passes through. Only feed documents (Phase 7) will call `triage_document()`.
- **`triage_pending_documents` source_type filter:** Defaults to `source_type="feed"` to only triage automated feed docs. Pass `None` to triage everything (useful in tests). Query built with conditional clause appending.
- **Triage is embeddings-only, no LLM:** The whole point is a cheap filter — embedding similarity avoids expensive LLM calls on irrelevant content.
- **Silent skip on re-triage:** Returns existing decision if `triaged != 0`, matching the pattern of `process_document()` which returns `[]` if already processed.
- **Three sync fetchers, one async orchestrator:** `fetch_rss()`, `fetch_scrape()`, `fetch_youtube()` are sync (feedparser/httpx.Client/youtube-transcript-api are sync libraries). `poll_feed()` wraps fetcher calls in `asyncio.to_thread()` to avoid blocking the event loop.
- **`FetchedItem` dataclass:** Frozen intermediate representation between fetcher output and DB insert. Mirrors `ParsedFile` from file_parser.py.
- **Batched source_uri dedup:** `ingest_feed_items()` fetches all existing `source_uri` values in a single `SELECT ... WHERE source_uri IN (...)` query, then filters in-memory before inserting. Avoids N+1 pattern.
- **Fetcher dispatch via `_FETCHERS` dict:** Direct function references (matching `file_parser.py`'s `_PARSERS` pattern). Tests use `monkeypatch.setitem()` on the dict.
- **Feed source CRUD in feeds.py:** `create_feed_source()`, `list_feed_sources()`, `update_feed_source()`, `delete_feed_source()` — all use `RETURNING *` pattern. Tight coupling with feed domain, small surface area.
- **Separation: feeds.py creates documents, scheduler orchestrates triage:** `poll_feed()` only fetches + inserts documents with `source_type='feed'`, `triaged=0`. The scheduler job calls `poll_feed()` then `triage_pending_documents()`.
- **`FeedScheduler` wraps APScheduler 3.x `AsyncIOScheduler`:** Each job opens its own DB connection via `connect()` to avoid sharing aiosqlite connections. Re-fetches feed source on each run to check if deactivated since scheduling.
- **APScheduler 3.x async quirk:** `AsyncIOScheduler.shutdown()` defers state transition to the event loop. Tests use `await asyncio.sleep(0)` after shutdown to let the state update propagate.
- **HTML parsing:** Simple regex `_strip_html()` and `_extract_html_title()`. `fetch_scrape()` extracts title before stripping to avoid double-parsing the HTML.
- **YouTube URL handling:** `extract_video_id()` supports `youtu.be/ID`, `youtube.com/watch?v=ID`, `youtube.com/embed/ID`. Channel feeds parse RSS then fetch transcripts per video, with individual failures logged and skipped.
- **mypy overrides:** `feedparser` (no py.typed, `follow_imports = "skip"`) and `apscheduler.*` (no stubs) added to pyproject.toml.
- **`ScoredDocument` is a frozen dataclass, not Pydantic:** Internal search result container — API serialization deferred to Phase 9.
- **FTS5 query sanitization:** Strips metacharacters (`"*():^`) and boolean operators (`AND/OR/NOT/NEAR`) then wraps each token in quotes to prevent FTS5 syntax errors from user input.
- **Hybrid search via RRF:** Reciprocal Rank Fusion with k=60. `list_count` dict tracks how many result lists each doc appears in during the scoring pass for O(1) match_type detection (avoids O(n*m) re-scan).
- **Sequential async search:** `keyword_search` and `semantic_search` run sequentially despite both being async — aiosqlite connections are not concurrency-safe.
- **BFS edge dedup via dict accumulation:** `get_neighborhood()` stores edges in `dict[str, Edge]` keyed by edge ID during traversal, deduplicating inline rather than post-hoc.
- **SQL operator precedence in BFS:** Edge query wraps `OR` clause in parens: `(source IN (...) OR target IN (...)) AND predicate = ?` — without parens, `AND` binds tighter than `OR`.
- **Edges are undirected for traversal:** `get_edges_for_engram()` and `get_neighborhood()` follow edges in both directions. `get_edges_between()` checks both `(A→B)` and `(B→A)`.
- **`DocumentOut` overrides metadata serializer:** `Document.serialize_metadata` returns JSON string for DB storage; `DocumentOut` overrides to return dict as-is for API responses. Uses `# type: ignore[override]` since return type intentionally differs.
- **`ScoredDocumentOut` flattening:** Backend `ScoredDocument` dataclass nests `document: Document`. Route handler flattens via `{**result.document.model_dump(mode="python"), "score": result.score}`.
- **Background ontology pipeline:** `_run_ontology_pipeline()` opens its own DB connection via `connect()` to avoid sharing the request-path aiosqlite connection. LLM/embeddings objects are stateless, safe to share.
- **`create_app` factory with `use_lifespan` flag:** Tests pass `use_lifespan=False` and manually set `app.state.*` to avoid starting the real scheduler or loading GPU models.
- **Knowledge search batch query:** `search_knowledge_endpoint` fetches matching engram IDs with `SELECT id` then retrieves all edges in a single `IN (...)` query (avoids N+1). Results capped at 100 edges, matching the predicate fallback path.
- **Feed update 404 detection:** Explicit existence check before `update_feed_source()` rather than string-matching on ValueError messages. Avoids fragile coupling to error message text.
- **`document_engrams` index:** Added `idx_document_engrams_engram` on `document_engrams(engram_id)` — the composite PK `(document_id, engram_id)` cannot serve queries filtering by `engram_id` first.
- **Viz endpoints are stubs:** Return empty lists; Phase 10 fills in the UMAP/clustering pipeline.
- **CORS:** Allows `localhost:3000` and `127.0.0.1:3000` for frontend dev.
- **Single client boundary:** `app/page.tsx` is a server component rendering `<StreamPage />` (client). All interactive pieces live under this one `"use client"` boundary — no benefit to server-rendering when data comes from the local backend via client-side fetch.
- **No state library:** React 19 hooks suffice. `useDocuments` is ~100 lines with polling. A library can be introduced if patterns repeat.
- **Dark mode via `prefers-color-scheme`:** CSS custom properties (`--surface`, `--border`, `--muted`, `--accent`, source-type colors) in `globals.css` respond to the media query. No class-based toggle.
- **Dot-grid background:** Faint `radial-gradient` pattern evokes the knowledge graph. Uses `color-mix()` for theme-adaptive opacity.
- **DocumentCard memoized:** `React.memo()` prevents re-renders during polling when document data hasn't changed.
- **Polling change detection:** `useDocuments` compares IDs and `processed` status before replacing state — returns same reference on no-op polls to avoid cascading re-renders.
- **Textarea auto-resize via rAF:** `requestAnimationFrame` batches the height read/write to avoid forced reflow on every keystroke.
- **Processing status as dot:** Documents have `processed: 0|1|2`. Small colored dot (amber/blue/green) with CSS pulse animation for in-progress states.
- **Source-type left border:** DocumentCard uses a colored left border (blue=scribble, purple=file, amber=feed) via CSS variables instead of inline Tailwind color classes.
- **Shared test factory:** `__tests__/helpers/makeDocument.ts` exports `makeDoc()` and `makeDocs()` used across all component/hook test files.
- **`SOURCE_STYLES` typed with `SourceType`:** Record key uses the union type from `types.ts` for compile-time exhaustiveness.
- **NetworkPanel reused across pages:** `DocumentDetailPage` and `EngramDetailPage` both render `NetworkPanel` with the same props interface (`documentEngramIds`, `engramDetails`, `isLoading`). The singleton Set trick highlights "this page's engrams" at full opacity while dimming neighbors.
- **`resolveEngram` shared utility:** Extracted to `lib/resolveEngram.ts` — both `NetworkPanel` and `SearchPage` need the same fallback logic (truncated ID when engram details aren't loaded yet). Avoids copy-paste.
- **Search hook debounce:** `useSearch` uses a 300ms `setTimeout` debounce with `useRef` timer + `activeRequestRef` race guard. Sets `isLoading=true` immediately (before debounce fires) for responsive "Searching…" feedback.
- **URL sync via `replaceState`:** SearchPage syncs `q` and `mode` to URL params on every change. No debounce needed — `replaceState` is near-free and ensures shareable URLs.
- **`useSearchParams` requires Suspense:** Next.js App Router mandates a `<Suspense>` boundary around components using `useSearchParams()`. Search route wraps `<SearchPage>` accordingly.
- **Engram detail page structure:** `EngramDetailPage` fetches engram + cluster docs via `useEngram`, then neighbor details via `useEngrams`. Teal left border (`var(--engram)`) provides visual continuity with `EngramBadge`.
- **Score badge uses accent color:** `DocumentCard` detects `ScoredDocument` via `"score" in doc` and renders an amber accent pill (`var(--accent)`) to distinguish relevance scores from timestamps.
- **Shared test helpers:** `__tests__/helpers/mockResponse.ts` exports `mockJsonResponse()` and `mockErrorResponse()` used across all hook/component tests. `makeEngram.ts` exports factories for `Engram`, `Edge`, `EngramDetail`, `DocumentDetail`.
- **Next.js 16 async params:** `app/engrams/[id]/page.tsx` uses `params: Promise<{ id: string }>` with `await params` — required pattern for dynamic route params in Next.js 16.

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
