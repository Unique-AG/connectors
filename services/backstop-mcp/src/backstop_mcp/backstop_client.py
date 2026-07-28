from collections.abc import Mapping

import httpx
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from backstop_mcp.config import BackstopConfig

_AUTHORIZATION_HEADER = "authorization"
_TOKEN_HEADER = "token"


class MissingBackstopCredentialsError(ToolError):
    """Raised when the connecting MCP client didn't supply Backstop credentials."""


def extract_backstop_auth_headers(request_headers: Mapping[str, str]) -> dict[str, str]:
    """Pull the caller's own Backstop Basic Auth headers out of the incoming MCP request.

    Each connecting client authenticates as themselves: they must send their own
    `Authorization: Basic <base64(username:password-or-token)>` header (and, for SSO
    users authenticating with an API token, a `token: true` header) when calling this
    MCP server. Those headers are forwarded to the Backstop REST API unchanged — see
    https://backstopsolutions.elevio.help/en/articles/1018 and .../236.
    """
    authorization = request_headers.get(_AUTHORIZATION_HEADER)
    if not authorization or not authorization.startswith("Basic "):
        raise MissingBackstopCredentialsError(
            "Missing 'Authorization: Basic <credentials>' header — connect with your own "
            + "Backstop username/password or username/API-token credentials."
        )

    headers = {_AUTHORIZATION_HEADER: authorization}
    if request_headers.get(_TOKEN_HEADER) == "true":
        headers[_TOKEN_HEADER] = "true"
    return headers


def create_backstop_client(base_url: str, request_headers: Mapping[str, str]) -> httpx.AsyncClient:
    headers = extract_backstop_auth_headers(request_headers)
    return httpx.AsyncClient(base_url=base_url, headers=headers)


def get_backstop_client(config: BackstopConfig) -> httpx.AsyncClient:
    """Build a Backstop API client scoped to the current MCP request's caller.

    Call this from within a tool implementation, where an HTTP request is active.
    """
    return create_backstop_client(config.base_url, get_http_headers())
