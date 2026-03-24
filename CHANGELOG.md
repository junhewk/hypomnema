# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
