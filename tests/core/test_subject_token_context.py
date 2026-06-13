"""Subject-token resolution for the stdio / no-request path.

The HTTP path (request.state.subject_token) is covered in test_auth_middleware;
this covers the ContextVar fallback that mirrors resolve_caller.
"""

from pontifex_mcp.auth.context import resolve_subject_token, set_stdio_subject_token


def test_resolves_none_by_default():
    set_stdio_subject_token(None)
    assert resolve_subject_token(None) is None


def test_resolves_stdio_token_when_no_ctx():
    set_stdio_subject_token("eyJstdio.token")
    try:
        assert resolve_subject_token(None) == "eyJstdio.token"
    finally:
        set_stdio_subject_token(None)


def test_ctx_without_request_falls_back_to_stdio():
    set_stdio_subject_token("eyJfallback")
    try:
        # An object whose request_context raises AttributeError -> stdio fallback.
        assert resolve_subject_token(object()) == "eyJfallback"
    finally:
        set_stdio_subject_token(None)
