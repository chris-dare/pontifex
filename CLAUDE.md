# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Project: MCP Platform

Multi-domain MCP server platform. Core library + pluggable domain modules. First domain: Ghana Stock Exchange (GSE).

Full architecture: see `MCP_PLATFORM_SOLUTION_DESIGN_v2.md`

### Stack

- Python 3.12
- FastAPI 0.115+
- SQLAlchemy 2.x (async, asyncpg driver)
- Pydantic v2 (v2 API only — no `.dict()`, no `.schema()`)
- Alembic (async migrations)
- PostgreSQL 16
- Redis 7 (redis.asyncio)
- httpx (async HTTP client for adapters)
- Logfire (observability — tracing, metrics, OTEL-based)
- uv (package manager)
- ruff (linter + formatter)
- ty (type checker — Astral's Rust-based alternative to mypy)
- pytest + pytest-asyncio

### Commands

- Install: `uv sync`
- Dev server: `uv run uvicorn gse_mcp.main:app --reload --port 8080`
- Test: `uv run pytest`
- Test single: `uv run pytest tests/domains/gse/test_tools.py -k test_live_prices`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Type check: `uv run ty check`
- Migration create: `uv run alembic revision --autogenerate -m "description"`
- Migration run: `uv run alembic upgrade head`
- Deploy: `fly deploy --app mcp-gse`

### Repo Structure

```
mcp-platform/
├── pyproject.toml     # Virtual workspace root (uv workspace)
├── uv.lock            # Single lockfile, committed
├── core/mcp_core/     # Shared library — auth, cache, audit, circuit breaker
├── domains/gse/gse_mcp/  # GSE domain module — tools, adapters, models
├── alembic/           # Migrations: alembic/core/ + alembic/domains/gse/
├── tests/             # tests/core/ + tests/domains/gse/
├── deploy/            # Dockerfiles, fly.toml
└── scripts/           # seed_db, export_audit_logs, health_check
```

### Architecture Rules

- **Core vs domain:** Core has zero domain knowledge. If it mentions "stock", "price", or "GSE", it's in the wrong place.
- **Adapter pattern:** All external API calls go through adapters implementing the `DataAdapter` protocol. Never call an external API directly from a tool handler.
- **Adding a domain:** New domain = new folder under `domains/`. Core requires zero changes.
- **Schema isolation:** Each domain gets its own Postgres schema. Domain services cannot touch other domains' tables.
- **Scope format:** Permission scopes use `domain:resource:action` (e.g. `gse:live_prices:read`). See Section 11 of the solution design.

### Conventions

- Async everywhere — `AsyncSession`, `async def`, `httpx.AsyncClient`
- Type annotations required on all functions
- No `Any` without a justification comment
- No `print()` — use `structlog`
- Pydantic v2 API only — `model_dump()` not `.dict()`, `model_json_schema()` not `.schema()`
- SQLAlchemy 2.x `select()` style — not legacy `query()`
- `selectinload()` for eager loading
- Named exports everywhere
- Tests follow AAA pattern (Arrange, Act, Assert)

### Avoid

- No sync SQLAlchemy — always `AsyncSession`
- No raw SQL strings — always SQLAlchemy ORM
- No hardcoded secrets — env vars via `pydantic-settings`
- No domain logic in core
- No core changes when adding a new domain module (flag it if you think core needs a change)
- No modifying alembic migration files — create new ones
- No new dependencies without listing them and asking first
