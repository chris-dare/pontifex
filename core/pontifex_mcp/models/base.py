from datetime import datetime

from pydantic import BaseModel, Field


class RateLimitInfo(BaseModel):
    limit: int
    remaining: int
    reset: int  # Unix epoch seconds


class ToolResponse(BaseModel):
    """Wrapper metadata returned with every tool call."""

    timestamp: datetime
    source: str
    is_live: bool
    cache_hit: bool = False
    rate_limit: RateLimitInfo | None = None


class AuditRecord(BaseModel):
    """In-memory representation before writing to Postgres."""

    timestamp: datetime
    domain: str
    key_id: str
    owner_id: str
    owner_label: str
    transport: str
    tool_name: str
    tool_params: dict = Field(default_factory=dict)
    data_source: str
    cache_hit: bool
    response_ms: int
    error: str | None = None
    ip_address: str | None = None
    delegated_audience: str | None = None


class ToolError(BaseModel):
    error_code: str
    message: str
    status: int
    retry: bool
    retry_after_seconds: int | None = None
    detail: str | None = None
