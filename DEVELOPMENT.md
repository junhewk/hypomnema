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
| P14 — Frontend: Viz Canvas | Done | 19 frontend (127 total) + 16 e2e + 1 backend (349 total) | R3F + drei, GL points/lines, orbit controls, fog, cluster labels, hover tooltip |
| P15 — CLI + Integration | Done | 7 backend (377 pass, 1 skip total) | CLI entry point, dynamic CORS, integration tests |
| P16 — Multi-Provider + Settings | Done | 36 backend (413 pass, 1 skip total) | OpenAI + Ollama LLM, OpenAI + Google embeddings, settings API, hot-swap, Fernet encryption, settings UI |
| P17 — UX Overhaul | Done | 6 backend + 0 frontend (419 pass, 1 skip total; 127 frontend) | Sidebar nav, editable documents with draft auto-save, viz minimap, LayoutShell |
| P18 — Tauri Desktop Packaging | Done | 0 new tests (scaffolding only) | Health endpoint, static file serving, desktop config mode, Tauri sidecar, PyInstaller spec |
| P19 — Viz Overhaul | Done | 0 new (updated 1 existing) | Constellation nodes, PageRank sizing, GLSL shader cleanup, radial reveal, auto-orbit, collapsible sidebar |

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
- **Multi-tier engram dedup:** Production path is now: (1) exact `canonical_name`, (2) direct alias-index lookup via persisted `engram_aliases`, (3) lexical alias overlap on sqlite-vec KNN candidates, (4) cosine similarity via sqlite-vec KNN (threshold `0.91`, `k=10`), (5) concept hash as a UNIQUE-safety fallback. Persisted alias keys include conservative normalization plus English gloss extraction for `한글명 (latin gloss)` and Korean legal shortforms such as `생명윤리및안전에관한법률 → 생명윤리법`. Eval-only labels remain `baseline`, `adjusted`, and `hardened`; in product docs and code discussion, refer to the production behavior as `engram dedupe` or `alias-index dedupe`.
- **Cosine from L2 distance:** sqlite-vec returns L2 distance; unit-normalized embeddings allow conversion via `cosine_sim = 1 - (l2² / 2)`. Production threshold `0.91` corresponds to L2 ≈ `0.424`; eval baseline threshold `0.92` corresponds to L2 ≈ `0.40`.
- **Cursor lifecycle with aiosqlite:** `RETURNING *` and `SELECT` cursors must be explicitly closed (`await cursor.close()`) before `db.commit()` to avoid `OperationalError: cannot commit transaction - SQL statements in progress`. Existing ingestion code (scribble.py, file_parser.py) avoids this by fetching before committing without intermediate queries; ontology code requires explicit closes due to multi-query-then-commit patterns.
- **Embedding binary serialization:** `np.asarray(embedding, dtype="<f4").tobytes()` — explicit little-endian float32, direct memory copy (no intermediate Python list). Same binary format as `struct.pack("<Nf", ...)` but faster.
- **Atomic per-document processing:** Single `db.commit()` after all engrams created + document marked `processed=1`. If LLM fails mid-extraction, document stays `processed=0` for retry. Empty documents (no extractable entities) still get `processed=1`.
- **Synonym resolution:** Two-step normalization: sync `normalize()` (lowercase, strip, collapse whitespace, strip trailing punctuation) always applied; async `resolve_synonyms()` uses LLM to merge synonyms within a single extraction batch. Cross-document dedup is handled by persisted alias lookup plus embedding-based matching in `get_or_create_engram`.
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
- **React Three Fiber + drei for 3D viz:** R3F v9 gives declarative React API over Three.js. `drei` provides `OrbitControls` (camera) and `Html` (tooltip/label overlays). `next/dynamic` with `ssr: false` on a `"use client"` page avoids SSR issues with WebGL — Next.js 16 disallows `ssr: false` in Server Components.
- **GL primitives, not meshes:** Engrams rendered as `THREE.Points` (GPU point sprites), edges as `THREE.LineSegments`. Two draw calls total. `sizeAttenuation={false}` keeps points constant screen-size regardless of zoom.
- **`VizEdge` as `Pick<Edge, ...>`:** Lightweight projection of the full `Edge` type — avoids duplicate interface while selecting only the 4 fields needed for visualization.
- **`load_edges()` in projection module:** Backend edge query extracted to `visualization/projection.py` alongside `load_projections`/`load_clusters`/`load_gaps`. Selects only needed columns (`source_engram_id`, `target_engram_id`, `predicate`, `confidence`) with `VizEdge` response schema. Limit 5000 prevents unbounded queries.
- **Pre-allocated edge buffer:** `buildEdgeBuffer` two-pass approach: count valid edges first, then fill a pre-allocated `Float32Array` directly — avoids dynamic `number[]` growth + conversion copy.
- **Cluster lookup via Map:** `clusterMap` built once via `useMemo` when clusters change. Tooltip `clusterLabel` derivation uses O(1) Map lookup instead of O(N) `clusters.find()` — important since `handlePointerMove` fires on every mouse movement.
- **Golden-angle HSL cluster palette:** `clusterColor(id)` uses `hue = (id * 137.508) % 360` with `s=70%, l=60%` for luminous colors on the dark viewport. Noise points (`cluster_id` null or -1) get muted gray matching `--muted`.
- **Atmospheric dark viewport:** Viz page uses dedicated `#08080a` background with faint teal/amber radial gradients, scene fog for depth perception, and `depthWrite: false` on transparent primitives to prevent z-fighting.
- **Glass morphism overlays:** Nav pills, tooltip, and cluster labels use `backdrop-filter: blur()` with semi-transparent backgrounds via `color-mix()` — bridges HTML overlays into the 3D space visually.
- **Raycaster threshold:** `Points: { threshold: 0.3 }` provides reasonable hit detection for point sprites. Cast as `unknown as RaycasterParameters` due to R3F typing gap — only `RaycasterParameters` type imported (not `import * as THREE`).

### Implementation Notes (P16)

- **Fernet key auto-generation:** `crypto.get_or_create_key()` creates `{data_dir}/.hypomnema_key` with `0o600` permissions on first run. Key persists across restarts; API keys encrypted at rest in the `settings` table.
- **Settings table is key-value:** `settings(key TEXT PK, value TEXT, encrypted INTEGER, updated_at TEXT)`. Encrypted values stored as Fernet ciphertext; `get_all_settings_masked()` returns masked values (last 4 chars) without needing the Fernet key.
- **Embedding provider fixed at startup:** `HYPOMNEMA_EMBEDDING_PROVIDER` env var selects `local`/`openai`/`google`. Settings UI displays as read-only. Different embedding models produce incompatible vectors — changing requires a fresh database.
- **LLM hot-swap:** `PUT /api/settings` acquires `app.state.llm_lock` (asyncio.Lock), calls `build_llm()` factory, replaces `app.state.llm` in-place. No restart needed. The lock prevents mid-request replacement.
- **DB settings override env vars for LLM fields only:** `Settings.with_db_overrides()` merges DB settings into env-based Settings, but only for `_LLM_OVERRIDABLE` fields (provider, model, API keys, base URLs). Embedding, host, port, db_path stay from env.
- **`_LLM_OVERRIDABLE` is module-level:** Pydantic treats `_`-prefixed class attributes as `ModelPrivateAttr`, breaking `in` operator. Moved to module scope.
- **`model_construct()` skips validation:** `with_db_overrides` uses `model_construct()` to avoid re-running validators (e.g., `set_host_for_mode`) on reconstructed Settings. Safe because values come from validated env + user DB input.
- **Ollama uses httpx directly:** `POST /api/generate` with `stream: false`. No `ollama` Python package dependency. httpx already a project dependency.
- **OpenAI `base_url` exposed:** Allows pointing at Together, Groq, vLLM, or any OpenAI-compatible API. Empty string = default OpenAI endpoint.
- **Mock providers excluded from `/api/settings/providers`:** Mock LLM/embeddings remain for testing only — not user-facing in the settings UI or provider lists.
- **Dirty-field tracking in settings UI:** Frontend tracks which fields the user actually modified. Untouched API key fields (showing masked values) are not sent in PUT, preventing overwrite of stored keys with masked strings.
- **Provider cards instead of dropdown:** Settings UI uses stacked `border-l-2` cards matching the DocumentCard pattern, with active provider indicated by amber accent border + green status dot.
- **New dependencies:** `cryptography>=44,<45` (Fernet), `openai>=1.60,<2` (OpenAI LLM + embeddings). Both added to pyproject.toml with mypy overrides for missing stubs.
- **Existing test updated:** `test_config.py::test_invalid_llm_provider_rejected` was using `"openai"` as invalid provider — updated to `"nonexistent"` since OpenAI is now valid.

### Implementation Notes (P17+P18)

- **LayoutShell wraps all pages:** `LayoutShell` component provides a single `VizDataProvider` wrapping with conditional layout — sidebar + main for normal pages, full-screen passthrough for `/viz`. Avoids duplicate providers and context loss on navigation.
- **Sidebar component:** Persistent left sidebar (`w-56`, `bg-surface`) with logo, nav items (Stream, Search, Settings), viz minimap, and full viz link. `NavItem` extracted as shared component used by both main nav and viz link.
- **Sidebar active indicator:** CSS `::before` pseudo-element with `var(--accent)` left border, height animated on active/hover states via `data-active` attribute.
- **VizMinimap performance:** Uses R3F `frameloop="demand"` with a `SlowTicker` component that calls `invalidate()` at 10fps via `setInterval`. `IntersectionObserver` defers Canvas mounting until the minimap is in viewport. No continuous 60fps loop.
- **VizDataProvider context:** `useVizDataContext.tsx` wraps `useVizData()` in React Context. `useVizDataCtx()` throws if used outside provider (no conditional hook fallback — React Rules of Hooks). Both minimap and full viz share the same fetched data.
- **Editable documents:** `PATCH /api/documents/{id}` endpoint updates text/title, resets `processed=0`, cleans up `document_engrams`, `document_embeddings`, and `edges WHERE source_document_id = id`, then re-runs ontology pipeline in background. Uses `UPDATE ... RETURNING *` to avoid redundant re-SELECT.
- **DocumentUpdate schema:** `text: str | None = None`, `title: str | None = None`. Rejects empty body (both None).
- **ScribbleInput edit mode:** `editingDocument` prop pre-fills title/text, changes button to "Save & Reprocess", shows cancel button. Calls `api.updateDocument()` instead of `api.createScribble()`.
- **Draft auto-save:** `localStorage` persistence with 500ms debounce. Restores on mount, clears on successful save. Subtle "draft saved"/"draft restored" animation via `.draft-status` CSS class.
- **"Continue" button on DocumentCard:** Visible on hover for scribble-type documents. Uses `.continue-btn` CSS class with fade-in transition and `::before` arrow prefix.
- **Editor surface styling:** `.editor-surface` class with gradient background and `::before` left-margin line that fades in on `:focus-within` — manuscript editing feel.
- **Per-page nav removed:** All inline `← back` links and pill-style nav headers stripped from StreamPage, SearchPage, DocumentDetailPage, EngramDetailPage, SettingsPage. VizPage keeps full-screen canvas, nav pills removed.
- **Health endpoint:** `GET /api/health` → `{"status": "ok"}` — used by Tauri sidecar to poll backend readiness.
- **Static file serving:** `main.py` mounts `StaticFiles(directory=settings.static_dir, html=True)` at `/` when `static_dir` is set. API routes take precedence (registered first).
- **Desktop config mode:** `mode: Literal["local", "server", "desktop"]`. Desktop forces `host = "127.0.0.1"`, defaults `db_path` to `platformdirs.user_data_dir("hypomnema")`.
- **LocalEmbeddingModel guarded import:** `main.py` wraps import in try/except ImportError, falls back to MockEmbeddingModel. Allows cloud-only builds (no torch/transformers).
- **Next.js static export:** `next.config.ts` adds `output: process.env.NEXT_EXPORT === "1" ? "export" : undefined`. Normal dev/build workflow unaffected.
- **Desktop entry point:** `desktop.py` resolves paths for both PyInstaller frozen bundles and dev layout, parses `--port`, runs uvicorn.
- **Tauri v2 sidecar pattern:** `desktop/src-tauri/src/lib.rs` spawns PyInstaller'd backend, polls `GET /api/health` until ready, redirects window to `http://127.0.0.1:<port>`.
- **PyInstaller spec:** Cloud-only profile excludes `torch`, `transformers`, `sentence-transformers`. Includes `sqlite_vec` via custom hook.

---

## Project Structure

```
hypomnema/
├── backend/
│   ├── pyproject.toml                    # uv-managed
│   ├── src/hypomnema/
│   │   ├── main.py                       # FastAPI app factory + lifespan
│   │   ├── config.py                     # Pydantic Settings
│   │   ├── crypto.py                     # Fernet encryption for API keys at rest
│   │   ├── db/
│   │   │   ├── engine.py                 # get_db(), PRAGMAs, sqlite-vec loading
│   │   │   ├── schema.py                 # CREATE TABLE/VIRTUAL TABLE, FTS5
│   │   │   ├── models.py                 # Pydantic models
│   │   │   └── settings_store.py         # Key-value settings CRUD with encryption
│   │   ├── llm/
│   │   │   ├── base.py                   # LLMClient Protocol
│   │   │   ├── claude.py                 # Anthropic implementation
│   │   │   ├── google.py                 # Gemini implementation
│   │   │   ├── openai.py                 # OpenAI implementation (supports base_url)
│   │   │   ├── ollama.py                 # Ollama REST API implementation
│   │   │   ├── factory.py                # build_llm() factory for lifespan + hot-swap
│   │   │   └── mock.py                   # Deterministic mock for tests
│   │   ├── embeddings/
│   │   │   ├── base.py                   # EmbeddingModel Protocol
│   │   │   ├── local_gpu.py              # sentence-transformers
│   │   │   ├── openai.py                 # OpenAI embeddings
│   │   │   ├── google.py                 # Google embeddings
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
│   │       ├── documents.py              # CRUD + PATCH edit with re-processing
│   │       ├── engrams.py
│   │       ├── search.py
│   │       ├── visualization.py
│   │       ├── feeds.py
│   │       ├── health.py                 # GET /api/health (desktop sidecar polling)
│   │       └── settings.py              # Settings API + LLM hot-swap
│   └── tests/
│       ├── conftest.py                   # Shared fixtures: tmp_db, mock_llm, mock_embeddings
│       ├── fixtures/                     # sample.pdf, sample.docx, sample.md
│       └── test_*/                       # Mirror of src/ structure
├── frontend/
│   ├── package.json                      # Next.js 16+, vitest, playwright, tailwind
│   ├── src/
│   │   ├── app/                          # App Router pages
│   │   ├── components/                   # Sidebar, LayoutShell, VizMinimap, ScribbleInput, DocumentCard, etc.
│   │   ├── lib/api.ts                    # Typed fetch wrapper
│   │   ├── lib/types.ts                  # TS types matching backend models
│   │   ├── lib/vizTransforms.ts          # Shared buffer builders for viz (points, edges, colors)
│   │   └── hooks/                        # useDocuments, useEngrams, useSearch, useSettings, useVizDataContext
│   ├── __tests__/
│   └── e2e/
├── desktop/
│   ├── src-tauri/                        # Tauri v2 app (Rust)
│   │   ├── Cargo.toml
│   │   ├── tauri.conf.json
│   │   ├── src/lib.rs                    # Sidecar spawn, health poll, window redirect
│   │   └── capabilities/default.json
│   └── packaging/
│       ├── build.py                      # Orchestrates: next export → pyinstaller → tauri build
│       ├── hypomnema.spec                # PyInstaller spec (cloud-only, no torch)
│       └── hooks/hook-sqlite_vec.py      # PyInstaller hook for sqlite_vec
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
    concept_hash TEXT NOT NULL UNIQUE,     -- sign-hash fallback safeguard
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE engram_aliases (
    engram_id TEXT NOT NULL REFERENCES engrams(id) ON DELETE CASCADE,
    alias_key TEXT NOT NULL,
    alias_kind TEXT NOT NULL,
    PRIMARY KEY (engram_id, alias_key)
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

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    encrypted INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
```

---

## Key Architectural Decisions

**LLM Abstraction:** `Protocol`-based — `LLMClient` with `complete()` and `complete_json()`. Implementations: Claude (anthropic SDK), Google (google-genai SDK), OpenAI (openai SDK, supports custom base_url), Ollama (httpx REST client), Mock (deterministic, canned responses keyed by input substring). `build_llm()` factory in `llm/factory.py` used by both lifespan and settings hot-swap.

**Embedding Abstraction:** `EmbeddingModel` Protocol with `dimension` property and `embed(texts)`. Implementations: Local (sentence-transformers), OpenAI (openai SDK), Google (google-genai SDK), Mock (hash-seeded PRNG). Embedding provider is fixed at startup via env var — different models produce incompatible vectors.

**API Key Encryption:** Fernet symmetric encryption with auto-generated keyfile at `{data_dir}/.hypomnema_key`. API keys encrypted before DB storage, decrypted on read, masked in API responses. Settings stored in `settings` key-value table.

**LLM Hot-Swap:** Settings API acquires `asyncio.Lock`, builds new LLM client via factory, replaces `app.state.llm` in-place. No restart needed. DB settings override env vars for LLM-related fields only.

**Engram Dedupe:** Exact name first, then persisted alias-index lookup (`engram_aliases`), then KNN alias overlap, then vector threshold, then concept-hash fallback. Alias rows are backfilled during schema creation so older DBs gain direct alias lookup without a separate migration step.

**Concept Hash (fallback safeguard):** Binarize embedding by sign → SHA-256 hash the bit-string. Similar embeddings can collide, so this is no longer treated as the primary dedupe mechanism; it is the last safety net after lexical and vector checks.

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
         └─ P16 (Multi-Provider + Settings)
             └─ P17 (UX Overhaul — Sidebar, Edit, Minimap)
                 └─ P18 (Tauri Desktop Packaging)
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

**Goal:** LLM extracts entities → normalize → embed → alias/vector dedup → store Engrams.

**Tests first:**
- `test_ontology/test_extractor.py` — mock LLM returns entity list; empty text → empty list; JSON parsing correct
- `test_ontology/test_normalizer.py` — whitespace stripped; lowercased; LLM maps synonyms to same canonical form
- `test_ontology/test_engram.py` — alias keys generated correctly; direct alias lookup works for bilingual/legal variants; concept hash deterministic; new concept creates engram + embedding row; duplicate returns existing; `document_engrams` junction created
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

### Phase 16 — Multi-Provider Support + Settings UI

**Goal:** OpenAI and Ollama LLM providers, OpenAI and Google embedding providers, settings API with encrypted API key storage, frontend settings page with LLM hot-swap.

**Tests first:**
- `test_crypto.py` — key creation, roundtrip encrypt/decrypt, wrong key raises, masking
- `test_db/test_settings_store.py` — plaintext/encrypted CRUD, upsert, masked retrieval
- `test_llm/test_openai.py` — protocol compliance, API call mocking, JSON parsing
- `test_llm/test_ollama.py` — protocol compliance, REST call mocking, JSON parsing
- `test_embeddings/test_openai_embed.py` — protocol, dimension, normalized output
- `test_embeddings/test_google_embed.py` — protocol, dimension, normalized output
- `test_api/test_settings.py` — masked GET, provider update, key encryption, embedding rejection, providers list, hot-swap

**Build:** `crypto.py`, `db/settings_store.py`, `llm/openai.py`, `llm/ollama.py`, `llm/factory.py`, `embeddings/openai.py`, `embeddings/google.py`, `api/settings.py`, expanded `config.py`, updated `main.py` lifespan. Frontend: `SettingsPage`, `useSettings` hook, settings API methods, provider types.

**API additions:**
```
GET    /api/settings                → SettingsResponse (masked keys)
PUT    /api/settings                → SettingsResponse (hot-swaps LLM)
GET    /api/settings/providers      → ProvidersResponse (available providers)
```

### Phase 17 — UX Overhaul: Sidebar Nav, Editable Documents, Viz Minimap

**Goal:** Replace scattered per-page nav with persistent sidebar, add document editing with draft auto-save, embed viz minimap in sidebar.

**Backend:**
- `PATCH /api/documents/{id}` — update text/title, reset processed, clean up old associations, re-run ontology pipeline
- `DocumentUpdate` schema in `api/schemas.py`
- Tests: `test_api/test_documents.py::TestUpdateDocument` — 5 tests

**Frontend:**
- `LayoutShell` — conditional sidebar/fullscreen layout with single `VizDataProvider`
- `Sidebar` — persistent nav with logo, active indicators, minimap
- `VizMinimap` — low-fps R3F canvas with IntersectionObserver lazy loading
- `useVizDataContext` — React Context sharing viz data between minimap and full page
- `ScribbleInput` — 10-row editor, localStorage draft auto-save, edit mode
- `DocumentCard` — "continue" button on hover for scribbles
- All pages: removed inline nav headers/back links
- `api.ts` — `updateDocument()` method

**API addition:**
```
PATCH  /api/documents/{id}          → DocumentOut (edit + reprocess)
```

---

### Phase 18 — Tauri Desktop Packaging

**Goal:** Package as native desktop app via Tauri v2 sidecar pattern.

**Backend changes (benefits both web + desktop):**
- `GET /api/health` endpoint for sidecar polling
- Static file serving via `StaticFiles` mount when `static_dir` is set
- `desktop` config mode (localhost, platformdirs data dir)
- `desktop.py` entry point for PyInstaller sidecar
- Guarded `LocalEmbeddingModel` import for cloud-only builds

**Desktop scaffolding (`desktop/`):**
- Tauri v2 app: sidecar spawn → health poll → window redirect
- PyInstaller spec: cloud-only profile excluding torch
- Build orchestrator: next export → pyinstaller → tauri build

**Frontend change:**
- `next.config.ts` conditional `output: "export"` via `NEXT_EXPORT=1` env var

---

### Phase 19 — Viz Overhaul ("Minority Report" Spatial UX)

**Goal:** Transform visualization from bloated glow nodes into a cinematic constellation display with gestural 3D controls and a collapsible sidebar.

**Viz transforms (`vizTransforms.ts`):**
- `computePageRank()` — power iteration (damping=0.85, 20 iterations) with confidence-weighted edges, returns normalized [0,1] scores
- `buildColorBuffer()` — constellation mode: warm neutral white default, cluster color on focus, `"all"` for minimap
- `buildSizeBuffer()` — PageRank-based sizing: 4px base, 85th percentile threshold scales to 18px
- `buildEdgeColorBuffer()` — per-vertex edge colors with opacity baked in via premultiplied mix toward background (LineBasicMaterial has no per-vertex alpha)
- Named constants: `COLOR_NEUTRAL`, `COLOR_EDGE_DEFAULT`, `COLOR_VIZ_BG`

**VizScene shaders and animation:**
- Crisp fragment shader (core/body/halo smoothstep) replacing 3-layer glow
- `uReveal` uniform — radial reveal animation over ~2s on page load
- `uTime` uniform — 6% ambient breathing oscillation, phase-offset by position.x
- `ShaderAnimator` component (merged RevealAnimator + TimeDriver) — stops reveal after completion
- `AutoOrbitController` — cinematic rotation (speed 0.5), stops on pointerdown/wheel
- Edge vertex colors via `LineBasicMaterial({ vertexColors: true })`

**Collapsible sidebar:**
- `useSidebarContext.tsx` — React context + localStorage persistence (`hypomnema-sidebar-collapsed`)
- `Sidebar.tsx` — lucide-react icons (Rows3, Search, Settings), collapsed `w-14` icon-only / expanded `w-56`
- `LayoutShell.tsx` — always renders sidebar (removed viz passthrough ternary), wraps in `SidebarProvider`
- `MobileNav.tsx` — icons from `NAV_ITEMS`, no collapse on mobile

**VizPage changes:**
- Removed fixed positioning and back button
- Escape only clears focused node (no navigation)
- Auto-orbit state + callbacks passed to VizScene and VizControlsHUD

**HUD relabeling:** spatial language — "orbit" (not "orbit / sweep"), "spread" (not "explode"), "push / pull" (not "yank depth"), auto-orbit toggle button

**Tooltip/card readability:** forced dark-mode CSS (`.viz-tooltip`), increased font sizes (13px name, 11px cluster)

**CSS additions:** `.sidebar-transition`, `.sidebar-label-fade`, `[data-collapsed]` active indicator morphs to centered bottom dot

---

## Distribution Notes (2026-03-14)

This is a policy snapshot, not a permanent truth. Re-check platform docs before shipping a public desktop release.

**Current release posture:**
- Prefer the open-source server/web version on GitHub as the default public distribution path.
- Prioritize Windows desktop distribution before macOS desktop distribution.
- Treat macOS desktop distribution as a later investment once the product and installer flow are stable.

**Windows:**
- Windows does not require an Apple-style annual developer fee for normal direct downloads.
- GitHub Releases with a standard installer is sufficient for the first public Windows release.
- `winget` is optional. It is a package-manager distribution channel, not an approval program and not an app store. Its value is install/upgrade convenience, not trust.
- `winget` does not remove Microsoft Defender SmartScreen warnings by itself.
- Windows code signing is a separate trust step. The practical later-stage path is a standard Authenticode code-signing certificate plus `signtool` with timestamping.
- Microsoft Store is optional. As of this snapshot, individual developer accounts are free and company accounts are approximately USD 99 one time, not annual.
- Practical recommendation: release on GitHub first, skip `winget` unless command-line install/upgrade convenience becomes important, and defer paid code-signing until SmartScreen friction justifies the cost.

**macOS:**
- For broad desktop distribution to normal users, the practical path is Apple Developer Program membership plus signing/notarization.
- Apple Developer Program membership is USD 99 per year as of this snapshot.
- Without signing/notarization, users can still run the app, but the Gatekeeper flow is much worse and requires manual override.
- For Hypomnema, this trust cost is amplified because the desktop app packages a local knowledge tool with file ingestion, API-key handling, and a sidecar backend binary.
- Practical recommendation: do not pay the Apple cost until the macOS desktop release is worth the operational effort.

**Homebrew on macOS:**
- There is no Homebrew accreditation program and no Homebrew fee.
- Official `homebrew/cask` inclusion is possible, but it is not an easy substitute for Apple signing.
- Official casks are expected to run on the latest major macOS and to launch with Gatekeeper enabled. Unsigned apps are a common rejection case.
- Official casks also face notability and maintenance expectations. Homebrew documents example rejection thresholds below roughly `30 forks / 30 watchers / 75 stars`, with higher thresholds for self-submitted projects below roughly `90 / 90 / 225`.
- For an individual developer or early-stage project, official Homebrew listing is therefore possible but relatively hard.
- A personal Homebrew tap is much easier and requires no approval. It is a good option later for power users, but it is not a replacement for signing/notarization if the goal is mainstream macOS installation.

**Resulting strategy for Hypomnema:**
- Public/open-source distribution: GitHub, centered on the server/web version.
- Windows desktop: first desktop target.
- Windows desktop distribution does not require `winget` for the first release.
- macOS desktop: only after there is enough demand to justify Apple membership, notarization, packaging work, and support burden.
- Homebrew: consider a personal tap after a signed macOS build exists; do not rely on official `homebrew/cask` for the first macOS release.

**References:**
- Apple Developer Program: https://developer.apple.com/programs/
- Homebrew Acceptable Casks: https://docs.brew.sh/Acceptable-Casks
- Homebrew Taps: https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap
- WinGet overview: https://learn.microsoft.com/en-us/windows/package-manager/
- SignTool: https://learn.microsoft.com/en-us/windows/win32/seccrypto/using-signtool-to-sign-a-file
- Microsoft Store account FAQ: https://learn.microsoft.com/en-us/windows/apps/publish/faq/open-developer-account

---

## Verification

After each phase, run:
- **Backend:** `cd backend && uv run pytest tests/test_<phase>/ -v`
- **Frontend:** `cd frontend && npm test` (vitest) and `npx playwright test` (e2e)
- **Full suite:** `cd backend && uv run pytest` — all prior phases' tests must stay green (regression)

Final integration: `./start-web.sh`, create a scribble, verify engrams appear, search returns it, visualization canvas renders.
