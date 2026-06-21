"""The migration advisory lock takes effect on Postgres and stays out of the way
on SQLite. Concurrency itself is exercised against real Postgres in the
integration check; here we just pin the dialect behavior."""

from pontifex_mcp.migrations.lock import MIGRATION_LOCK_KEY, lock_for_migration


class _FakeConn:
    """Records SQL passed to execute(), and reports a dialect name."""

    def __init__(self, dialect_name):
        self.dialect = type("Dialect", (), {"name": dialect_name})()
        self.executed = []

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params))


def test_postgres_takes_the_advisory_lock():
    conn = _FakeConn("postgresql")
    lock_for_migration(conn)
    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "pg_advisory_xact_lock" in sql
    assert params == {"key": MIGRATION_LOCK_KEY}


def test_sqlite_is_a_no_op():
    conn = _FakeConn("sqlite")
    lock_for_migration(conn)
    assert conn.executed == []


def test_lock_key_is_a_stable_signed_64bit_int():
    # Reproducible across processes (it's hashed from a constant), and fits the
    # bigint that pg_advisory_xact_lock expects.
    assert isinstance(MIGRATION_LOCK_KEY, int)
    assert -(2**63) <= MIGRATION_LOCK_KEY < 2**63
