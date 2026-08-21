"""Microsoft Graph client for one caller's delegated token.

This module acquires, refreshes, caches and stores no tokens. FastMCP's AzureProvider owns the
OAuth 2.1 proxy and the On-Behalf-Of exchange. This module sends the resulting access token as a
bearer header on Graph requests, through the official SDK.

The token is per call. The HTTP transport is shared, because it is a connection pool with the SDK's
middleware pipeline: one per call would mean a cold TLS handshake per call and a leaked pool.
`create_graph_transport` builds it once, `graph_client_for` wraps it per caller.
"""

from collections.abc import Mapping
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
from opentelemetry.semconv.attributes.url_attributes import URL_FULL
from opentelemetry.trace import Span, SpanContext, Status, StatusCode
from opentelemetry.util.types import AttributeValue

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
# pod. Turned off here. `url.uri_template` stays, and a template is what a latency breakdown is
# grouped by anyway.
#
# This option reaches the request span only. See `_QuietUrlReplaceHandler` for the other place the
# SDK sets `url.full`.
#
# One instance, not one per call: `graph_client_for` runs per request and only ever reads it.
_NO_EUII_SPAN_ATTRIBUTES = ObservabilityOptions(include_euii_attributes=False)


class _CallerTokenProvider(AccessTokenProvider):
    """Kiota token provider holding a single delegated token.

    Hand-written because `kiota_abstractions` ships no static-token provider. Pairing a custom
    `AccessTokenProvider` with `BaseBearerTokenAuthenticationProvider` is the construction Microsoft
    documents for a bearer token: "Use a custom access token provider with the Base bearer token
    authentication provider", https://learn.microsoft.com/en-us/openapi/kiota/authentication.
    microsoftgraph/msgraph-sdk-python#501 is the open, maintainer-acknowledged issue tracking the
    missing documentation for this scenario.

    TRAP: do not pass an `azure-identity` credential to `GraphServiceClient` instead. For an async
    credential the SDK calls `await credentials.close()` after every token acquisition, inside `if
    inspect.isawaitable(result):`
    (kiota_authentication_azure/azure_identity_access_token_provider.py:113-115), so a sync
    credential never reaches it but FastMCP's cached `OnBehalfOfCredential` is async and does. That
    closes the credential's transport, which breaks the user permanently at the next cache miss
    about an hour later, and only a fresh sign-in recovers it. This provider owns a string, so
    there is nothing to close.
    """

    def __init__(self, access_token: str) -> None:
        self._access_token: str = access_token

    @override
    async def get_authorization_token(
        self,
        uri: str,
        additional_authentication_context: dict[str, object] | None = None,
    ) -> str:
        """The caller's delegated token for Graph over https only.

        TRAP: the check must happen here. `BaseBearerTokenAuthenticationProvider` does not consult
        the allowed-hosts validator at all. The URL reaching this method is not always one this
        service composed: an `@odata.nextLink` comes back inside a response body and re-enters
        `send_async`, which authenticates the follow-up page afresh, so a nextLink pointing off
        Graph is what the host check is live against. Redirects are not. The auth provider is
        consulted once per logical request (kiota_http/httpx_request_adapter.py:593 and :708),
        before the request enters the middleware pipeline at :600, and `RedirectHandler` loops
        entirely inside that pipeline without re-entering authentication.

        The scheme check is separate and equally load-bearing, because `AllowedHostsValidator`
        compares the hostname alone (kiota_abstractions/authentication/allowed_hosts_validator.py):
        without it, `http://graph.microsoft.com/...` matches the allowed host and the delegated
        token goes out in cleartext. The SDK's own `AzureIdentityAccessTokenProvider` refuses the
        same case by raising `HTTPError("Only https is supported")`
        (kiota_authentication_azure/azure_identity_access_token_provider.py:80-84). This provider
        declines instead: `""` is already how its contract says "no token", and
        `BaseBearerTokenAuthenticationProvider` omits the header for `""`, so there is one refusal
        shape rather than two. Its localhost exemption is moot here, because the host check rejects
        localhost first. Neither check looks at the port.

        Continuous Access Evaluation context is ignored. Satisfying claims challenges requires a
        new token, which is the auth provider's job.
        """
        if urlparse(uri).scheme != "https" or not _GRAPH_HOSTS.is_url_host_valid(uri):
            return ""
        return self._access_token

    @override
    def get_allowed_hosts_validator(self) -> AllowedHostsValidator:
        return _GRAPH_HOSTS


class _SpanWithoutTheUrl(Span):
    """A span that forwards everything to the real one except a `url.full` attribute.

    Only the two attribute setters filter, and they filter on one key. `Span` is an ABC with nine
    abstract methods plus `add_link`, so the delegation is spelled out rather than inherited.
    """

    def __init__(self, span: Span) -> None:
        self._span: Span = span

    @override
    def set_attribute(self, key: str, value: AttributeValue) -> None:
        if key != URL_FULL:
            self._span.set_attribute(key, value)

    @override
    def set_attributes(self, attributes: Mapping[str, AttributeValue]) -> None:
        self._span.set_attributes({k: v for k, v in attributes.items() if k != URL_FULL})

    @override
    def end(self, end_time: int | None = None) -> None:
        self._span.end(end_time)

    @override
    def get_span_context(self) -> SpanContext:
        return self._span.get_span_context()

    @override
    def is_recording(self) -> bool:
        return self._span.is_recording()

    @override
    def update_name(self, name: str) -> None:
        self._span.update_name(name)

    @override
    def set_status(self, status: Status | StatusCode, description: str | None = None) -> None:
        self._span.set_status(status, description)

    @override
    def add_event(
        self,
        name: str,
        attributes: Mapping[str, AttributeValue] | None = None,
        timestamp: int | None = None,
    ) -> None:
        self._span.add_event(name, attributes, timestamp)

    @override
    def add_link(
        self,
        context: SpanContext,
        attributes: Mapping[str, AttributeValue] | None = None,
    ) -> None:
        self._span.add_link(context, attributes)

    @override
    def record_exception(
        self,
        exception: BaseException,
        attributes: Mapping[str, AttributeValue] | None = None,
        timestamp: int | None = None,
        escaped: bool = False,
    ) -> None:
        self._span.record_exception(exception, attributes, timestamp, escaped)


class _QuietUrlReplaceHandler(UrlReplaceHandler):
    """The SDK's `/me` URL rewrite, without the rewritten URL on the span it opens.

    `_NO_EUII_SPAN_ATTRIBUTES` cannot reach this one. `UrlReplaceHandler.send` sets `url.full` on
    its own span without consulting `ObservabilityOptions` at all
    (kiota_http/middleware/url_replace_handler.py:44), and that URL carries the same chat, message,
    meeting and transcript ids the request span was cleaned of. The handler also carries the
    `/users/me-token-to-replace` → `/me` rewrite every `client.me` call depends on, so switching it
    off is not an option. Hence a subclass rather than a removal.

    No documented switch turns that one line off. `URL_FULL` is written in exactly two places in
    the whole SDK, and only the request adapter's (kiota_http/httpx_request_adapter.py:673-674)
    honours `ObservabilityOptions.include_euii_attributes`. url_replace_handler.py:44 writes it
    unconditionally, and `ObservabilityOptions` is never plumbed into the middleware chain at all.

    So the span the handler writes to is intercepted, rather than the method that writes to it.
    `_create_observability_span` is itself an underscore-prefixed method on `BaseMiddleware`
    (kiota_http/middleware/middleware.py:66), so this swaps one private-SDK dependency for another.
    It is the better one: the SDK's own `send` then runs unmodified, so whatever an msgraph or
    kiota bump adds to it is inherited instead of silently lost, which a hand-copy of `send` could
    not promise. The residual risk moves to the wrapper's surface. It covers `set_attribute` and
    `set_attributes`, and a third spelling upstream would have to be covered too.
    `tests/graph_client/test_spans.py` asserts over real SDK calls that no span carries `url.full`
    or a resource id, so a new spelling fails there.
    """

    @override
    def _create_observability_span(self, request: httpx.Request, span_name: str) -> Span:
        # The ignore is for the base method's unannotated `request` parameter, which makes the call
        # partially unknown. Its return type is annotated, hence the `Span` above.
        return _SpanWithoutTheUrl(
            super()._create_observability_span(  # pyright: ignore[reportUnknownMemberType]
                request, span_name
            )
        )


def _graph_middleware(options: dict[str, RequestOption]) -> list[BaseMiddleware]:
    """The SDK's default Graph pipeline with the URL replacer swapped for the quiet one.

    Trap: this inlines `GraphClientFactory.create_with_default_middleware`
    (msgraph_core/graph_client_factory.py:54-56), which builds the handler list and loads it onto
    the client in one step, leaving no seam to swap a handler in. A handler the SDK adds to that
    method later does not appear here. Re-read it on a bump.
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
    """Shared HTTP transport for all Graph calls.

    Built via `GraphClientFactory` to keep the SDK's middleware pipeline: redirects, retries
    (honouring Retry-After on 429, 503 and 504, on `asyncio.sleep`, so a wait never blocks the event
    loop), parameter decoding, `/me` URL rewrite, and telemetry. Only what `GraphSettings` controls
    is overridden, plus the one handler `_graph_middleware` quietens.

    No base_url here on purpose. `graph_client_for` sets the one that is used, and says why.

    `sdk_middleware_options` carries the `/users/me-token-to-replace` → `/me` rewrite that
    `client.me` calls depend on, plus the telemetry handler's SDK version. Carry it over rather
    than rebuild it.

    `await client.aclose()` does not close the underlying connection pool. The SDK wraps it in
    `AsyncGraphTransport`, which defines no `aclose` of its own and so inherits
    `httpx.AsyncBaseTransport.aclose`, whose body is `pass`
    (msgraph_core/middleware/async_graph_transport.py, httpx/_transports/base.py:85-86). Open
    upstream bug: microsoft/kiota-python#494. The pool goes when the process does.
    """
    middleware_options: dict[str, RequestOption] = {
        **sdk_middleware_options,
        RetryHandlerOption.get_key(): RetryHandlerOption(max_retries=settings.max_retries),
    }
    return GraphClientFactory.create_with_custom_middleware(
        middleware=_graph_middleware(middleware_options),
        client=httpx.AsyncClient(
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
    # TRAP: this is the only place the Graph base URL is set, and it has to stay that way.
    # `HttpxRequestAdapter.__init__` copies the transport's base_url verbatim
    # (kiota_http/httpx_request_adapter.py:90), and httpx normalises a base_url it is given to end
    # with a slash, so giving the transport one puts `https://graph.microsoft.com/v1.0//chats/...`
    # on the wire: an empty path segment Graph tolerates and nothing else on the way there promises
    # to. `create_graph_transport` therefore leaves the transport's base_url empty, the adapter
    # emits an absolute URL, and httpx never consults its own. Nothing fills the gap behind us:
    # `create_with_custom_middleware` sets a base_url only when it builds the client itself, which
    # it does not when handed one (msgraph_core/graph_client_factory.py:83-85).
    adapter.base_url = _GRAPH_BASE_URL
    # Assigned rather than passed: `GraphRequestAdapter.__init__` takes only an auth provider and a
    # client, and drops its base class's `observability_options` parameter
    # (msgraph/graph_request_adapter.py:22-26). The attribute is public and is read once per
    # request, well after construction, so setting it here is as good as passing it.
    #
    # This closes the request span only. `_QuietUrlReplaceHandler` on the transport closes the other
    # place the SDK sets `url.full`. `tests/graph_client/test_spans.py` asserts over both.
    adapter.observability_options = _NO_EUII_SPAN_ATTRIBUTES
    return GraphServiceClient(request_adapter=adapter)
