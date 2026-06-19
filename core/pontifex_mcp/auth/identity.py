from dataclasses import dataclass, field

from pontifex_mcp.auth.scopes import scopes_match


@dataclass
class CallerIdentity:
    key_id: str
    owner_id: str
    owner_label: str
    scopes: list[str] = field(default_factory=list)
    rate_limit_rpm: int = 60
    transport: str = "http"
    # Set ONLY by `anonymous_identity()` for backendless/open servers. It can
    # never arrive from a JWT claim or an API-key row (both omit it, so it
    # defaults False) — so the scope bypass is tied to in-process construction,
    # not to attacker- or operator-controlled data. Fail-closed by default.
    anonymous: bool = False

    def can_use_tool(self, domain: str, resource: str, action: str) -> bool:
        if self.anonymous:
            return True
        return scopes_match(self.scopes, domain, resource, action)


def anonymous_identity(transport: str = "http") -> CallerIdentity:
    """The caller used when no auth backend is configured.

    `anonymous=True` makes scope checks pass (scopes are advisory in this mode);
    the `["*"]` scope list is a human-facing marker for audit, not the mechanism
    that grants access. Injecting this — rather than leaving the caller
    unresolved — keeps scope enforcement and audit on the normal path; the tool
    runtime treats an unresolved caller as a denied request.
    """
    return CallerIdentity(
        key_id="anonymous",
        owner_id="anonymous",
        owner_label="Anonymous",
        scopes=["*"],
        rate_limit_rpm=9999,
        transport=transport,
        anonymous=True,
    )
