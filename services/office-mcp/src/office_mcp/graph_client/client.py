"""A Microsoft Graph client for the caller whose access token we were handed.

Nothing here acquires, refreshes, caches or stores a token. FastMCP's `AzureProvider` owns the
OAuth 2.1 proxy and the On-Behalf-Of exchange, and hands a tool the resulting Graph access token
as a string; this module's job is to get that string onto the wire as a bearer header on requests
the official SDK builds.

Two lifetimes, deliberately separated. The token is per call. The HTTP transport is not: an
`httpx.AsyncClient` is a connection pool with the middleware pipeline installed on it, so
building one per Graph call would give every request a cold TLS handshake and leak the pool.
`create_graph_transport` builds it once, `graph_client_for` borrows it per caller.
"""

from typing import override
from urllib.parse import urlparse

import httpx
from kiota_abstractions.authentication import (
    AccessTokenProvider,
    AllowedHostsValidator,
    BaseBearerTokenAuthenticationProvider,
)
from kiota_abstractions.request_option import RequestOption
from kiota_http.middleware.options.retry_handler_option import RetryHandlerOption
from msgraph.graph_request_adapter import GraphRequestAdapter
from msgraph.graph_request_adapter import options as sdk_middleware_options
from msgraph.graph_service_client import GraphServiceClient
from msgraph_core import APIVersion, GraphClientFactory, NationalClouds

from office_mcp.graph_client.settings import GraphSettings

_GRAPH_ORIGIN = str(NationalClouds.Global)
_GRAPH_BASE_URL = f"{_GRAPH_ORIGIN}/{APIVersion.v1}"

_GRAPH_HOSTNAME = urlparse(_GRAPH_ORIGIN).hostname
assert _GRAPH_HOSTNAME is not None, f"national cloud endpoint has no host: {_GRAPH_ORIGIN}"

# The only host a caller's delegated token may be sent to. Shared because it never changes.
_GRAPH_HOSTS = AllowedHostsValidator([_GRAPH_HOSTNAME])


class _CallerTokenProvider(AccessTokenProvider):
    """Kiota's token seam, holding the one token it will ever be asked for.

    This is not an `azure-identity` credential, and that is the point. Handing
    `GraphServiceClient(credentials=...)` a credential looks more idiomatic and is a trap: the
    SDK's own adapter for that path calls `await credentials.close()` after *every* token
    acquisition (`kiota_authentication_azure/azure_identity_access_token_provider.py`), which
    would close the transport of the `OnBehalfOfCredential` FastMCP caches per user — breaking
    that user permanently at the next cache miss, an hour later. The same path also returns an
    empty bearer token for anything that isn't exactly an `azure.core.credentials.AccessToken`,
    which surfaces as an unexplained 401. `AccessTokenProvider` is two methods and has neither
    hazard.
    """

    def __init__(self, access_token: str) -> None:
        self._access_token: str = access_token

    @override
    async def get_authorization_token(
        self,
        uri: str,
        additional_authentication_context: dict[str, object] | None = None,
    ) -> str:
        """The caller's token, for Graph, and for nothing else.

        The host check has to happen here: `BaseBearerTokenAuthenticationProvider` never
        consults the validator itself, so without this a redirect or an `@odata.nextLink`
        pointing off Graph would be sent a user's delegated token. Returning an empty string is
        how this contract declines — the bearer header is then omitted rather than forged.

        `additional_authentication_context` carries a Continuous Access Evaluation claims
        challenge when Graph issues one. It is ignored: satisfying a claims challenge means
        acquiring a *new* token, which is the auth provider's job and not something this type
        could do without becoming the token plumbing it exists to avoid.
        """
        if not _GRAPH_HOSTS.is_url_host_valid(uri):
            return ""
        return self._access_token

    @override
    def get_allowed_hosts_validator(self) -> AllowedHostsValidator:
        return _GRAPH_HOSTS


def create_graph_transport(settings: GraphSettings) -> httpx.AsyncClient:
    """The long-lived HTTP transport every Graph call shares. Close it on shutdown.

    Built through `GraphClientFactory` so the SDK's default middleware pipeline stays intact:
    redirects, retries (which honour `Retry-After` on 429/503/504, on `asyncio.sleep`),
    parameter-name decoding, the `/me` URL rewrite and Graph's telemetry handler. Only the two
    things `GraphSettings` exists for are overridden — and note the factory does not set
    `base_url` when it is given a client, so that is ours too.

    `sdk_middleware_options` is the SDK's own default option set, carried over rather than
    rebuilt: it holds the `/users/me-token-to-replace` → `/me` rewrite that every `client.me`
    call depends on, plus the telemetry handler's SDK version.
    """
    middleware_options: dict[str, RequestOption] = {
        **sdk_middleware_options,
        RetryHandlerOption.get_key(): RetryHandlerOption(max_retries=settings.max_retries),
    }
    return GraphClientFactory.create_with_default_middleware(
        client=httpx.AsyncClient(
            base_url=_GRAPH_BASE_URL,
            timeout=httpx.Timeout(
                settings.request_timeout_seconds,
                connect=settings.connect_timeout_seconds,
            ),
            http2=True,
        ),
        options=middleware_options,
    )


def graph_client_for(transport: httpx.AsyncClient, access_token: str) -> GraphServiceClient:
    """A Graph client that calls as the holder of `access_token`, over the shared `transport`."""
    adapter = GraphRequestAdapter(
        auth_provider=BaseBearerTokenAuthenticationProvider(_CallerTokenProvider(access_token)),
        client=transport,
    )
    # The adapter otherwise takes its base URL from the transport, and httpx normalises any
    # `base_url` to end in a slash — which the SDK's own URL templates (`{+baseurl}/users/...`)
    # then join onto, so every request goes to `/v1.0//users/...`. Graph happens to tolerate the
    # empty path segment; nothing else on the way there is promised to.
    adapter.base_url = _GRAPH_BASE_URL
    return GraphServiceClient(request_adapter=adapter)
