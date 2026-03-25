<p align="center">
  <img src="./frontend/public/hypomnema_text.png" alt="Hypomnema" width="360">
</p>

<p align="center">
  <strong>An automated ontological synthesizer.</strong><br>
  Drop in notes, PDFs, and URLs. Get back a living knowledge network.
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
- **3D visualization** — constellation-mode point cloud with PageRank node sizing, GLSL shaders, cluster color reveal, cinematic auto-orbit
- **Full-text + semantic search** — FTS5 for keyword search, sqlite-vec for vector similarity
- **Multi-provider** — Claude, Gemini, OpenAI, Ollama for LLM; local sentence-transformers, OpenAI, or Google for embeddings. Hot-swappable at runtime.
- **Single-file database** — everything in one portable SQLite file. No Postgres, no external services.
- **Encrypted at rest** — API keys stored with Fernet encryption

## Quick Start

### Local development

```bash
cd backend
uv sync --extra local-embeddings
uv run hypomnema dev
```

Opens `http://localhost:3073`. Requires Python 3.12+, Node.js 20+, and [uv](https://docs.astral.sh/uv/).

### Docker

```bash
docker compose up --build
```

Runs at `http://localhost:8073`. Data persists in `./data/`.

Set a passphrase for remote access:

```bash
HYPOMNEMA_PASSPHRASE=your-secret docker compose up --build
```

### Desktop

Pre-built binaries for macOS, Windows, and Linux are available on the [Releases](../../releases) page. See [BUILD.md](./desktop/BUILD.md) for building from source.

## Configuration

All settings use the `HYPOMNEMA_` prefix. Copy [`.env.example`](./.env.example) for a full reference.

| Variable | Default | Description |
|----------|---------|-------------|
| `HYPOMNEMA_LLM_PROVIDER` | `mock` | `claude`, `google`, `openai`, `ollama`, or `mock` |
| `HYPOMNEMA_EMBEDDING_PROVIDER` | `local` | `local`, `openai`, or `google` |
| `HYPOMNEMA_ANTHROPIC_API_KEY` | | Required if using Claude |
| `HYPOMNEMA_GOOGLE_API_KEY` | | Required if using Gemini |
| `HYPOMNEMA_OPENAI_API_KEY` | | Required if using OpenAI |
| `HYPOMNEMA_PASSPHRASE` | | Pre-set auth passphrase (server/Docker mode) |
| `HYPOMNEMA_DB_PATH` | `data/hypomnema.db` | SQLite database location |

LLM provider and API keys can also be configured at runtime via the Settings UI. Embedding provider is chosen at first-run setup — changing it later triggers a full knowledge graph rebuild.

## Architecture

Three-layer stack, single codebase:

- **Backend** — Python / FastAPI: orchestrates LLM calls, document parsing, embedding, feed scheduling
- **Database** — SQLite + WAL mode + [sqlite-vec](https://github.com/asg017/sqlite-vec): single portable file for all data and vector search
- **Frontend** — Next.js PWA: renders the topological UI, queries the backend API

### Deployment modes

| Mode | Command | Use case |
|------|---------|----------|
| Local | `uv run hypomnema dev` | Development, personal use |
| Server | `uv run hypomnema serve` | Always-on, remote access via Tailscale/LAN |
| Docker | `docker compose up` | Self-hosted server, single container |
| Desktop | Download from Releases | Native app (Tauri + PyInstaller sidecar) |

## Contributing

```bash
# Backend
cd backend && uv sync --extra local-embeddings
uv run ruff check .
uv run mypy .
uv run pytest

# Frontend
cd frontend && npm ci
npm run typecheck
npm test
```

See [DEVELOPMENT.md](./DEVELOPMENT.md) for architecture details and implementation notes.

## License

[AGPL-3.0](./LICENSE)
