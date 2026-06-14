# Security

Pontifex MCP exists to make one thing safe: **letting an AI agent call your real systems.** This page
is the security model behind that — written for someone deciding whether to put it in front of
production data.

## The short version

- **Nothing runs unauthenticated.** Every tool call carries a verified identity — an API key or an
  OAuth 2.1 token — before any handler executes.
- **Least privilege.** A caller can only invoke the tools their scopes allow, and **cannot widen their
  own access** at runtime.
- **Everything is recorded.** Each call produces an audit row: who, what, when, which data source.
- **Your data stays yours.** It's self-hosted — it runs on your own infrastructure, against your own
  databases, with no third party in the path.

## Authentication

Two credential types, both resolving to a single verified identity:

| Credential | For | How it's verified |
| --- | --- | --- |
| `sk_…` **API key** | scripts, CI, machine-to-machine | Hashed at rest; the presented key is hashed and compared — the plaintext is never stored. |
| **OAuth 2.1 JWT** | interactive clients (Claude Desktop, agents) | Signature verified against your OIDC provider's JWKS, with issuer and audience checks. |

JWT validation is deliberately strict:

- **Asymmetric algorithms only.** Symmetric/`alg: none` tokens are rejected — defeating the classic
  algorithm-confusion and unsigned-token attacks.
- **No privilege from claims you don't control.** A caller's rate limit and scopes come from *server*
  configuration and your provider's verified claims — a forged `rate_limit` or scope claim in a token
  is ignored.
- **No validation oracle.** Rejections return a single generic message, so a probing client can't learn
  *why* a token failed.

## Authorization

Permissions use a `domain:resource:action` scope model (e.g. `orders:order:read`). The scope a tool
requires is declared on the tool itself and checked **before the handler runs**. Scopes are granted by
the caller's API key or their verified token claims — and are never expanded at runtime. Wildcards
(`orders:*:read`) let you grant breadth deliberately, not by accident.

## Audit & accountability

Every tool call writes an `AuditRecord` — caller identity, tool, timestamp, data source, cache hit, and
latency — to your Postgres database. This is the trail you need for **incident response** ("who accessed
this, and when?") and **compliance** evidence. Because the writer is pluggable, you can route audit
events to your own sink as well.

## Data residency & isolation

- **Self-hosted.** Pontifex MCP is a library you run on your own infrastructure — no third party sits in
  the request path. Your systems' data never transits anything outside your environment.
- **You hold the secrets.** Database, Redis, and provider credentials are read from environment
  variables — nothing is hardcoded or phoned home.
- **Standards-based discovery.** OAuth bootstrapping uses RFC 9728 protected-resource metadata and a
  `WWW-Authenticate` challenge — no proprietary handshake.

## What's your responsibility

Pontifex secures the *MCP layer*. You still own the perimeter around it:

- Run it over TLS, behind your load balancer / gateway.
- Configure your OIDC provider (issuer, audience, the scopes claim, role mappings).
- Secure and rotate the credentials in your environment.
- Scope API keys to the minimum each caller needs.

!!! note "Verifiable, not just asserted"

    Every claim here maps to code you can read in `pontifex_mcp` — the JWT validation, the pre-call
    scope check, the audit write. The security model is open to inspection, not taken on trust.
