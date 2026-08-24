import httpx
import respx
from kiota_abstractions.request_option import RequestOption
from msgraph.graph_request_adapter import options as sdk_middleware_options
from msgraph.graph_service_client import GraphServiceClient
from msgraph_core import GraphClientFactory

from office_365_mcp.graph_client import GraphSettings, create_graph_transport
from office_365_mcp.graph_client.client import (
    _CallerTokenProvider,  # pyright: ignore[reportPrivateUsage]
)

from .conftest import CALLER_TOKEN, GRAPH_V1, RecordedSleeps


def _handler_chain(transport: httpx.AsyncClient) -> list[str]:
    """Reaches through private attributes: the SDK exposes no assembled pipeline."""
    handler: object = transport._transport  # pyright: ignore[reportPrivateUsage]
    handler = getattr(getattr(handler, "pipeline", None), "_first_middleware", None)
    names: list[str] = []
    while handler is not None:
        names.append(type(handler).__name__)
        handler = getattr(handler, "next", None)
    return names


class TestTheCallersTokenIsWhatCalls:
    async def test_it_is_sent_to_graph_as_a_bearer_token(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get("/me").mock(
            return_value=httpx.Response(200, json={"id": "u-1", "displayName": "Ada Lovelace"})
        )

        user = await client.me.get()

        assert user is not None
        assert user.display_name == "Ada Lovelace"
        assert route.calls.last.request.headers["authorization"] == f"Bearer {CALLER_TOKEN}"

    async def test_nothing_else_is_given_the_token(self) -> None:
        """The SDK's bearer provider never consults the allowed-hosts validator itself, so this is
        all that stands between an off-Graph `@odata.nextLink` and a user's delegated credential."""
        provider = _CallerTokenProvider(CALLER_TOKEN)

        assert await provider.get_authorization_token("https://graph.microsoft.com/v1.0/me")
        assert await provider.get_authorization_token("https://example.invalid/v1.0/me") == ""

    async def test_the_right_host_over_the_wrong_scheme_is_given_nothing_either(self) -> None:
        """`AllowedHostsValidator` compares the hostname and nothing else, so a host check alone
        hands the delegated token to `http://graph.microsoft.com/...` in cleartext."""
        provider = _CallerTokenProvider(CALLER_TOKEN)

        assert await provider.get_authorization_token("http://graph.microsoft.com/v1.0/me") == ""
        assert await provider.get_authorization_token("ftp://graph.microsoft.com/v1.0/me") == ""
        assert await provider.get_authorization_token("//graph.microsoft.com/v1.0/me") == ""


class TestTheGraphBaseUrlIsSetInOnePlace:
    async def test_no_empty_path_segment_reaches_the_wire(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A second base_url produces `https://graph.microsoft.com/v1.0//me`: httpx normalises a
        base_url to end with a slash, `HttpxRequestAdapter` copies the transport's verbatim, and the
        SDK's URL templates join their own leading slash onto it. Graph tolerates the empty
        segment, so nothing fails loudly — hence the assertion on the built URL."""
        route = graph.get("/me").mock(return_value=httpx.Response(200, json={"id": "u-1"}))

        _ = await client.me.get()

        assert str(route.calls.last.request.url) == f"{GRAPH_V1}/me"

    async def test_the_adapter_holds_it_and_the_transport_does_not(
        self, transport: httpx.AsyncClient, client: GraphServiceClient
    ) -> None:
        """An unset transport base_url is what lets the adapter emit an absolute URL httpx never
        joins onto; the adapter's missing trailing slash keeps the join clean if it ever does."""
        # The ignore is for the SDK leaving `request_adapter`'s generic parameter unbound.
        base_url: str = client.request_adapter.base_url  # pyright: ignore[reportUnknownMemberType]

        assert str(transport.base_url) == ""
        assert base_url == GRAPH_V1
        assert not base_url.endswith("/")


class TestThrottling:
    async def test_retry_after_is_waited_out_and_the_call_then_succeeds(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        retry_sleeps: RecordedSleeps,
    ) -> None:
        """The factory installs no middleware on a client it is handed unless asked, and losing
        the retry handler shows up only as intermittent 429s reaching tools."""
        graph.get("/me").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "7"}),
                httpx.Response(200, json={"id": "u-1", "displayName": "Ada Lovelace"}),
            ]
        )

        user = await client.me.get()

        assert user is not None
        assert retry_sleeps.delays == [7], "the wait must be Graph's Retry-After, not a backoff"


class TestTheTransportRunsTheSdksOwnPipeline:
    async def test_it_is_the_sdks_default_chain_with_the_url_replacer_quietened(self) -> None:
        """`_graph_middleware` inlines `GraphClientFactory.create_with_default_middleware`, which
        builds and loads the handler list in one step with no seam to swap a handler into. The cost
        is that a handler the SDK adds in a later version would quietly not be installed."""
        options: dict[str, RequestOption] = {**sdk_middleware_options}
        sdk = GraphClientFactory.create_with_default_middleware(
            client=httpx.AsyncClient(), options=options
        )
        ours = create_graph_transport(GraphSettings())
        try:
            expected = [
                "_QuietUrlReplaceHandler" if name == "UrlReplaceHandler" else name
                for name in _handler_chain(sdk)
            ]
            assert expected, "the SDK's own chain came back empty, so this compares nothing"
            assert _handler_chain(ours) == expected
        finally:
            await sdk.aclose()
            await ours.aclose()
