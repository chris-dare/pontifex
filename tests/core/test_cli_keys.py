"""`pontifex-mcp keys` — create / list / revoke, exercised against a SQLite file
(the command works identically on Postgres; only the engine URL differs)."""

import sqlite3

import pytest
from pontifex_mcp.auth.api_keys import hash_key
from pontifex_mcp.cli import app
from pontifex_mcp.cli._output import ExitCode
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "keys.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    return path


def _rows(path):
    return (
        sqlite3.connect(path)
        .execute("SELECT key_id, key_hash, owner_id, is_active FROM api_keys ORDER BY key_id")
        .fetchall()
    )


def test_create_mints_key_and_stores_only_the_hash(db):
    result = runner.invoke(
        app,
        [
            "keys",
            "create",
            "--owner",
            "usr_k",
            "--scopes",
            "payments:balance:read",
            "--key-plaintext",
            "sk_dev_x",
        ],  # gitleaks:allow
    )
    assert result.exit_code == 0, result.output
    assert "sk_dev_x" in result.output  # plaintext shown once

    rows = _rows(db)
    assert len(rows) == 1
    key_id, key_hash, owner_id, is_active = rows[0]
    assert (key_id, owner_id, is_active) == ("key_usr_k", "usr_k", 1)
    assert key_hash == hash_key("sk_dev_x")  # hash stored...
    assert "sk_dev_x" not in key_hash  # ...never the plaintext


def test_create_generates_random_key_when_no_plaintext(db):
    result = runner.invoke(app, ["keys", "create", "--owner", "u", "--scopes", "a:b"])
    assert result.exit_code == 0
    assert "sk_live_" in result.output


def test_create_rejects_empty_scopes(db):
    result = runner.invoke(app, ["keys", "create", "--owner", "u", "--scopes", " , "])
    assert result.exit_code == int(ExitCode.USER_ERROR)


def test_create_duplicate_key_id_is_user_error(db):
    args = ["keys", "create", "--owner", "u", "--scopes", "a:b", "--key-id", "key_dup"]
    assert runner.invoke(app, args).exit_code == 0
    dup = runner.invoke(app, args)
    assert dup.exit_code == int(ExitCode.USER_ERROR)
    assert "already exists" in dup.output


def test_list_shows_keys_and_hides_revoked(db):
    runner.invoke(app, ["keys", "create", "--owner", "a", "--scopes", "x:y", "--key-id", "key_a"])
    runner.invoke(app, ["keys", "create", "--owner", "b", "--scopes", "x:y", "--key-id", "key_b"])
    runner.invoke(app, ["keys", "revoke", "key_b"])

    listed = runner.invoke(app, ["keys", "list"])
    assert listed.exit_code == 0
    assert "key_a" in listed.output
    assert "key_b" not in listed.output  # revoked hidden by default

    all_keys = runner.invoke(app, ["keys", "list", "--all"])
    assert "key_b" in all_keys.output
    assert "revoked" in all_keys.output


def test_list_empty_is_clean(db):
    result = runner.invoke(app, ["keys", "list"])
    assert result.exit_code == 0
    assert "No keys" in result.output


def test_revoke_soft_deletes(db):
    runner.invoke(app, ["keys", "create", "--owner", "a", "--scopes", "x:y", "--key-id", "key_a"])
    result = runner.invoke(app, ["keys", "revoke", "key_a"])
    assert result.exit_code == 0
    # Soft delete: row stays, is_active flips to 0 (audit history preserved).
    rows = _rows(db)
    assert rows[0][0] == "key_a"
    assert rows[0][3] == 0


def test_revoke_missing_key_is_user_error(db):
    result = runner.invoke(app, ["keys", "revoke", "key_nope"])
    assert result.exit_code == int(ExitCode.USER_ERROR)
    assert "No key" in result.output


class _FakeRedis:
    def __init__(self):
        self.deleted = []

    async def delete(self, key):
        self.deleted.append(key)

    async def aclose(self):
        pass


def test_revoke_invalidates_redis_cache(db, monkeypatch):
    """With REDIS_URL set, revoke must clear the resolver's `apikey:<hash>` entry
    so the key stops authenticating immediately, not after the cache TTL."""
    import redis.asyncio

    runner.invoke(
        app,
        [
            "keys",
            "create",
            "--owner",
            "a",
            "--scopes",
            "x:y",
            "--key-id",
            "key_a",
            "--key-plaintext",
            "sk_a",
        ],  # gitleaks:allow
    )
    fake = _FakeRedis()
    monkeypatch.setattr(redis.asyncio, "from_url", lambda _url: fake)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    result = runner.invoke(app, ["keys", "revoke", "key_a"])
    assert result.exit_code == 0
    assert fake.deleted == [f"apikey:{hash_key('sk_a')}"]  # gitleaks:allow


def test_keys_create_missing_database_url_exits_infra(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = runner.invoke(app, ["keys", "create", "--owner", "u", "--scopes", "a:b"])
    assert result.exit_code == int(ExitCode.INFRA_ERROR)
