"""How a request carries the credentials of the user a call acts for. What the credentials are is
the `shared` contract `UpstreamCredentials`; how the upstream reads them is decided here."""

from collections.abc import AsyncGenerator
from typing import override

import httpx2

from mcp_skeleton.shared import CredentialsProvider
from mcp_skeleton.shared import UpstreamCredentials


def auth_for(credentials: UpstreamCredentials) -> httpx2.Auth:
    """HTTP Basic auth. Change it to the scheme the upstream expects, such as a header of its
    own: both the sign-in check and every call go through it."""
    return httpx2.BasicAuth(credentials.username, credentials.password.get_secret_value())


class CredentialsAuth(httpx2.Auth):
    """Signs each request with the credentials `provider` returns at the time it is sent."""

    def __init__(self, provider: CredentialsProvider) -> None:
        self._provider: CredentialsProvider = provider

    @override
    async def async_auth_flow(
        self, request: httpx2.Request
    ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        flow = auth_for(await self._provider()).async_auth_flow(request)
        outgoing = await anext(flow)
        while True:
            response = yield outgoing
            try:
                outgoing = await flow.asend(response)
            except StopAsyncIteration:
                return
