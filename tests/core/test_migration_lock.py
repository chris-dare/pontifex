"""The migration advisory lock takes effect on Postgres and stays out of the way
on SQLite. Concurrency itself is exercised against real Postgres in the
integration check; here we just pin the dialect behavior."""

from pontifex_mcp.migrations.lock import MIGRATION_LOCK_KEY, lock_for_migration


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeConn:
    """Records SQL passed to execute(), reports a dialect, and lets a test choose
    whether the non-blocking `pg_try_advisory_xact_lock` succeeds."""

    def __init__(self, dialect_name, try_lock_succeeds=True):
        self.dialect = type("Dialect", (), {"name": dialect_name})()
        self.executed = []
        self._try_lock_succeeds = try_lock_succeeds

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params))
        return _FakeResult(self._try_lock_succeeds)


def test_postgres_uncontended_takes_lock_without_blocking():
    conn = _FakeConn("postgresql", try_lock_succeeds=True)
    lock_for_migration(conn)
    # Only the non-blocking try ran; no blocking acquire, no wait.
    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "pg_try_advisory_xact_lock" in sql
    assert params == {"key": MIGRATION_LOCK_KEY}


def test_postgres_contended_falls_back_to_blocking_acquire():
    conn = _FakeConn("postgresql", try_lock_succeeds=False)
    lock_for_migration(conn)
    # Try failed, so it blocks on the real acquire.
    assert len(conn.executed) == 2
    assert "pg_try_advisory_xact_lock" in conn.executed[0][0]
    assert conn.executed[1][0].count("pg_advisory_xact_lock") == 1  # the blocking one
    assert "pg_try" not in conn.executed[1][0]


def test_sqlite_is_a_no_op():
    conn = _FakeConn("sqlite")
    lock_for_migration(conn)
    assert conn.executed == []


def test_lock_key_is_a_stable_signed_64bit_int():
    # Reproducible across processes (it's hashed from a constant), and fits the
    # bigint that pg_advisory_xact_lock expects.
    assert isinstance(MIGRATION_LOCK_KEY, int)
    assert -(2**63) <= MIGRATION_LOCK_KEY < 2**63
