# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Hypomnema** (plural: *hypomnemata*) — from the Greek term for a personal note, reminder, draft, or commentary, used in classical antiquity for compiling notes on readings or experiences.

This is an Automated Ontological Synthesizer — a research tool that builds a knowledge graph from zero-friction inputs (text "scribbles", file uploads, automated feeds). It extracts entities ("Engrams"), normalizes and deduplicates them via embeddings, and generates relational edges with typed predicates. The UI visualizes clusters and structural gaps rather than file trees.

This is **not** a PKM/note-taking tool. It is an active knowledge network with no folders or manual organization.

## Architecture

**Three-layer stack, single codebase, no containers:**

- **Backend:** Python / FastAPI — orchestrates LLM calls, document parsing, embedding, cronjobs
- **Database:** SQLite with WAL mode + `sqlite-vec` extension — single portable `.db` file for all data and vector search
- **Frontend:** Next.js PWA — thin client that renders the topological UI, queries the backend API

### Data Flow

1. **Ingestion** — manual scribbles, file throws (PDF/DOCX/MD), or automated periodic feeds (RSS, scrapes, transcripts)
2. **Triage ("The Bouncer")** — cheap LLM/embedding filter gates automated feeds to protect API budget
3. **Ontology Engine** — capable LLM extracts entities, normalizes to canonical strings, generates embeddings, deduplicates via concept hash (Engram). Top-K vector retrieval limits edge generation to avoid O(N²) API calls. Targeted LLM call assigns typed predicates (contradicts, provides methodology for, etc.)
4. **Storage** — raw text stored in central `text` column; structure lives entirely in Engram nodes and edges
5. **Visualization** — UMAP/t-SNE projection, spatial clustering, gap highlighting

### Deployment Modes

- **Local mode** (`uv run hypomnema dev`) — binds to localhost, opens browser, hot-reload enabled
- **Server mode** (`HYPOMNEMA_MODE=server HYPOMNEMA_HOST=<ip> uv run hypomnema serve`) — binds to specified host (e.g. Tailscale IP), runs production frontend, 24/7 continuous ingestion
- **Desktop mode** (`HYPOMNEMA_MODE=desktop`) — Tauri v2 native app, PyInstaller'd backend as sidecar, static frontend served via FastAPI `StaticFiles`, cloud-only embeddings (no torch)

### Running

All commands run from `backend/`:

```bash
# Development (localhost, hot-reload, auto-opens browser)
uv run hypomnema dev
uv run hypomnema dev --no-browser

# Production / server mode (Tailscale / remote access)
HYPOMNEMA_MODE=server HYPOMNEMA_HOST=<tailscale-ip> uv run hypomnema serve
HYPOMNEMA_MODE=server HYPOMNEMA_HOST=<tailscale-ip> uv run hypomnema serve --build  # force frontend rebuild

# Tests
cd backend && uv run pytest                    # all backend tests
cd frontend && npm test                        # vitest
cd frontend && npx playwright test             # e2e
```

### Configuration

All settings use `HYPOMNEMA_` env prefix. Key env vars:

- `HYPOMNEMA_MODE` — `local` (default), `server`, or `desktop`
- `HYPOMNEMA_HOST` — bind address (default `127.0.0.1`, set to Tailscale IP for server mode)
- `HYPOMNEMA_LLM_PROVIDER` — `claude`, `google`, `openai`, `ollama`, or `mock` (default `mock`)
- `HYPOMNEMA_EMBEDDING_PROVIDER` — `local`, `openai`, or `google` (default `local`, fixed at startup)
- `HYPOMNEMA_ANTHROPIC_API_KEY`, `HYPOMNEMA_GOOGLE_API_KEY`, `HYPOMNEMA_OPENAI_API_KEY` — provider API keys
- `HYPOMNEMA_DB_PATH` — SQLite database path (default `data/hypomnema.db`)

LLM provider and API keys can also be configured at runtime via the Settings UI (`/settings`). DB settings override env vars for LLM-related fields. Embedding provider is fixed at startup — changing it requires a fresh database.

### Frontend Layout

- **Persistent sidebar** (`Sidebar.tsx`) with nav items (Stream, Search, Settings), viz minimap, and full viz link
- **LayoutShell** wraps all pages: sidebar layout for normal pages, full-screen passthrough for `/viz`
- **VizDataProvider** context at root level shares viz data between minimap and full page (single fetch)
- **Documents are editable** — "continue" button on scribble cards loads into edit mode with draft auto-save via localStorage

## Key Design Constraints

- No Docker, no PostgreSQL — bare-metal, single `.db` file
- Flat database: no file/folder hierarchy, all structure is dynamic from graph edges
- Frontend does no heavy compute — pure rendering client
- Entity deduplication uses embedding-based concept hashes for O(1) lookup
- Edge generation uses Top-K retrieval to bound LLM API costs
- Embedding provider fixed at install time — different models produce incompatible vectors
- LLM provider hot-swappable at runtime via Settings API (no restart needed)
- API keys encrypted at rest via Fernet with auto-generated local keyfile
