# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Hypomnema** (plural: *hypomnemata*) — from the Greek term for a personal note, reminder, draft, or commentary, used in classical antiquity for compiling notes on readings or experiences.

This is an Automated Ontological Synthesizer — a research tool that builds a knowledge graph from zero-friction inputs (text "scribbles", file uploads, automated feeds). It extracts entities ("Engrams"), normalizes them, deduplicates them via deterministic alias matching plus embeddings, and generates relational edges with typed predicates. The UI visualizes clusters and structural gaps rather than file trees.

This is **not** a PKM/note-taking tool. It is an active knowledge network with no folders or manual organization.

## Architecture

**Single Python stack, single codebase:**

- **App:** [NiceGUI](https://nicegui.io/) serves both the UI (Python pages/components) and the FastAPI API. No separate frontend build, no Node.js.
- **Database:** SQLite with WAL mode + `sqlite-vec` extension — single portable `.db` file for all data and vector search
- **Backend:** Python / FastAPI routers — orchestrate LLM calls, document parsing, embedding, cronjobs

### Data Flow

1. **Ingestion** — manual scribbles, file throws (PDF/DOCX/MD), or automated periodic feeds (RSS, scrapes, transcripts). PDFs extracted via opendataloader-pdf (layout-aware markdown) with pypdf fallback.
2. **Triage ("The Bouncer")** — cheap LLM/embedding filter gates automated feeds to protect API budget
3. **Ontology Engine** — capable LLM extracts entities, normalizes to canonical strings, generates embeddings, then deduplicates engrams in this order: exact canonical name, direct alias-index lookup, lexical alias overlap on KNN candidates, vector similarity, and concept-hash fallback. Targeted LLM call assigns typed predicates (contradicts, provides methodology for, etc.). For files/URLs, also generates a title revision and TL;DR summary (not a full rewrite). Scribbles get full tidy rewriting with configurable tidy levels (internal only, not exposed in UI).
4. **Storage** — raw text stored in central `text` column; structure lives entirely in Engram nodes and edges
5. **Revision** — scribbles editable in-place (text + title); non-scribbles (URL/file/feed) get a user annotation layer (`annotation` column) — original text is immutable. Every edit snapshots the pre-edit state into `document_revisions`, increments `revision`, clears tidy fields, and enqueues incremental reprocessing. The incremental pipeline (`revise_document`) re-extracts entities, diffs the engram set, and only adds/removes the delta — if churn exceeds 50% of existing engrams, falls back to full nuke-and-rebuild. Shared helper `snapshot_and_update_document()` is used by both the API PATCH handler and the UI inline editor.
6. **Heat scoring** — after pipeline completes, `compute_all_heat()` scores every document from graph signals (temporal recency, concept co-activity, revision count, edge centrality) and classifies as `active` / `reference` / `dormant`. Stream page has filter tabs for each tier.
7. **Visualization** — UMAP/t-SNE projection, spatial clustering, gap highlighting

### Deployment Modes

- **Local mode** (`uv run hypomnema dev`) — binds to localhost:8073, opens browser, hot-reload enabled
- **Server mode** (`uv run hypomnema serve` or `HYPOMNEMA_HOST=<ip> uv run hypomnema serve`) — defaults to remote/server networking, 24/7 continuous ingestion
- **Docker mode** (`docker compose up`) — single container, port 8073
- **Desktop mode** (`uv run hypomnema desktop`) — native window via pywebview, no browser required

### Running

All commands run from the project root:

```bash
# Development (localhost, hot-reload, auto-opens browser)
uv run hypomnema dev
uv run hypomnema dev --no-browser

# Production / server mode (Tailscale / remote access)
uv run hypomnema serve
HYPOMNEMA_HOST=<tailscale-ip> uv run hypomnema serve

# Desktop (native window via pywebview)
uv run hypomnema desktop

# Docker
docker compose up --build                      # single container, port 8073

# Tests
uv run pytest                                  # all backend tests
```

### Configuration

All settings use `HYPOMNEMA_` env prefix. Key env vars:

- `HYPOMNEMA_MODE` — `local` (default), `server`, or `desktop`; `serve` defaults to `server` if unset
- `HYPOMNEMA_HOST` — bind address (default `127.0.0.1`, set to Tailscale IP for server mode)
- `HYPOMNEMA_LLM_PROVIDER` — `claude`, `google`, `openai`, or `ollama` (default `google`)
- `HYPOMNEMA_EMBEDDING_PROVIDER` — `openai` or `google` (default `google`)
- `HYPOMNEMA_ANTHROPIC_API_KEY`, `HYPOMNEMA_GOOGLE_API_KEY`, `HYPOMNEMA_OPENAI_API_KEY` — provider API keys
- `HYPOMNEMA_DB_PATH` — SQLite database path (default `data/hypomnema.db`)

LLM provider and API keys can also be configured at runtime via the Settings UI (`/settings`). DB settings override env vars for LLM-related fields. Embedding provider can be changed at runtime via Settings — this triggers a full knowledge graph rebuild (all engrams/edges deleted, documents reprocessed).

### UI Layout (NiceGUI)

- **Collapsible sidebar** (`ui/layout.py`) with Material icons and nav items (Stream, Search, Settings), viz minimap, and full viz link — collapses to icon-only via Quasar drawer mini mode, state toggled via button
- **`page_layout()`** wraps all pages — renders sidebar + main content container. Each page uses `@ui.page` decorator.
- **Viz minimap** in sidebar — loads projection data and renders a small 3d-force-graph preview
- **Inline document editing** — Edit/Annotate button on document detail page toggles inline edit mode. Scribbles get title + text editor; non-scribbles get annotation textarea below read-only original text. Save calls `snapshot_and_update_document()` and enqueues incremental reprocessing.
- **Pages** (`ui/pages/`): `stream.py`, `search.py`, `document.py`, `engram.py`, `settings.py`, `setup.py`, `viz.py`
- **Components** (`ui/components/`): `document_card.py` and other reusable UI elements
- **Viz** (`ui/viz/`): `graph.py` (3d-force-graph integration), `minimap.py`, `transforms.py` (data preparation)

### Visualization

- **3d-force-graph** — rendered via NiceGUI's `ui.html`/JavaScript interop, replacing the old Three.js/R3F approach
- **PageRank sizing** — power iteration (damping=0.85, 20 iterations) using edge confidence as weights; nodes above 85th percentile scale up, rest stay at base size
- **Cluster colors** — golden-angle HSL palette for distinct cluster coloring; noise points get muted gray
- **Auto-orbit** — cinematic slow rotation toggled via HUD; stops on user interaction
- **Edge highlighting** — focused node's edges glow in cluster color; others dim

## Key Design Constraints

- Single `.db` file, no PostgreSQL — optional Docker for deployment
- Flat database: no file/folder hierarchy, all structure is dynamic from graph edges and heat scoring
- Document actionability is auto-derived from graph topology, not manual categories — `HeatTier` Literal type in `ontology/heat.py`, styles in `ui/theme.py`
- UI is server-rendered Python (NiceGUI) — no separate frontend build or Node.js dependency
- Entity deduplication is multi-stage: exact name, persisted alias index, KNN alias overlap, vector similarity, then concept-hash fallback
- Edge generation uses Top-K retrieval to bound LLM API costs
- Document revision is source-type-dependent: scribbles edit text in-place, non-scribbles use an `annotation` column (original text immutable). Revision history stored in `document_revisions` table. Incremental pipeline diffs engrams and falls back to full rebuild above 50% churn.
- Embedding provider changeable at runtime — triggers full knowledge graph rebuild (documents preserved)
- LLM provider hot-swappable at runtime via Settings API (no restart needed)
- API keys encrypted at rest via Fernet with auto-generated local keyfile

## Naming

- Use `engram dedupe` or `alias-index dedupe` for the production functionality.
- Do not describe the production path as `hardened`; that label is only useful inside eval comparisons (`baseline`, `adjusted`, `hardened`).
