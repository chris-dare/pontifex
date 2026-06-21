# Use with your coding agent

`pontifex-mcp` bundles an official [Agent Skill](https://library-skills.io) in the
package: a `SKILL.md` that teaches a coding agent how to build with it. The skill covers
the `PontifexMCP` facade, `namespace:resource:action` scopes, API-key and JWT auth, the
`pontifex-mcp` CLI, caching, and generating tools from an OpenAPI spec.

The skill ships and versions with the library, so your agent reads guidance that matches
the version you installed. Upgrade the package and the guidance moves with it.

## Install the skill

Add the package, then run [`library-skills`](https://library-skills.io) to wire the skill
into your project:

```bash
uv add pontifex-mcp        # or: pip install pontifex-mcp
uvx library-skills         # scans your dependencies, installs the skills you pick
```

or just install the specific skill for pontifex mcp
```bash
uvx library-skills -s pontifex-mcp --yes
```

`library-skills` scans your installed dependencies, finds the ones that ship a skill, and
links each into `.agents/skills/`, the shared directory that Codex, Cursor, GitHub Copilot,
OpenCode, and other agents read. That one command covers them all.

Claude Code reads its own `.claude/skills/` directory, so it takes a dedicated flag `--claude`:

```bash
uvx library-skills -s pontifex-mcp --claude --yes
```

Either way, the link points back at the installed package, so the skill stays current as
you upgrade.

## What your agent gets

The skill loads when you ask your agent to work with pontifex-mcp. It walks the build
path: `PontifexMCP`, `@mcp.tool(scope=...)`, `ApiKeyAuth` and `JwtAuth`, the CLI, caching,
and OpenAPI tool generation. It also pins down the conventions an agent tends to miss from
memory, like the decorator needing parentheses and the SQLite-to-Postgres switch being a
config change. For moving across breaking releases, it carries the
[upgrade steps](../about/upgrading.md).
