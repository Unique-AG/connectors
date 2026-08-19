"""Microsoft Graph client for one caller's delegated token.

This module does not acquire, refresh, cache or store tokens. FastMCP's AzureProvider owns the
OAuth 2.1 proxy and On-Behalf-Of exchange; this module sends the resulting access token as a
bearer header on Graph requests via the official SDK.

The token is per call. The HTTP transport is shared: it is a connection pool with the SDK's
middleware pipeline. Building one per call causes a cold TLS handshake per call and leaks the pool.
`create_graph_transport` builds it once; `graph_client_for` wraps it per caller.
"""

from collections.abc import Awaitable, Callable
from typing import override
from urllib.parse import urlparse

import httpx
from kiota_abstractions.authentication import (
    AccessTokenProvider,
    AllowedHostsValidator,
    BaseBearerTokenAuthenticationProvider,
)
from kiota_abstractions.request_option import RequestOption
from kiota_http.kiota_client_factory import KiotaClientFactory
from kiota_http.middleware.middleware import BaseMiddleware
from kiota_http.middleware.options.retry_handler_option import RetryHandlerOption
from kiota_http.middleware.url_replace_handler import UrlReplaceHandler
from kiota_http.observability_options import ObservabilityOptions
from msgraph.graph_request_adapter import GraphRequestAdapter
from msgraph.graph_request_adapter import options as sdk_middleware_options
from msgraph.graph_service_client import GraphServiceClient
from msgraph_core import APIVersion, GraphClientFactory, NationalClouds
from msgraph_core.middleware import GraphTelemetryHandler
from msgraph_core.middleware.options import GraphTelemetryHandlerOption
from opentelemetry.trace import Span

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
# `/users/{user}/onlineMeetings/{meeting}/transcripts/{transcript}`, and a
# `?$filter=JoinWebUrl eq ...` carrying the tenant id. A trace backend keeps span attributes for
# weeks and is read by anyone who can read traces, so with tracing switched on those ids leave the
# pod. Turned off here; `url.uri_template` stays, and a template is what a latency breakdown is
# grouped by anyway.
#
# This option reaches the request span only. The other place the SDK sets `url.full` does not
# consult it — see `_QuietUrlReplaceHandler`, which is the rest of the same decision.
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


# `BaseMiddleware.send` hands the request to the next handler in the pipeline, or to the transport
# when there is none. It carries no annotations, so it is named once here with the signature the SDK
# implements — the alternative is an ignore comment at each call.
#
# Reached this way rather than as `super().send` from the handler below, because `super()` there is
# the very method being replaced.
_pass_to_the_next_handler: Callable[  # pyright: ignore[reportUnknownVariableType]
    [BaseMiddleware, httpx.Request, httpx.AsyncBaseTransport], Awaitable[httpx.Response]
] = BaseMiddleware.send  # pyright: ignore[reportUnknownMemberType]


class _QuietUrlReplaceHandler(UrlReplaceHandler):
    """The SDK's `/me` URL rewrite, without the rewritten URL on the span it opens.

    `_NO_EUII_SPAN_ATTRIBUTES` cannot reach this one. `UrlReplaceHandler.send` sets `url.full` on
    its own span without consulting `ObservabilityOptions` at all
    (kiota_http/middleware/url_replace_handler.py:44), and that URL is the same chat, message,
    meeting and transcript ids the request span was cleaned of. The handler also carries the
    `/users/me-token-to-replace` → `/me` rewrite every `client.me` call depends on, so switching
    it off is not an option — hence a subclass rather than a removal.

    Trap: `send` below mirrors `UrlReplaceHandler.send` (url_replace_handler.py:35-47) minus that
    one `set_attribute` line. On an SDK bump, re-read that method: whatever it gains has to be
    gained here too, or this handler silently stops doing it.
    """

    @override
    async def send(
        self,
        request: httpx.Request,
        transport: httpx.AsyncBaseTransport,
    ) -> httpx.Response:
        # The ignore below is for an unannotated `request` parameter on
        # `BaseMiddleware._create_observability_span`, which makes the call partially unknown. Its
        # return type is annotated, hence the `Span` here.
        span: Span = self._create_observability_span(  # pyright: ignore[reportUnknownMemberType]
            request, "UrlReplaceHandler_send"
        )
        if self.options and self.options.is_enabled:
            span.set_attribute("com.microsoft.kiota.handler.url_replacer.enable", True)
            # Design decision: the request is mutated, which the house rule against mutating
            # arguments would otherwise forbid. A kiota middleware has no return path for a
            # replacement request — the pipeline hands the one object down the chain — so the
            # rewrite is only expressible in place, and in place is where the SDK does it.
            request.url = httpx.URL(
                self.replace_url_segment(str(request.url), self._get_current_options(request))
            )
        response = await _pass_to_the_next_handler(self, request, transport)
        span.end()
        return response


def _graph_middleware(options: dict[str, RequestOption]) -> list[BaseMiddleware]:
    """The SDK's default Graph pipeline with the URL replacer swapped for the quiet one.

    Trap: this is `GraphClientFactory.create_with_default_middleware` inlined
    (msgraph_core/graph_client_factory.py:54-56), because that method builds the handler list and
    loads it onto the client in one step and leaves no seam to swap a handler in. A handler the SDK
    adds to that method in a later version does not appear here — re-read it on a bump.
    """
    telemetry_option = options[GraphTelemetryHandlerOption.get_key()]
    assert isinstance(telemetry_option, GraphTelemetryHandlerOption), (
        "the Graph SDK's telemetry option is missing from the middleware options"
    )
    quietened = [
        _QuietUrlReplaceHandler(options=handler.options)
        if isinstance(handler, UrlReplaceHandler)
        else handler
        for handler in KiotaClientFactory.get_default_middleware(options)
    ]
    return [*quietened, GraphTelemetryHandler(options=telemetry_option)]


def create_graph_transport(settings: GraphSettings) -> httpx.AsyncClient:
    """Shared HTTP transport for all Graph calls. Close on shutdown.

    Built via `GraphClientFactory` to preserve the SDK's middleware pipeline: redirects, retries
    (honouring Retry-After on 429/503/504, on asyncio.sleep, so a wait never blocks the event
    loop), parameter decoding, `/me` URL rewrite, and telemetry. Only the two things
    GraphSettings controls are overridden, plus the one handler `_graph_middleware` quietens. The
    factory does not set base_url when given a client, so base_url above is ours to set too.

    `sdk_middleware_options` carries the `/users/me-token-to-replace` → `/me` rewrite that
    `client.me` calls depend on, plus the telemetry handler's SDK version. Carry it over rather
    than rebuild it.
    """
    middleware_options: dict[str, RequestOption] = {
        **sdk_middleware_options,
        RetryHandlerOption.get_key(): RetryHandlerOption(max_retries=settings.max_retries),
    }
    return GraphClientFactory.create_with_custom_middleware(
        middleware=_graph_middleware(middleware_options),
        client=httpx.AsyncClient(
            base_url=_GRAPH_BASE_URL,
            timeout=httpx.Timeout(
                settings.request_timeout_seconds,
                connect=settings.connect_timeout_seconds,
            ),
            http2=True,
        ),
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
    # This closes the request span only. The other place the SDK sets `url.full` never reads these
    # options; `_QuietUrlReplaceHandler`, installed on the transport, is what closes that one. See
    # `tests/graph_client/test_spans.py`, which asserts over both.
    adapter.observability_options = _NO_EUII_SPAN_ATTRIBUTES
    return GraphServiceClient(request_adapter=adapter)
