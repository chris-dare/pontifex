def scopes_match(scopes: list[str], namespace: str, resource: str, action: str) -> bool:
    """Return True if any scope in `scopes` permits namespace:resource:action.

    Supported patterns:
      - {namespace}:*:*               full namespace access
      - {namespace}:*:{action}        all resources, specific action
      - {namespace}:{resource}:*      specific resource, all actions
      - {namespace}:{resource}:{action}   exact match

    Scope comparison is case-insensitive. A bare `*` is NOT a global wildcard
    here — open/anonymous access is granted by `CallerIdentity.anonymous`, not by
    a scope string, so a `*` leaking onto a real JWT/API-key grants nothing.
    """
    namespace_l = namespace.lower()
    resource_l = resource.lower()
    action_l = action.lower()
    patterns = {
        f"{namespace_l}:*:*",
        f"{namespace_l}:*:{action_l}",
        f"{namespace_l}:{resource_l}:*",
        f"{namespace_l}:{resource_l}:{action_l}",
    }
    return any(s.lower() in patterns for s in scopes)
