from dataclasses import dataclass, field

from mcp_core.auth.scopes import scopes_match


@dataclass
class CallerIdentity:
    key_id: str
    owner_id: str
    owner_label: str
    scopes: list[str] = field(default_factory=list)
    rate_limit_rpm: int = 60
    transport: str = "http"

    def can_use_tool(self, domain: str, resource: str, action: str) -> bool:
        return scopes_match(self.scopes, domain, resource, action)
