#!/usr/bin/env python3
"""Create an API key in the MCP platform database.

Usage:
    # Generate a random key:
    python scripts/create_api_key.py \
        --owner-id usr_ci --owner-label "CI test" --scopes "gse:*:*"

    # Use a specific plaintext key (for deterministic UAT keys):
    python scripts/create_api_key.py \
        --owner-id usr_uat --owner-label "UAT test" --scopes "gse:*:*" \
        --key-plaintext sk_test_uat_fixed

Reads DATABASE_URL from the environment.
"""

import argparse
import asyncio
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta

from pontifex_mcp.auth.api_keys import hash_key
from pontifex_mcp.models.db import ApiKeyModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


async def create_key(
    database_url: str,
    key_id: str,
    owner_id: str,
    owner_label: str,
    scopes: list[str],
    plaintext: str,
    expires_at: datetime | None = None,
) -> None:
    engine = create_async_engine(database_url)
    async with AsyncSession(engine) as session:
        record = ApiKeyModel(
            key_id=key_id,
            key_hash=hash_key(plaintext),
            owner_id=owner_id,
            owner_label=owner_label,
            scopes=scopes,
            rate_limit_rpm=120,
            is_active=True,
            expires_at=expires_at,
        )
        session.add(record)
        await session.commit()
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an MCP platform API key")
    parser.add_argument("--owner-id", required=True, help="Owner identifier (e.g. usr_ci)")
    parser.add_argument("--owner-label", required=True, help="Human-readable label")
    parser.add_argument("--scopes", required=True, help="Comma-separated scopes (e.g. gse:*:*)")
    parser.add_argument(
        "--key-plaintext",
        default=None,
        help="Use this plaintext key instead of generating a random one",
    )
    parser.add_argument(
        "--key-id",
        default=None,
        help="Key ID (default: auto-generated from owner-id)",
    )
    parser.add_argument(
        "--expires-in-days",
        type=int,
        default=None,
        help="Expire the key after N days (default: no expiry). Recommended for production keys.",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    plaintext = args.key_plaintext or f"sk_live_{secrets.token_urlsafe(24)}"
    key_id = args.key_id or f"key_{args.owner_id}"
    scopes = [s.strip() for s in args.scopes.split(",")]
    expires_at = (
        datetime.now(UTC) + timedelta(days=args.expires_in_days)
        if args.expires_in_days is not None
        else None
    )

    asyncio.run(
        create_key(
            database_url=database_url,
            key_id=key_id,
            owner_id=args.owner_id,
            owner_label=args.owner_label,
            scopes=scopes,
            plaintext=plaintext,
            expires_at=expires_at,
        )
    )

    print(f"key_id:    {key_id}")
    print(f"plaintext: {plaintext}")
    print(f"scopes:    {scopes}")
    print(f"owner:     {args.owner_id} ({args.owner_label})")
    print(f"expires:   {expires_at.isoformat() if expires_at else 'never'}")


if __name__ == "__main__":
    main()
