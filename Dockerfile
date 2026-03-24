# ── Stage 1: Build frontend as static export ──────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
ENV NEXT_EXPORT=1
ENV NEXT_PUBLIC_API_URL=""
RUN npm run build

# ── Stage 2: Backend + static serving ─────────────────────
FROM python:3.12-slim AS backend

# System deps for sqlite-vec, optional torch, and healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install Python dependencies
COPY backend/pyproject.toml backend/uv.lock* ./backend/
ARG VARIANT=full
RUN cd backend && \
    if [ "$VARIANT" = "slim" ]; then \
      uv sync --no-dev --no-install-project; \
    else \
      uv sync --no-dev --no-install-project --extra local-embeddings; \
    fi

# Copy backend source
COPY backend/ ./backend/

# Install the project itself
RUN cd backend && \
    if [ "$VARIANT" = "slim" ]; then \
      uv sync --no-dev; \
    else \
      uv sync --no-dev --extra local-embeddings; \
    fi

# Copy static frontend from builder
COPY --from=frontend-builder /app/frontend/out ./static

# Environment
ENV HYPOMNEMA_MODE=server
ENV HYPOMNEMA_HOST=0.0.0.0
ENV HYPOMNEMA_STATIC_DIR=/app/static
ENV HYPOMNEMA_DB_PATH=/app/data/hypomnema.db

EXPOSE 8073

# Create data directory
RUN mkdir -p /app/data

# Non-root user
RUN adduser --disabled-password --gecos '' --home /app hypomnema && \
    chown -R hypomnema:hypomnema /app
USER hypomnema

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fs http://localhost:8073/api/health || exit 1

CMD ["backend/.venv/bin/uvicorn", "hypomnema.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8073", "--log-level", "info"]
