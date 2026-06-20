from datetime import datetime

from sqlalchemy import ARRAY, JSON, BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# The same models run on both Postgres (production, Alembic-managed,
# schema-per-domain) and SQLite (quickstart/local, create_all, no schemas).
# Rather than downgrade the Postgres column types — which would diverge from the
# existing migrations and force new ones — each Postgres-specific type is kept
# via `.with_variant(..., "postgresql")` and falls back to a portable type on
# SQLite. So Postgres DDL is unchanged (JSONB / text[] / INET / BIGINT) and
# SQLite gets JSON / JSON / TEXT / INTEGER. See `pontifex_mcp.storage` for the
# dialect detection and the SQLite `pontifex_mcp_core` → default schema translation.


class Base(DeclarativeBase):
    pass


class ApiKeyModel(Base):
    __tablename__ = "api_keys"
    __table_args__ = {"schema": "pontifex_mcp_core"}

    key_id: Mapped[str] = mapped_column(String, primary_key=True)
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    owner_label: Mapped[str] = mapped_column(String, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        JSON().with_variant(ARRAY(String), "postgresql"), nullable=False
    )
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditLogModel(Base):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "pontifex_mcp_core"}

    # BigInteger compiles to BIGINT on both dialects, but on SQLite a BIGINT
    # primary key is NOT the rowid alias, so it won't autoincrement. The sqlite
    # variant maps it to INTEGER (= rowid alias) so inserts auto-assign; Postgres
    # keeps BIGINT / BIGSERIAL.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # `index=True` gives portable single-column indexes on the SQLite floor
    # (create_all). Postgres is Alembic-managed and intentionally diverges: the
    # migration builds composite `(col, timestamp DESC)` indexes tuned for the
    # "latest rows for X" audit queries. Columns/nullability/keys stay in parity
    # across both dialects; only audit_log's index *shape* differs, by design.
    domain: Mapped[str] = mapped_column(String, nullable=False, index=True)
    key_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    owner_label: Mapped[str] = mapped_column(String, nullable=False)
    transport: Mapped[str] = mapped_column(String, nullable=False)
    tool_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tool_params: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    data_source: Mapped[str] = mapped_column(String, nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(
        String().with_variant(INET, "postgresql"), nullable=True
    )
    # When the call reached its backend via per-user OAuth token exchange, the
    # downstream audience the user's credential was delegated to (never the
    # token itself). Null for hand-written and service-credential tools.
    delegated_audience: Mapped[str | None] = mapped_column(String, nullable=True)


class DomainRegistryModel(Base):
    __tablename__ = "domain_registry"
    __table_args__ = {"schema": "pontifex_mcp_core"}

    domain: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
