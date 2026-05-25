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

Reads GSE_MCP_DATABASE_URL from the environment.
"""

import argparse
import asyncio
import os
import secrets
import sys

from mcp_core.auth.api_keys import hash_key
from mcp_core.models.db import ApiKeyModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


async def create_key(
    database_url: str,
    key_id: str,
    owner_id: str,
    owner_label: str,
    scopes: list[str],
    plaintext: str,
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
    args = parser.parse_args()

    database_url = os.environ.get("GSE_MCP_DATABASE_URL")
    if not database_url:
        print("ERROR: GSE_MCP_DATABASE_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    plaintext = args.key_plaintext or f"sk_live_{secrets.token_urlsafe(24)}"
    key_id = args.key_id or f"key_{args.owner_id}"
    scopes = [s.strip() for s in args.scopes.split(",")]

    asyncio.run(
        create_key(
            database_url=database_url,
            key_id=key_id,
            owner_id=args.owner_id,
            owner_label=args.owner_label,
            scopes=scopes,
            plaintext=plaintext,
        )
    )

    print(f"key_id:    {key_id}")
    print(f"plaintext: {plaintext}")
    print(f"scopes:    {scopes}")
    print(f"owner:     {args.owner_id} ({args.owner_label})")


if __name__ == "__main__":
    main()
