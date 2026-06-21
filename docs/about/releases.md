# Versioning & releases

Pontifex is published to PyPI as
[`pontifex-mcp`](https://pypi.org/project/pontifex-mcp/) and developed in the open at
[chris-dare/pontifex](https://github.com/chris-dare/pontifex).

```bash
uv add pontifex-mcp        # or: pip install pontifex-mcp
```

## What's stable

The **supported public surface** is everything importable from
`pontifex_mcp`, listed in the [Python API reference](../reference/python-api.md).

Anything reached through a deeper path (`pontifex_mcp.middleware`, `pontifex_mcp.auth`,
…) is an internal detail and may change without a major-version bump. Import from the
top level and you're on the supported path.

## Versioning

Releases follow semantic versioning. Pontifex is in active development, and we work to
keep upgrades boring. Most releases are additive — your tools, scopes, and API keys keep
working untouched. When something genuinely has to break, it's deliberate: a minor version
with step-by-step migration in the [Upgrading](upgrading.md) guide. Pin the version you
depend on.

Each release is published as a **GitHub Release** with notes describing what changed
and a compare link to the previous tag. That's the changelog. There's no separate
`CHANGELOG.md` to drift out of sync.

[**Release notes on GitHub →**](https://github.com/chris-dare/pontifex/releases)

## License

Apache-2.0. Use it, fork it, embed it in a commercial product. See the LICENSE file for the full terms.
