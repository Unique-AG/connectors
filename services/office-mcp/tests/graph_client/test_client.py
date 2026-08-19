import httpx
import respx
from kiota_abstractions.request_option import RequestOption
from msgraph.graph_request_adapter import options as sdk_middleware_options
from msgraph.graph_service_client import GraphServiceClient
from msgraph_core import GraphClientFactory

from office_mcp.graph_client import GraphSettings, create_graph_transport
from office_mcp.graph_client.client import (
    _CallerTokenProvider,  # pyright: ignore[reportPrivateUsage]
)

from .conftest import CALLER_TOKEN, RecordedSleeps


def _handler_chain(transport: httpx.AsyncClient) -> list[str]:
    """The class names of the middleware a transport will run, in order.

    Reaches through the SDK's private attributes because there is no public way to see an assembled
    pipeline, and the assembled pipeline is the thing worth seeing here.
    """
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
        """A `@odata.nextLink` or a redirect pointing off Graph must not be handed the token.

        The SDK's bearer provider never consults the allowed-hosts validator itself, so this is
        the only thing standing between a redirected request and a user's delegated credential.
        """
        provider = _CallerTokenProvider(CALLER_TOKEN)

        assert await provider.get_authorization_token("https://graph.microsoft.com/v1.0/me")
        assert await provider.get_authorization_token("https://example.invalid/v1.0/me") == ""


class TestThrottling:
    async def test_retry_after_is_waited_out_and_the_call_then_succeeds(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        retry_sleeps: RecordedSleeps,
    ) -> None:
        """Graph's throttling contract, which the SDK's own retry middleware implements.

        Asserted here because the transport is built with a custom `httpx.AsyncClient`, and the
        factory does not install any middleware on a client it is handed unless asked — so
        losing the retry handler is a one-line mistake with no other symptom than intermittent
        429s reaching tools.
        """
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
        """A tripwire for the one thing `_graph_middleware` cannot get from the SDK.

        That function inlines `GraphClientFactory.create_with_default_middleware`, because the
        factory builds the handler list and loads it onto the client in one step and leaves no seam
        to swap a handler into. The cost is that a handler the SDK adds to its own list in a later
        version would quietly not be installed, and nothing about a missing redirect or user-agent
        handler announces itself. So the SDK's own client is built beside ours and the two chains
        are compared.
        """
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
