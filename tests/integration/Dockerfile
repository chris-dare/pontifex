# Shared image for the integration stack: runs the Pontifex HTTP app, the
# downstream resource server, alembic migrations, and the test runner — all need
# only the core package's deps (fastapi, uvicorn, mcp, httpx, authlib,
# sqlalchemy, asyncpg, alembic, redis, pyyaml). Build context is the repo root.
FROM python:3.12-slim
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY pyproject.toml uv.lock .python-version ./
COPY core/ core/
COPY domains/gse/ domains/gse/
RUN uv sync --package pontifex-mcp --frozen --no-dev || uv sync --package pontifex-mcp --no-dev

COPY alembic/ alembic/
COPY tests/integration/ tests/integration/

ENV PYTHONUNBUFFERED=1
