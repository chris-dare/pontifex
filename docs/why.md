# Why Pontifex

## The gap

The model is ready. The systems you need it to act on are not.

Your orders API, your customer database, your internal services were built for your
applications and your employees, not for an autonomous agent. Point an agent at them
and your security review asks one thing:

> Who is calling, what can they touch, how often, and what did they do?

MCP, the protocol agents use to call tools, answers none of that. It standardizes the
connection and leaves the control to you. So your team builds a strong pilot, and it
stops at the first system that holds real data.

Pontifex answers those four questions, so you can ship the pilot.

## What it changes

| Without a governance layer | With Pontifex |
| --- | --- |
| An agent's access is all-or-nothing | You scope each caller to the exact tools they need |
| "Trust the agent" | You trust a verified identity on every call |
| No record of what the agent did | A full audit row per call: caller, tool, data source, latency |
| One slow upstream stalls everything | Rate limiting, failover, and circuit breaking contain it |
| Your data flows through a vendor | You self-host; nothing leaves your environment |

Now you can put your name on the sentence "an agent can reach production," because you
control and record every call it makes.

## Built on open standards

Pontifex does not ask you to bet on a platform.

- It builds on the official MCP Python SDK, not a fork or a reimplementation.
- It uses OAuth 2.1 and standard JWTs for identity, so you bring any OIDC provider
  (Auth0, Entra, Clerk, Keycloak).
- It reads OpenAPI to onboard existing systems without code.
- It speaks RFC 9728 and RFC 8693 for discovery and token exchange, with no proprietary
  handshake.

Pair it with any AI vendor. Run it anywhere you run Python. To remove it, drop the
dependency; your tools stay standard MCP underneath.

## You hold the data

Pontifex is a library you run, not a service you send data to.

It sits inside your environment, between the agent and your systems. No third party
sits in the request path. You supply the database, Redis, and provider credentials from
your own environment. Pontifex hardcodes nothing and phones nothing home.

That is what lets your security and compliance teams sign off on "we are connecting AI
to customer data."

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

## When to skip it

If you are shipping a single public tool over non-sensitive data, use the MCP SDK on
its own. You do not need identity, scopes, or an audit trail yet, and adding them buys
you nothing.

Pontifex pays off once a real system and a real identity are involved, the point where
you can no longer accept unauthenticated access.

## Is it for you?

| You are… | Start here |
| --- | --- |
| An engineer building a server | [Quickstart](learn/quickstart.md) |
| Onboarding an existing API | [Connect an API](learn/connect-an-api.md) |
| Reviewing the security model | [Security](concepts/security.md) |
| Sizing the architecture | [How a request flows](concepts/request-path.md) |
