# Why Pontifex

For the person deciding whether to put an AI agent in front of production.

## The gap every AI initiative hits

The model is ready. The systems it needs to act on are not.

Your orders API, your customer database, your internal services — they were built for
your applications and your employees, not for an autonomous agent. Pointing an agent at
them raises the question every security review asks:

> Who is calling, what are they allowed to touch, how often, and what happened?

MCP — the protocol agents use to call tools — answers *none* of that. It standardizes
the connection. It says nothing about control. So teams build an impressive pilot, and
then it stalls at the exact moment it has to touch something real.

Pontifex is the layer that answers those four questions, so the pilot can ship.

## What it changes

| Without a governance layer | With Pontifex |
| --- | --- |
| An agent's access is all-or-nothing | Each caller is scoped to the exact tools they need |
| "Trust the agent" | Trust a verified identity on every call |
| No record of what the agent did | A full audit row per call — caller, tool, data source, latency |
| One flaky upstream stalls everything | Rate limiting, failover, and circuit breaking contain it |
| Your data flows through a vendor | Self-hosted; nothing leaves your environment |

The result: "an agent can reach production" stops being a liability and becomes a
control you can put your name on.

## Built on open standards

Pontifex doesn't ask you to bet on a platform.

- **Built on the official MCP Python SDK.** Not a fork, not a reimplementation.
- **OAuth 2.1 and standard JWTs** for identity — bring any OIDC provider (Auth0,
  Entra, Clerk, Keycloak).
- **OpenAPI** to onboard existing systems without code.
- **RFC 9728 / RFC 8693** for discovery and token exchange — no proprietary handshake.

Pair it with any AI vendor. Run it anywhere you run Python. And if you ever want it
gone, it strips out cleanly — your tools are standard MCP underneath.

## You hold the data

Pontifex is a **library you run**, not a service you send data to.

It sits inside your environment, between the agent and your systems. No third party is
in the request path. Database, Redis, and provider credentials come from your
environment. Nothing is hardcoded. Nothing phones home.

That's what makes "we're connecting AI to customer data" a sentence your security and
compliance teams can finish.

## Pontifex vs. the MCP SDK alone

The SDK gives you a server that exposes tools. Pontifex adds the layer that makes the
server safe to expose.

| | MCP Python SDK | Pontifex MCP |
| --- | --- | --- |
| Define and serve tools | ✅ | ✅ (built on it) |
| Authenticate callers | — | ✅ API keys + OAuth 2.1 |
| Per-caller scopes | — | ✅ `domain:resource:action` |
| Audit log | — | ✅ every call, to Postgres |
| Rate limiting | — | ✅ per caller |
| Resilience (failover, breakers) | — | ✅ |
| Onboard an OpenAPI API with no code | — | ✅ |

## When *not* to use it

Be honest about the fit.

If you're shipping a **single public tool over non-sensitive data**, the MCP SDK on its
own is simpler. You don't need identity, scopes, or an audit trail yet, and adding them
is overhead without a payoff.

Pontifex earns its place the moment **a real system and a real identity are involved** —
the point where unauthenticated access stops being acceptable.

## Is it for you?

| You are… | Start here |
| --- | --- |
| An engineer building a server | [Quickstart](learn/quickstart.md) |
| Onboarding an existing API | [Connect an API](learn/connect-an-api.md) |
| Reviewing the security model | [Security](concepts/security.md) |
| Sizing the architecture | [How a request flows](concepts/request-path.md) |
