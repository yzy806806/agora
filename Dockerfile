# === Build stage ===
FROM python:3.12-slim AS builder

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for cache
COPY pyproject.toml README.md ./

# Install production dependencies only
RUN uv pip install --system \
    fastapi>=0.110 uvicorn>=0.29 websockets>=12.0 \
    pydantic>=2.0 pydantic-settings>=2.0 aiosqlite>=0.20 \
    aiofiles>=24.1 \
    aiobotocore>=2.12 \
    httpx>=0.27 aiohttp>=3.9 prometheus-client>=0.20 pyyaml>=6.0 \
    pyjwt>=2.8 packaging>=24.0

# === Production stage ===
FROM python:3.12-slim AS coordinator

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

# Copy source code (new agora/ package structure)
COPY agora/ /app/agora/
COPY pyproject.toml README.md ./

# Install project (no deps — already installed above)
RUN pip install --no-deps -e .

ENV PATH="/usr/local/bin:$PATH"

# Expose coordinator port
EXPOSE 8765

# Default: start Coordinator
CMD ["agora-coordinator"]

# Health check (uses /health endpoint)
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/api/v1/health')" || exit 1

# === Testing stage ===
FROM python:3.12-slim AS testing

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml README.md ./

# Install all dependencies including dev
RUN uv pip install --system \
    fastapi>=0.110 uvicorn>=0.29 websockets>=12.0 \
    pydantic>=2.0 pydantic-settings>=2.0 aiosqlite>=0.20 \
    aiofiles>=24.1 \
    aiobotocore>=2.12 \
    httpx>=0.27 aiohttp>=3.9 prometheus-client>=0.20 pyyaml>=6.0 \
    pyjwt>=2.8 packaging>=24.0 \
    pytest>=8.0 pytest-asyncio>=0.23 pytest-timeout>=2.2

# Copy source code and tests
COPY agora/ /app/agora/
COPY tests/ /app/tests/
COPY pyproject.toml README.md ./

RUN pip install --no-deps -e .

ENV PATH="/usr/local/bin:$PATH"
