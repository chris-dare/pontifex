# Pontifex MCP

The security and governance layer for MCP servers, built on the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

This is the home of **[pontifex-mcp](https://pypi.org/project/pontifex-mcp/)** — a Python library for building [MCP](https://modelcontextprotocol.io) servers that connect AI agents to real systems **without giving up control over who can call what**. You write the tools; it handles authentication, per-caller scopes, rate limits, and a full audit trail.

## The idea

AI agents are ready to do real work against your systems. What the MCP SDK gives you is a *server* that exposes tools. What it doesn't give you is the control that makes a server safe to point at production data: *who* is calling, *what* they're allowed to touch, *how often*, and a *record* of what happened.

`pontifex-mcp` is that control layer. It turns your existing APIs, data stores, and internal services into **governed tools any AI agent can call** — and it runs on your own infrastructure, so your data never leaves your environment.

- **Secure by default** — OAuth 2.1 JWTs *and* `sk_…` API keys; every tool call is authenticated, against any OIDC provider (Auth0, Entra, Clerk, Keycloak).
- **Least-privilege scopes** — `domain:resource:action`, checked before every call. Callers can't widen their own access.
- **Auditable** — every call recorded: who, what, when, data source, cache hit, latency.
- **Resilient** — per-caller rate limiting, adapter failover, circuit breaking.
- **Observable** — Logfire / OpenTelemetry tracing and metrics wired in.
- **Built on the MCP SDK** — keep its tools, protocol, and transports; add the controls a production server needs.

## Install

```bash
pip install pontifex-mcp     # or: uv add pontifex-mcp
```

Requires Python 3.12+ — and nothing else to get started. A `PontifexMCP` server runs with no database, no Redis, and no auth; you add Postgres and Redis only when you turn on API-key enforcement. The full quickstart — the zero-infra floor, graduating to enforced auth and durable audit, the security model — lives in **[core/README.md](core/README.md)** and the [documentation](https://chris-dare.github.io/pontifex/).

## This repository

A [uv workspace](https://docs.astral.sh/uv/concepts/workspaces/) holding the library and a demo domain:

```
core/pontifex_mcp/   The pontifex-mcp library — auth, scopes, audit, resilience, observability
domains/gse/         Ghana Stock Exchange — a worked example domain built on the library
alembic/             Database migrations (core schema + per-domain schemas)
tests/               core + domain tests
deploy/              Dockerfiles, fly.toml
scripts/             Operational scripts (seed, export audit, health check)
```

**Core has zero domain knowledge.** A domain is a self-contained folder under `domains/` — a settings class, one or more data adapters, and tools wrapped with `tool_runtime`. Adding one requires no changes to core. The GSE domain is the reference: see **[domains/gse/README.md](domains/gse/README.md)**.

## Develop

```bash
git clone https://github.com/chris-dare/pontifex && cd pontifex
docker compose up -d redis postgres   # infrastructure
uv sync                               # install the workspace
uv run alembic upgrade head           # run migrations
uv run pytest                         # tests
```

Lint with `uv run ruff check .`, format with `uv run ruff format .`, type-check with `uv run ty check`.

## Documentation

- **Docs site** — [https://chris-dare.github.io/pontifex/](https://chris-dare.github.io/pontifex/)
- **Package README** — [core/README.md](core/README.md) (also rendered on [PyPI](https://pypi.org/project/pontifex-mcp/))
- **Demo domain** — [domains/gse/README.md](domains/gse/README.md)

## License

Apache-2.0 © Chris Dare. Part of [Argonauts](https://argonauts.chrisdare.me).