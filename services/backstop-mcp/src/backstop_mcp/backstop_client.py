import base64

import httpx

from backstop_mcp.auth.context import get_current_backstop_credential
from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.config import BackstopConfig

_AUTHORIZATION_HEADER = "authorization"
_TOKEN_HEADER = "token"

# GET /system-info takes no parameters and returns no business data — the cheapest real
# Backstop call that still requires a valid credential, so it doubles as a login-time check.
_VERIFICATION_PATH = "/system-info"


class BackstopUnreachableError(Exception):
    """Raised when Backstop can't be reached at all (network error, 5xx) during verification.

    Distinct from "invalid credentials" (401/403) — the caller should show a different
    message ("Backstop is unreachable, try again") rather than blaming the submitted token.
    """


class BackstopAuthError(Exception):
    """Raised when Backstop rejects the stored credential (401) while calling a real endpoint.

    Unlike `BackstopUnreachableError`, this means the credential itself is no longer valid
    (e.g. the user's personal API token was revoked in Backstop) — the caller should prompt
    the user to reconnect rather than retry.
    """


async def _raise_for_backstop_status(response: httpx.Response) -> None:
    """`httpx` response event hook: auto-raise on every Backstop error response.

    A 401 means the stored credential itself was revoked/expired in Backstop — raised as
    `BackstopAuthError` so tool code can tell it apart from "this specific call failed"
    (any other 4xx/5xx, raised via the normal `httpx.HTTPStatusError`). Attached to every
    client `create_backstop_client` builds, so tool implementations never check status
    codes themselves — see `tools/system_info.py` for an example.
    """
    if response.status_code == 401:
        raise BackstopAuthError("Backstop rejected the stored credential — please reconnect.")
    response.raise_for_status()


def build_auth_headers(username: str, api_token: str) -> dict[str, str]:
    """Build the `Authorization: Basic ...` + `token: true` headers Backstop expects.

    Every user connects with a personal API token (not a password), so `token: true` is
    always sent — see https://backstopsolutions.elevio.help/en/articles/1018 and .../236.
    """
    basic_auth = base64.b64encode(f"{username}:{api_token}".encode()).decode()
    return {_AUTHORIZATION_HEADER: f"Basic {basic_auth}", _TOKEN_HEADER: "true"}


def create_backstop_client(
    base_url: str, credential: BackstopCredentialSecret
) -> httpx.AsyncClient:
    headers = build_auth_headers(credential.username, credential.api_token.get_secret_value())
    return httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        event_hooks={"response": [_raise_for_backstop_status]},
    )


async def get_backstop_client() -> httpx.AsyncClient:
    """Build a Backstop API client authenticated as the current MCP caller.

    Call this from within a tool implementation, where an authenticated request is active.
    Resolves the caller's own stored credential via `auth.context` — raises
    `auth.context.NotConnectedError` if they haven't completed the login flow. Every
    response the returned client makes is auto-checked (see `_raise_for_backstop_status`).
    """
    credential = await get_current_backstop_credential()
    return create_backstop_client(BackstopConfig().base_url, credential)


async def verify_credential(username: str, api_token: str, base_url: str) -> bool:
    """Check whether a Backstop username + personal API token actually authenticates.

    Called from the login form's submit handler (see `auth/provider.py`) before minting an
    authorization code. Returns True/False for a definite valid/invalid answer; raises
    `BackstopUnreachableError` if Backstop itself couldn't be reached (network error, 5xx) —
    that's not the same failure mode as "wrong token" and should be shown to the user
    differently.
    """
    headers = build_auth_headers(username, api_token)

    try:
        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.get(_VERIFICATION_PATH, headers=headers)
    except httpx.RequestError as exc:
        raise BackstopUnreachableError(f"Could not reach Backstop at {base_url}") from exc

    if response.status_code == 200:
        return True
    if response.status_code in (401, 403):
        return False

    raise BackstopUnreachableError(
        f"Backstop returned unexpected status {response.status_code} while verifying credentials"
    )
