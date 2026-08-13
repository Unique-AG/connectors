"""Paging `/me/chats`, against synthesised two-page responses."""

import httpx
import respx
from msgraph.generated.models.chat import Chat
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import collect_pages

from .conftest import GRAPH_V1

SECOND_PAGE = f"{GRAPH_V1}/me/chats?$skiptoken=synthetic-page-2"


def chat(number: int, topic: str) -> dict[str, object]:
    return {"id": f"19:{number:032x}@thread.v2", "topic": topic, "chatType": "group"}


def mock_two_pages(graph: respx.MockRouter) -> None:
    """Two pages of three chats, the first advertising the second by absolute nextLink.

    The `$skiptoken` route is registered first because respx matches in registration order and
    the bare route would otherwise answer both requests.
    """
    graph.get("/me/chats", params={"$skiptoken": "synthetic-page-2"}).mock(
        return_value=httpx.Response(200, json={"value": [chat(3, "keep")]})
    )
    graph.get("/me/chats").mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [chat(1, "keep"), chat(2, "drop")],
                "@odata.nextLink": SECOND_PAGE,
            },
        )
    )


def topics(chats: list[Chat]) -> list[str | None]:
    return [item.topic for item in chats]


class TestFollowingNextLink:
    async def test_every_page_is_walked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        mock_two_pages(graph)
        first = await client.me.chats.get()
        assert first is not None

        collected = await collect_pages(first, client, limit=10)

        assert topics(collected.items) == ["keep", "drop", "keep"]
        assert not collected.truncated

    async def test_the_next_link_is_replayed_verbatim(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The whole URL is the cursor; Graph documents that its `$skiptoken` is not ours to
        take apart and re-send under our own query parameters."""
        mock_two_pages(graph)
        first = await client.me.chats.get()
        assert first is not None

        _ = await collect_pages(first, client, limit=10)

        assert str(graph.calls.last.request.url) == SECOND_PAGE


class TestTheCaps:
    async def test_the_item_limit_stops_the_walk_and_says_it_did(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        mock_two_pages(graph)
        first = await client.me.chats.get()
        assert first is not None

        collected = await collect_pages(first, client, limit=1)

        assert topics(collected.items) == ["keep"]
        assert collected.truncated
        assert len(graph.calls) == 1, "the second page must not be fetched to be discarded"

    async def test_filtered_out_items_still_count_against_the_scan_cap(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The teams-mcp lesson: a filtered collection can page a long way for nothing, so the
        cap has to bound what was *looked at*, not what was kept."""
        mock_two_pages(graph)
        first = await client.me.chats.get()
        assert first is not None

        collected = await collect_pages(
            first,
            client,
            limit=10,
            matches=lambda item: item.topic == "keep",
            max_scanned=2,
        )

        assert topics(collected.items) == ["keep"]
        assert collected.truncated

    async def test_a_filter_that_keeps_everything_available_is_not_truncated(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        mock_two_pages(graph)
        first = await client.me.chats.get()
        assert first is not None

        collected = await collect_pages(
            first,
            client,
            limit=10,
            matches=lambda item: item.topic == "keep",
        )

        assert topics(collected.items) == ["keep", "keep"]
        assert not collected.truncated
