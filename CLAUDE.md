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

- **Local mode** (`start-web.sh`) — binds to localhost, opens in browser, cronjobs run only while active
- **Server mode** (`start-server.sh`) — binds to Tailscale VPN interface, runs 24/7, continuous ingestion

## Key Design Constraints

- No Docker, no PostgreSQL — bare-metal, single `.db` file
- Flat database: no file/folder hierarchy, all structure is dynamic from graph edges
- Frontend does no heavy compute — pure rendering client
- Entity deduplication uses embedding-based concept hashes for O(1) lookup
- Edge generation uses Top-K retrieval to bound LLM API costs
