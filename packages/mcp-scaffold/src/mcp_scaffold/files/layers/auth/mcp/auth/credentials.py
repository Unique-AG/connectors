"""Who a call acts for, and their credentials for the upstream, read from the store through the
`shared` contract."""

from collections.abc import Callable

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token

from mcp_skeleton.shared import AuthStore
from mcp_skeleton.shared import CredentialsProvider
from mcp_skeleton.shared import UpstreamCredentials

_SIGN_IN_AGAIN = "Your sign-in is no longer valid. Sign in to this MCP again."


def current_subject() -> str:
    """The signed-in user the current call acts for, which FastMCP keeps from their token."""
    token = get_access_token()
    if token is None or token.subject is None:
        raise ToolError(_SIGN_IN_AGAIN)
    return token.subject


def caller_credentials(store: Callable[[], AuthStore]) -> CredentialsProvider:
    """A `CredentialsProvider` that returns the credentials of the user the current call acts for,
    read when the call needs them."""

    async def credentials() -> UpstreamCredentials:
        found = await store().get_credentials(current_subject())
        if found is None:
            raise ToolError(_SIGN_IN_AGAIN)
        return found

    return credentials
