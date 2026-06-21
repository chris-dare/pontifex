"""Serialize concurrent migration runs.

`pontifex-mcp db upgrade` is meant to drop into a deploy pipeline, but nothing
stops two replicas from running it at the same moment. Alembic doesn't lock
across the whole upgrade, so a race can surface as a duplicate-object error on
one of them. A Postgres transaction-scoped advisory lock fixes that: the first
process holds it and runs the migrations, the rest wait, then see an up-to-date
schema and no-op. The lock releases automatically when the migration
transaction ends — no manual unlock, no leak on crash.

SQLite is single-writer and never reaches this path, so the helper is a no-op
there (and on any non-Postgres dialect).
"""

import hashlib

import structlog
from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = structlog.get_logger(__name__)

# A stable, app-specific 64-bit key derived from the schema name, so our lock
# doesn't collide with another application's advisory locks in a shared database.
# Derived (not a magic number) so it's reproducible and self-documenting.
MIGRATION_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"pontifex_mcp_core:migrations").digest()[:8], "big", signed=True
)


def lock_for_migration(connection: Connection) -> None:
    """Take the migration advisory lock on Postgres; no-op on other dialects.

    Call it inside the migration transaction, before applying migrations, so the
    lock is held for the whole upgrade and released when the transaction ends.

    Tries without blocking first, so the common uncontended case is silent. Only
    when another process holds the lock does it log and then wait — so a deploy
    stuck behind a long-running migration is diagnosable, not a mystery.
    """
    if connection.dialect.name != "postgresql":
        return
    acquired = connection.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
    ).scalar()
    if acquired:
        return
    logger.info(
        "migration_lock_wait",
        msg="another process is running migrations; waiting for the advisory lock",
    )
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
