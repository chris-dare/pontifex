"""Stub: export audit_log rows older than 90 days to Parquet, then delete.

This is a placeholder; a real implementation would use pyarrow/fastparquet and
write to S3. Run nightly via cron.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from mcp_core.config import CoreSettings
from mcp_core.models.db import AuditLogModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

CUTOFF_DAYS = 90


async def main() -> None:
    settings = CoreSettings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cutoff = datetime.now(UTC) - timedelta(days=CUTOFF_DAYS)

    async with factory() as session:
        rows = (
            (await session.execute(select(AuditLogModel).where(AuditLogModel.timestamp < cutoff)))
            .scalars()
            .all()
        )
        # TODO: write `rows` to Parquet at s3://.../audit/{year}/{month}/...
        print(f"would export {len(rows)} rows older than {cutoff.isoformat()}")
        await session.execute(delete(AuditLogModel).where(AuditLogModel.timestamp < cutoff))
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
