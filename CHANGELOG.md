# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.5] - 2026-03-31

### Fixed
- **Per-cluster spread** — Alt+scroll spread now expands/contracts each cluster from its own centroid instead of the global network center
- **Zoom floor** — set OrbitControls `minDistance` to prevent zoom from stalling at extreme close range

## [0.2.4] - 2026-03-30

### Added
- **Serialized SQLite write transactions** — `immediate_transaction()` context manager with per-database write gate serializes concurrent writers via `BEGIN IMMEDIATE`, replacing manual `db.commit()`/`db.rollback()` across all modules
- **Pipeline transaction safety** — LLM/embedding work runs outside transactions; DB writes batched inside `immediate_transaction` blocks
- **Document delete cleanup** — orphan engram garbage collection now removes from all related tables (aliases, projections, embeddings, engrams)
- **URL fetch race-condition fix** — duplicate check moved inside write transaction to prevent concurrent inserts of the same URL
- **Transaction test suite** — covers cross-connection serialization, nested reentrant transactions, and mixed-connection rejection

### Changed
- SQLite busy timeout centralised as `SQLITE_BUSY_TIMEOUT_MS` constant (raised to 15s)
- `_resolve_and_create_engrams` split into `_prepare_engrams` (LLM work) and `_materialize_engrams` (DB writes) for cleaner transaction boundaries
- Edge proposal collection extracted into `_collect_edge_proposals` to gather LLM results before opening write transactions

## [0.2.3] - 2026-03-30

### Added
- **Theme system** — three switchable colour themes (Midnight, Graphite, Phantom) selectable at runtime via Settings page; stored in DB as `ui_theme` setting
- **Redesigned UI typography** — Cormorant Garamond (serif display) + DM Sans (body sans) replace JetBrains Mono; new `.text-display-lg`, `.text-display-sm`, `.section-label` CSS classes
- **CSS custom properties** — all theme colours flow through `:root` variables; cards, sidebar, borders, and accents adapt automatically on theme switch
- **Staggered card animations** — document cards enter with cascading fade-up delays
- **Card hover effects** — `.doc-card` class adds lift + shadow transition on hover

### Changed
- Complete colour palette overhaul: cool midnight slate replaces neutral grays as default
- Source-type badges and heat-tier indicators use fixed semantic colours across all themes
- Sidebar, mobile header, and viz page now use CSS variables instead of hardcoded hex values
- Settings page reorganised with theme picker as first section

## [0.2.2] - 2026-03-27

### Added
- **Document revision system** — every edit snapshots the pre-edit state into a `document_revisions` table with full history accessible via API (`GET /revisions`, `GET /revisions/{num}`)
- **Annotation layer** for non-scribble documents (URLs, files, feeds) — original text stays immutable, users add personal notes via an `annotation` column that feeds into entity extraction alongside the source text
- **Incremental reprocessing** — `revise_document()` re-extracts entities, diffs the engram set against existing links, and only adds/removes the delta. Falls back to full nuke-and-rebuild when engram churn exceeds 50%
- **Inline edit mode** on document detail page — Edit button for scribbles (title + text), Annotate button for non-scribbles (annotation textarea below read-only original)
- Source-type validation on PATCH endpoint — scribbles reject annotation field, non-scribbles reject text modification
- FTS5 rebuilt to include `annotation` column in full-text search (migration 003)

### Changed
- `_remove_document_associations` moved to `pipeline.py` as `remove_document_associations` (shared by API delete handler and pipeline fallback)
- Extracted `_resolve_and_create_engrams` helper — deduplicates the normalize/synonym/embed/create block between `process_document` and `revise_document`
- Extracted `_finalize_pipeline` helper — deduplicates projection/heat/status tail between ontology and revision pipeline runners
- Extracted `snapshot_and_update_document` — shared by API PATCH handler and UI inline editor
- PATCH handler no longer nukes engram/edge associations on edit — preserved for incremental pipeline diff
- Batched DELETE queries in incremental path (IN clauses instead of per-engram loops)
- `RevisionOut` schema now extends `DocumentRevision` model (follows `DocumentOut`/`Document` pattern)
- Heat scoring revision signal now functional (was always 0 before since no revision path existed)

## [0.2.1] - 2026-03-26

### Added
- Graph-derived document heat scoring (active / reference / dormant tiers)

## [0.1.0] - Unreleased

### Added
- Core ontology engine: entity extraction, deduplication (exact name, alias index, KNN, vector, concept-hash), typed edge generation
- Ingestion pipeline: scribbles, file uploads (PDF/DOCX/MD), URL scraping, RSS/YouTube feeds
- Triage system for automated feed gating
- 3D visualization: constellation mode, PageRank sizing, GLSL shaders, radial reveal, node breathing, auto-orbit
- Multi-provider LLM support: Claude, Google, OpenAI, Ollama (hot-swappable at runtime)
- Multi-provider embeddings: local (sentence-transformers), OpenAI, Google (changeable with KG rebuild)
- Configurable text tidy levels (format_only through full_revision)
- PDF ingestion with processing metadata and progress tracking
- Full-text search via FTS5
- First-run setup wizard (embedding + LLM provider selection)
- Passphrase authentication for server mode (PBKDF2-SHA256, HMAC-signed cookies)
- API key encryption at rest (Fernet)
- Desktop build pipeline: Tauri v2 + PyInstaller sidecar
- Docker support: multi-stage build, single-container deployment
- Collapsible sidebar with minimap, mobile navigation
- Document editing with ontology reprocessing
- Settings UI for runtime LLM/embedding configuration
