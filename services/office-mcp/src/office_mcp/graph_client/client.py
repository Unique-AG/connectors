"""Microsoft Graph client for one caller's delegated token.

This module does not acquire, refresh, cache or store tokens. FastMCP's AzureProvider owns the
OAuth 2.1 proxy and On-Behalf-Of exchange; this module sends the resulting access token as a
bearer header on Graph requests via the official SDK.

The token is per call. The HTTP transport is shared: it is a connection pool with the SDK's
middleware pipeline. Building one per call causes a cold TLS handshake per call and leaks the pool.
`create_graph_transport` builds it once; `graph_client_for` wraps it per caller.
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
from kiota_http.observability_options import ObservabilityOptions
from msgraph.graph_request_adapter import GraphRequestAdapter
from msgraph.graph_request_adapter import options as sdk_middleware_options
from msgraph.graph_service_client import GraphServiceClient
from msgraph_core import APIVersion, GraphClientFactory, NationalClouds

from office_mcp.graph_client.settings import GraphSettings

_GRAPH_ORIGIN = str(NationalClouds.Global)
_GRAPH_BASE_URL = f"{_GRAPH_ORIGIN}/{APIVersion.v1}"

_GRAPH_HOSTNAME = urlparse(_GRAPH_ORIGIN).hostname
assert _GRAPH_HOSTNAME is not None, f"national cloud endpoint has no host: {_GRAPH_ORIGIN}"

# Only host allowed to receive the caller's delegated token.
_GRAPH_HOSTS = AllowedHostsValidator([_GRAPH_HOSTNAME])

# Kiota calls a Graph URL "EUII" and puts it on every request span as `url.full` by default
# (`ObservabilityOptions.include_euii_attributes`, kiota_http/observability_options.py:9). In this
# service that URL *is* the sensitive part: `/chats/{chat}/messages/{message}`,
# `/users/{user}/onlineMeetings/{meeting}/transcripts/{transcript}`. A trace backend keeps span
# attributes for weeks and is read by anyone who can read traces, so with tracing switched on those
# ids leave the pod. Turned off here; `url.uri_template` stays, and a template is what a latency
# breakdown is grouped by anyway.
#
# One instance, not one per call: `graph_client_for` runs per request, and the object is only ever
# read.
_NO_EUII_SPAN_ATTRIBUTES = ObservabilityOptions(include_euii_attributes=False)


class _CallerTokenProvider(AccessTokenProvider):
    """Kiota token provider holding a single delegated token.

    TRAP: Do not pass an `azure-identity` credential to `GraphServiceClient`. The SDK calls
    `await credentials.close()` after every token acquisition. This closes FastMCP's cached
    `OnBehalfOfCredential` transport. The closed transport breaks the user permanently, at the
    next cache miss, about an hour later. The user must sign in again to recover. That same
    path also returns an empty bearer token for anything that isn't exactly an
    `azure.core.credentials.AccessToken`, which surfaces as an unexplained 401. This provider is
    two methods and has neither hazard.
    """

    def __init__(self, access_token: str) -> None:
        self._access_token: str = access_token

    @override
    async def get_authorization_token(
        self,
        uri: str,
        additional_authentication_context: dict[str, object] | None = None,
    ) -> str:
        """The caller's delegated token for Graph only.

        TRAP: The host check must happen here. `BaseBearerTokenAuthenticationProvider` does not
        consult the allowed-hosts validator, so redirects and @odata.nextLink URLs pointing off
        Graph would receive the user's delegated token. Returning an empty string is how this
        contract declines — the bearer header is then omitted rather than forged.

        Continuous Access Evaluation context is ignored. Satisfying claims challenges requires
        acquiring a new token, which is the auth provider's job, not this type's.
        """
        if not _GRAPH_HOSTS.is_url_host_valid(uri):
            return ""
        return self._access_token

    @override
    def get_allowed_hosts_validator(self) -> AllowedHostsValidator:
        return _GRAPH_HOSTS


def create_graph_transport(settings: GraphSettings) -> httpx.AsyncClient:
    """Shared HTTP transport for all Graph calls. Close on shutdown.

    Built via `GraphClientFactory` to preserve the SDK's middleware pipeline: redirects, retries
    (honouring Retry-After on 429/503/504, on asyncio.sleep, so a wait never blocks the event
    loop), parameter decoding, `/me` URL rewrite, and telemetry. Only the two things
    GraphSettings controls are overridden. The factory does not set base_url when given a
    client, so base_url above is ours to set too.

    `sdk_middleware_options` carries the `/users/me-token-to-replace` → `/me` rewrite that
    `client.me` calls depend on, plus the telemetry handler's SDK version. Carry it over rather
    than rebuild it.
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
    """Graph client calling as the holder of access_token via the shared transport."""
    adapter = GraphRequestAdapter(
        auth_provider=BaseBearerTokenAuthenticationProvider(_CallerTokenProvider(access_token)),
        client=transport,
    )
    # TRAP: without this line, the adapter takes base_url from the transport instead. httpx
    # normalises base_url to end with a slash. The SDK's URL templates then join onto it,
    # causing `/v1.0//users/...`. Graph tolerates the empty path segment; nothing else on the
    # way there is promised to.
    adapter.base_url = _GRAPH_BASE_URL
    # Assigned rather than passed: `GraphRequestAdapter.__init__` takes only an auth provider and a
    # client, and drops its base class's `observability_options` parameter on the floor
    # (msgraph/graph_request_adapter.py:22-26). The attribute is public and is read once per
    # request, well after construction, so setting it here is the same kind of correction as the
    # base_url above.
    #
    # Trap: this does not close every leak. `UrlReplaceHandler` sets `url.full` on its own span
    # without consulting these options at all (kiota_http/middleware/url_replace_handler.py:44), and
    # that handler carries the `/me` rewrite, so it cannot be switched off. Removing that one needs
    # either an upstream fix or a span filter where the tracer provider is built. See
    # `tests/graph_client/test_spans.py`.
    adapter.observability_options = _NO_EUII_SPAN_ATTRIBUTES
    return GraphServiceClient(request_adapter=adapter)
