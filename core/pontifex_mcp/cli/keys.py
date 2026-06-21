"""`pontifex-mcp keys` — create, list, and revoke API keys.

Works against whatever `DATABASE_URL` points at (SQLite or Postgres). The
plaintext key is shown once on create; only its SHA-256 hash is stored.
"""

import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import typer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from pontifex_mcp.auth.api_keys import hash_key
from pontifex_mcp.cli._db import async_command, resolve_database_url
from pontifex_mcp.cli._output import ExitCode, fail, print_json
from pontifex_mcp.models.db import ApiKeyModel
from pontifex_mcp.storage import (
    create_db_engine,
    ensure_sqlite_schema,
    is_sqlite,
    normalize_db_url,
)

app = typer.Typer(no_args_is_help=True, help="Create, list, and revoke API keys.")


@app.callback()
def keys() -> None:
    """Create, list, and revoke API keys."""


async def _engine_for(url: str) -> AsyncEngine:
    """Engine for `DATABASE_URL`; auto-creates the tables on the SQLite floor.

    Postgres is Alembic-managed — if the tables are missing the operation fails
    with a clear "run db upgrade" message rather than creating them here.
    """
    engine = create_db_engine(url)
    if is_sqlite(url):
        await ensure_sqlite_schema(engine)
    return engine


def _is_missing_table(exc: Exception) -> bool:
    """True for Postgres 'undefined table' (SQLSTATE 42P01) — the schema hasn't
    been migrated yet. Reads the stable SQLSTATE off the wrapped DBAPI error
    rather than matching message text, so it survives driver/version changes.
    """
    orig = getattr(exc, "orig", None)
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return code == "42P01"


def _db_fail(exc: Exception) -> NoReturn:
    if _is_missing_table(exc):
        # The common first-run slip: Postgres reached, but `db upgrade` not run.
        # A clean one-liner beats dumping the INSERT + bound params at the user.
        fail(
            "The database schema isn't set up yet. Run `pontifex-mcp db upgrade` first.",
            ExitCode.INFRA_ERROR,
        )
    fail(
        f"Could not reach the database: {exc}\n"
        "Check DATABASE_URL points at a running database and the credentials are valid.",
        ExitCode.INFRA_ERROR,
    )


async def _invalidate_resolver_cache(key_hash: str) -> None:
    """Drop the resolver's `apikey:<hash>` Redis entry so a revoke takes effect
    immediately, not after the lookup cache TTL.

    Best-effort: the DB revoke has already committed, so a Redis hiccup here must
    not fail the command — the entry just expires on its own TTL instead.
    """
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return
    import redis.asyncio as redis
    from redis.exceptions import RedisError

    client = redis.from_url(redis_url)
    try:
        await client.delete(f"apikey:{key_hash}")
    except (OSError, RedisError) as exc:
        typer.echo(
            f"warning: revoked in the database, but could not clear the Redis cache "
            f"entry ({exc}); it expires on its own within the cache TTL.",
            err=True,
        )
    finally:
        await client.aclose()


@app.command()
@async_command
async def create(
    owner: str = typer.Option(..., "--owner", help="Owner identifier, e.g. usr_kwame."),
    scopes: str = typer.Option(
        ..., "--scopes", help="Comma-separated scopes, e.g. payments:balance:read."
    ),
    label: str = typer.Option(
        "", "--label", help="Human-readable owner label (defaults to --owner)."
    ),
    key_id: str = typer.Option("", "--key-id", help="Key id (default: key_<owner>)."),
    rate_limit_rpm: int = typer.Option(60, "--rate-limit-rpm", help="Per-caller requests/minute."),
    expires_in_days: int | None = typer.Option(
        None, "--expires-in-days", help="Expire after N days (default: never)."
    ),
    key_plaintext: str = typer.Option(
        "",
        "--key-plaintext",
        help="Use this exact key instead of generating one (reproducible CI/UAT keys).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
) -> None:
    """Mint an API key. The plaintext is shown once; only its hash is stored."""
    url = normalize_db_url(resolve_database_url())
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    if not scope_list:
        fail("No scopes given. Pass --scopes like payments:balance:read.", ExitCode.USER_ERROR)
    for scope in scope_list:
        # API-key scopes are enforced as the full namespace:resource:action triple
        # (wildcards allowed in resource/action). A 2-part scope or a bare `*`
        # would mint a key that can never match a tool — reject it at create time.
        parts = scope.split(":")
        if len(parts) != 3 or not all(p.strip() for p in parts):
            fail(
                f"Invalid scope {scope!r}: API-key scopes are 'namespace:resource:action' "
                "(e.g. payments:balance:read, payments:*:read, payments:*:*).",
                ExitCode.USER_ERROR,
            )

    plaintext = key_plaintext or f"sk_live_{secrets.token_urlsafe(24)}"
    kid = key_id or f"key_{owner}"
    expires_at = (
        datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days is not None else None
    )

    engine = await _engine_for(url)
    try:
        async with AsyncSession(engine) as session:
            session.add(
                ApiKeyModel(
                    key_id=kid,
                    key_hash=hash_key(plaintext),
                    owner_id=owner,
                    owner_label=label or owner,
                    scopes=scope_list,
                    rate_limit_rpm=rate_limit_rpm,
                    is_active=True,
                    expires_at=expires_at,
                )
            )
            await session.commit()
    except IntegrityError:
        # Two unique constraints can trip this: the key_id (PK) or the key_hash
        # (reusing a --key-plaintext). Name both rather than blame the key_id.
        fail(
            f"A key with key_id '{kid}' or this key value already exists. "
            "Use a different --key-id, or omit --key-plaintext to generate a fresh key.",
            ExitCode.USER_ERROR,
        )
    except (OSError, SQLAlchemyError) as exc:
        _db_fail(exc)
    finally:
        await engine.dispose()

    if json_output:
        print_json(
            {
                "key_id": kid,
                "api_key": plaintext,
                "owner_id": owner,
                "scopes": scope_list,
                "expires_at": expires_at.isoformat() if expires_at else None,
            }
        )
    else:
        typer.echo(f"key_id:   {kid}")
        typer.echo(f"api_key:  {plaintext}   (shown once — store it now)")
        typer.echo(f"owner:    {owner} ({label or owner})")
        typer.echo(f"scopes:   {', '.join(scope_list)}")
        typer.echo(f"expires:  {expires_at.isoformat() if expires_at else 'never'}")


@app.command(name="list")
@async_command
async def list_keys(
    show_all: bool = typer.Option(False, "--all", help="Include revoked keys."),
    json_output: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
) -> None:
    """List API keys (key_id, owner, scopes, active, expires). Never the secret."""
    url = normalize_db_url(resolve_database_url())
    engine = await _engine_for(url)
    try:
        async with AsyncSession(engine) as session:
            stmt = select(ApiKeyModel).order_by(ApiKeyModel.created_at)
            if not show_all:
                stmt = stmt.where(ApiKeyModel.is_active.is_(True))
            rows = list((await session.execute(stmt)).scalars().all())
    except (OSError, SQLAlchemyError) as exc:
        _db_fail(exc)
    finally:
        await engine.dispose()

    if json_output:
        print_json(
            [
                {
                    "key_id": r.key_id,
                    "owner_id": r.owner_id,
                    "scopes": list(r.scopes),
                    "is_active": r.is_active,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                }
                for r in rows
            ]
        )
        return

    if not rows:
        typer.echo("No keys.")
        return
    width = max(len(r.key_id) for r in rows)
    for r in rows:
        state = "active" if r.is_active else "revoked"
        expires = r.expires_at.date().isoformat() if r.expires_at else "never"
        typer.echo(
            f"{r.key_id:<{width}}  {state:<7}  expires:{expires}  "
            f"{r.owner_id}  [{', '.join(r.scopes)}]"
        )


@app.command()
@async_command
async def revoke(
    key_id: str = typer.Argument(..., help="The key_id to revoke (from `keys list`)."),
    json_output: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
) -> None:
    """Revoke a key. Soft delete (is_active=False) so audit history is preserved.

    Takes effect immediately: the resolver's Redis cache entry is cleared too, so
    a revoked key stops authenticating at once rather than after the cache TTL.
    """
    url = normalize_db_url(resolve_database_url())
    engine = await _engine_for(url)
    key_hash = ""
    try:
        async with AsyncSession(engine) as session:
            row = (
                await session.execute(select(ApiKeyModel).where(ApiKeyModel.key_id == key_id))
            ).scalar_one_or_none()
            if row is None:
                fail(
                    f"No key with key_id '{key_id}'. Run `pontifex-mcp keys list` to see them.",
                    ExitCode.USER_ERROR,
                )
            key_hash = row.key_hash
            row.is_active = False
            await session.commit()
    except (OSError, SQLAlchemyError) as exc:
        _db_fail(exc)
    finally:
        await engine.dispose()

    await _invalidate_resolver_cache(key_hash)

    if json_output:
        print_json({"key_id": key_id, "status": "revoked"})
    else:
        typer.echo(f"Revoked {key_id}.")
