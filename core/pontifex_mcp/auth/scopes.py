def scopes_match(scopes: list[str], domain: str, resource: str, action: str) -> bool:
    """Return True if any scope in `scopes` permits domain:resource:action.

    Supported patterns:
      - {domain}:*:*               full domain access
      - {domain}:*:{action}        all resources, specific action
      - {domain}:{resource}:*      specific resource, all actions
      - {domain}:{resource}:{action}   exact match

    Scope comparison is case-insensitive.
    """
    domain_l = domain.lower()
    resource_l = resource.lower()
    action_l = action.lower()
    patterns = {
        f"{domain_l}:*:*",
        f"{domain_l}:*:{action_l}",
        f"{domain_l}:{resource_l}:*",
        f"{domain_l}:{resource_l}:{action_l}",
    }
    return any(s.lower() in patterns for s in scopes)
