<p align="center">
  <img src="./hypomnema_text.png" alt="Hypomnema" width="360">
</p>

<p align="center">
  <strong>An automated ontological synthesizer.</strong><br>
  Drop in notes, PDFs, and URLs. Get back a living knowledge network.
</p>

<p align="center">
  <a href="https://github.com/junhewk/hypomnema/actions/workflows/ci.yml"><img src="https://github.com/junhewk/hypomnema/actions/workflows/ci.yml/badge.svg?branch=master" alt="CI"></a>
  <a href="https://github.com/junhewk/hypomnema/releases"><img src="https://img.shields.io/github/v/release/junhewk/hypomnema?include_prereleases&label=release" alt="Release"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12+-3776ab" alt="Python 3.12+"></a>
</p>

<p align="center">
  <a href="./LICENSE">AGPL-3.0</a> &middot;
  <a href="./CHANGELOG.md">Changelog</a> &middot;
  <a href="./DEVELOPMENT.md">Development</a>
</p>

---

Hypomnema extracts concepts from your research material, deduplicates them, links them with typed relationships, and renders the result as an explorable 3D network. No folders, no tags, no manual organization.

## Features

- **Zero-friction input** — scribbles, PDF/DOCX/Markdown upload, URL scraping, RSS/YouTube feeds
- **Smart PDF extraction** — layout-aware parsing via [opendataloader-pdf](https://github.com/opendataloader-project/opendataloader-pdf) with column detection and structure preservation; pypdf fallback
- **Automatic ontology** — LLM-powered entity extraction, multi-stage deduplication (exact match, alias index, KNN, vector similarity, concept hash), typed edge generation (supports, contradicts, critiques, extends, ...)
- **Title + TL;DR** — files and URL fetches get an LLM-generated title revision and concise summary; scribbles get full tidy rewriting
- **3D visualization** — constellation-mode point cloud with PageRank node sizing, cluster color reveal, cinematic auto-orbit (via 3d-force-graph)
- **Document revision** — scribbles are editable in-place; URLs/files/feeds get a user annotation layer. Every edit is revision-logged and re-processed incrementally (engram diff with 50% churn fallback to full rebuild). Feeds into heat scoring.
- **Document heat scoring** — graph-derived actionability signal classifies documents as active, reference, or dormant based on temporal recency, concept co-activity, revision count, and graph centrality. No manual filing — organization emerges from the knowledge graph.
- **Full-text + semantic search** — FTS5 for keyword search (including annotations), sqlite-vec for vector similarity
- **Multi-provider** — Claude, Gemini, OpenAI, Ollama for LLM; OpenAI or Google for embeddings. Hot-swappable at runtime.
- **Single-file database** — everything in one portable SQLite file. No Postgres, no external services.
- **Encrypted at rest** — API keys stored with Fernet encryption
- **Desktop app** — native window via pywebview, built with PyInstaller for macOS/Windows/Linux

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- An API key for at least one LLM provider (Google, OpenAI, Anthropic, or local Ollama)

### Local development

```bash
uv sync
uv run hypomnema dev
```

Opens `http://localhost:8073`. On first run, a setup wizard guides you through embedding and LLM provider configuration.

### Docker

```bash
docker compose up --build
```

Runs at `http://localhost:8073`. Data persists in `./data/`.

Set a passphrase for remote access:

```bash
HYPOMNEMA_PASSPHRASE=your-secret docker compose up --build
```

### Desktop app

Download the latest `.app` (macOS) or `.exe` (Windows) from [Releases](https://github.com/junhewk/hypomnema/releases). No Python or dependencies required.

## Configuration

All settings use the `HYPOMNEMA_` prefix. Copy [`.env.example`](./.env.example) for a full reference.

| Variable | Default | Description |
|----------|---------|-------------|
| `HYPOMNEMA_LLM_PROVIDER` | `google` | `claude`, `google`, `openai`, or `ollama` |
| `HYPOMNEMA_EMBEDDING_PROVIDER` | `google` | `openai` or `google` |
| `HYPOMNEMA_ANTHROPIC_API_KEY` | | Required if using Claude |
| `HYPOMNEMA_GOOGLE_API_KEY` | | Required if using Gemini |
| `HYPOMNEMA_OPENAI_API_KEY` | | Required if using OpenAI |
| `HYPOMNEMA_PASSPHRASE` | | Pre-set auth passphrase (server/Docker mode) |
| `HYPOMNEMA_DB_PATH` | `data/hypomnema.db` | SQLite database location |

LLM provider and API keys can also be configured at runtime via the Settings UI. Embedding provider is chosen at first-run setup — changing it later triggers a full knowledge graph rebuild.

## Architecture

Single Python stack, single codebase:

- **App** — [NiceGUI](https://nicegui.io/) serves both the UI and the FastAPI API. No separate frontend build step, no Node.js.
- **Database** — SQLite + WAL mode + [sqlite-vec](https://github.com/asg017/sqlite-vec): single portable file for all data and vector search
- **Backend** — Python / FastAPI routers: orchestrate LLM calls, document parsing, embedding, feed scheduling

### Deployment modes

| Mode | Command | Use case |
|------|---------|----------|
| Local | `uv run hypomnema dev` | Development, personal use |
| Server | `uv run hypomnema serve` | Always-on, remote access via Tailscale/LAN |
| Docker | `docker compose up` | Self-hosted server, single container |
| Desktop | `uv run hypomnema desktop` | Native window via pywebview |

## Contributing

```bash
uv sync
uv run ruff check .
uv run mypy .
uv run pytest
```

See [DEVELOPMENT.md](./DEVELOPMENT.md) for architecture details and implementation notes.

## License

[AGPL-3.0](./LICENSE)
