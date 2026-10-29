from collections.abc import Iterable
from typing import ClassVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

# Callback hosts of the hosted MCP clients we support. Sources:
# - claude.ai, claude.com: https://claude.com/docs/connectors/building/authentication#callback-urls
#   (`https://claude.ai/api/mcp/auth_callback`, announced to move to claude.com)
# - chatgpt.com: https://developers.openai.com/apps-sdk/build/auth
#   (`/connector_platform_oauth_redirect` and `/connector/oauth/{callback_id}`)
# - cursor.com, www.cursor.com: Cursor registers its cloud callback
#   `https://www.cursor.com/agents/mcp/oauth/callback` alongside its loopback and `cursor://` ones
# - vscode.dev, insiders.vscode.dev: VS Code registers `https://vscode.dev/redirect` and
#   `https://insiders.vscode.dev/redirect` alongside its loopback one
DEFAULT_ALLOWED_REDIRECT_HOSTS: tuple[str, ...] = (
    "claude.ai",
    "claude.com",
    "chatgpt.com",
    "cursor.com",
    "www.cursor.com",
    "vscode.dev",
    "insiders.vscode.dev",
)

# Private-use URI schemes (RFC 8252 §7.1) that open a desktop app. Cursor registers
# `cursor://anysphere.cursor-mcp/oauth/callback` in the same request as its loopback URI, so the
# whole registration fails without it.
DEFAULT_ALLOWED_REDIRECT_SCHEMES: tuple[str, ...] = ("cursor",)

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_WEB_SCHEMES = frozenset({"http", "https"})

# Schemes a browser executes or reads locally instead of handing to an app. Refused even when an
# operator lists them, since a redirect there is never a callback.
_UNSAFE_SCHEMES = frozenset({"javascript", "data", "file", "vbscript", "blob", "about"})


def _normalize_host(host: str) -> str:
    return host.strip().lower().removesuffix(".")


class RedirectTarget(BaseModel):
    """Where a redirect URI sends the browser, in the words the login page shows."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    host: str
    on_this_device: bool


class RedirectUriPolicy:
    """Decides which redirect URIs a dynamically registered client may use.

    Registration is open, so the redirect URI is the only thing tying an authorization code to a
    real client. Without a policy, anyone can register a client named "Claude" whose redirect URI
    they own, and a victim who signs in on our genuine login page hands them the code.

    Accepted: `http` or `https` on a loopback host with any port (RFC 8252 §7.3, native clients),
    `https` on an allowlisted host, and allowlisted private-use schemes. Everything else, and any
    URI with a fragment (RFC 6749 §3.1.2) or userinfo, is refused.
    """

    _allowed_hosts: frozenset[str]
    _allowed_schemes: frozenset[str]

    def __init__(
        self,
        *,
        allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_REDIRECT_HOSTS,
        allowed_schemes: Iterable[str] = DEFAULT_ALLOWED_REDIRECT_SCHEMES,
    ) -> None:
        self._allowed_hosts = frozenset(_normalize_host(host) for host in allowed_hosts if host)
        self._allowed_schemes = frozenset(
            scheme.strip().lower() for scheme in allowed_schemes if scheme
        )
        refused = self._allowed_schemes & (_WEB_SCHEMES | _UNSAFE_SCHEMES)
        if refused:
            raise ValueError(
                f"Redirect schemes {sorted(refused)} cannot be allowlisted; "
                + "list https hosts instead"
            )

    def rejection_reason(self, redirect_uri: str) -> str | None:
        """Why `redirect_uri` is refused, or None when it is allowed."""
        try:
            parts = urlsplit(redirect_uri)
            host = parts.hostname
        except ValueError:
            return "is not a valid URL"
        scheme = parts.scheme.lower()

        if scheme in _UNSAFE_SCHEMES:
            return f"uses the {scheme}: scheme"
        if "#" in redirect_uri:
            return "has a fragment"
        if parts.username is not None or parts.password is not None:
            return "has userinfo"

        if scheme in _WEB_SCHEMES:
            normalized = _normalize_host(host or "")
            if normalized in _LOOPBACK_HOSTS:
                return None
            if scheme == "http":
                return "uses http on a host other than localhost, 127.0.0.1 or [::1]"
            if normalized in self._allowed_hosts:
                return None
            return f"has host {normalized or '(none)'}, which is not on the allowlist"

        if scheme in self._allowed_schemes:
            return None
        return f"uses the {scheme or '(no)'} scheme, which is not on the allowlist"

    def allows(self, redirect_uri: str) -> bool:
        return self.rejection_reason(redirect_uri) is None


def describe_redirect_target(redirect_uri: str) -> RedirectTarget:
    """The host the login page names as where the user is sent after signing in.

    A private-use scheme and a loopback host both reach an app on the user's own machine, which
    the MCP authorization spec asks the consent screen to say, since any local process can claim
    to be the client.
    """
    parts = urlsplit(redirect_uri)
    scheme = parts.scheme.lower()
    host = _normalize_host(parts.hostname or "")
    if scheme in _WEB_SCHEMES:
        return RedirectTarget(host=host, on_this_device=host in _LOOPBACK_HOSTS)
    return RedirectTarget(host=f"{scheme}://{host}" if host else f"{scheme}:", on_this_device=True)
