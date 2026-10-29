import pytest

from mcp_credential_auth.redirect_policy import (
    RedirectTarget,
    RedirectUriPolicy,
    describe_redirect_target,
)

_POLICY = RedirectUriPolicy()


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://claude.ai/api/mcp/auth_callback",
        "https://claude.com/api/mcp/auth_callback",
        "https://chatgpt.com/connector_platform_oauth_redirect",
        "https://chatgpt.com/connector/oauth/abc123",
        "https://www.cursor.com/agents/mcp/oauth/callback",
        "https://vscode.dev/redirect",
        "https://insiders.vscode.dev/redirect",
        "https://CLAUDE.AI./api/mcp/auth_callback",
        "cursor://anysphere.cursor-mcp/oauth/callback",
    ],
)
def test_allows_supported_client_callbacks(redirect_uri: str) -> None:
    assert _POLICY.rejection_reason(redirect_uri) is None


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://localhost:3118/callback",
        "http://localhost/callback",
        "http://127.0.0.1:33418/",
        "http://127.0.0.1:8787/callback",
        "http://[::1]:51234/callback",
        "https://localhost:8443/callback",
    ],
)
def test_allows_loopback_on_any_port(redirect_uri: str) -> None:
    assert _POLICY.rejection_reason(redirect_uri) is None


@pytest.mark.parametrize(
    ("redirect_uri", "reason"),
    [
        (
            "https://attacker.example/callback",
            "has host attacker.example, which is not on the allowlist",
        ),
        (
            "https://claude.ai.attacker.example/cb",
            "has host claude.ai.attacker.example, which is not on the allowlist",
        ),
        (
            "http://claude.ai/api/mcp/auth_callback",
            "uses http on a host other than localhost, 127.0.0.1 or [::1]",
        ),
        ("https://user@claude.ai/api/mcp/auth_callback", "has userinfo"),
        ("http://localhost@attacker.example/cb", "has userinfo"),
        ("myapp://callback", "uses the myapp scheme, which is not on the allowlist"),
    ],
)
def test_rejects_hosts_and_schemes_off_the_allowlist(redirect_uri: str, reason: str) -> None:
    assert _POLICY.rejection_reason(redirect_uri) == reason


@pytest.mark.parametrize(
    ("redirect_uri", "scheme"),
    [
        ("javascript:alert(1)", "javascript"),
        ("JavaScript:alert(1)", "javascript"),
        ("data:text/html,<script>alert(1)</script>", "data"),
        ("file:///etc/passwd", "file"),
        ("vbscript:msgbox", "vbscript"),
    ],
)
def test_rejects_unsafe_schemes(redirect_uri: str, scheme: str) -> None:
    assert _POLICY.rejection_reason(redirect_uri) == f"uses the {scheme}: scheme"


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://claude.ai/api/mcp/auth_callback#frag",
        "http://localhost:3000/callback#",
        "cursor://anysphere.cursor-mcp/oauth/callback#x",
    ],
)
def test_rejects_fragments(redirect_uri: str) -> None:
    assert _POLICY.rejection_reason(redirect_uri) == "has a fragment"


def test_custom_allowlist_replaces_the_default() -> None:
    policy = RedirectUriPolicy(allowed_hosts=["Mcp.Example.COM"], allowed_schemes=[])

    assert policy.allows("https://mcp.example.com/callback")
    assert not policy.allows("https://claude.ai/api/mcp/auth_callback")
    assert not policy.allows("cursor://anysphere.cursor-mcp/oauth/callback")
    assert policy.allows("http://127.0.0.1:9999/callback")


@pytest.mark.parametrize("scheme", ["https", "http", "javascript", "data", "file"])
def test_refuses_to_allowlist_web_or_unsafe_schemes(scheme: str) -> None:
    with pytest.raises(ValueError, match="cannot be allowlisted"):
        RedirectUriPolicy(allowed_schemes=[scheme])


@pytest.mark.parametrize(
    ("redirect_uri", "target"),
    [
        (
            "https://claude.ai/api/mcp/auth_callback",
            RedirectTarget(host="claude.ai", on_this_device=False),
        ),
        (
            "http://localhost:3118/callback",
            RedirectTarget(host="localhost", on_this_device=True),
        ),
        ("http://[::1]:5000/cb", RedirectTarget(host="::1", on_this_device=True)),
        (
            "cursor://anysphere.cursor-mcp/oauth/callback",
            RedirectTarget(host="cursor://anysphere.cursor-mcp", on_this_device=True),
        ),
    ],
)
def test_describes_redirect_target(redirect_uri: str, target: RedirectTarget) -> None:
    assert describe_redirect_target(redirect_uri) == target
