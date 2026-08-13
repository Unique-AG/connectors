import httpx
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client.client import (
    _CallerTokenProvider,  # pyright: ignore[reportPrivateUsage]
)

from .conftest import CALLER_TOKEN, RecordedSleeps


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
