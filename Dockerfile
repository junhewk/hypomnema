FROM python:3.12-slim

WORKDIR /app

# System deps for sqlite-vec and NiceGUI
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml uv.lock ./
COPY src/ src/
RUN pip install --no-cache-dir uv && \
    uv sync --frozen --no-dev --extra projection && \
    rm -rf /root/.cache

# Config
ENV HYPOMNEMA_MODE=server \
    HYPOMNEMA_HOST=0.0.0.0 \
    HYPOMNEMA_DB_PATH=/app/data/hypomnema.db

EXPOSE 8073

# Health check
HEALTHCHECK --interval=30s --timeout=5s \
    CMD curl -f http://localhost:8073/api/health || exit 1

# Run as non-root
RUN useradd -m hypomnema
USER hypomnema

CMD ["uv", "run", "hypomnema", "serve"]
