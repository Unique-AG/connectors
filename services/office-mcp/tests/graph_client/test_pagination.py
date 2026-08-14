"""Paging `/me/chats`, against synthesised multi-page responses."""

import httpx
import pytest
import respx
from msgraph.generated.models.chat import Chat
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import collect_pages
from office_mcp.graph_client.pagination import MAX_EMPTY_PAGES

from .conftest import GRAPH_V1

SECOND_PAGE = f"{GRAPH_V1}/me/chats?$skiptoken=synthetic-page-2"
THIRD_PAGE = f"{GRAPH_V1}/me/chats?$skiptoken=synthetic-page-3"


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
        assert not collected.capped

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

    async def test_an_empty_page_carrying_a_next_link_is_walked_through(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The quirk this walk exists to close, and the defect it caused.

        `PageIterator.enumerate` returns False for a page whose `value` is empty and
        `PageIterator.iterate` reads that as the end of the collection — so the SDK's own walk over
        `[items + nextLink]`, `[nothing + nextLink]`, `[the last item]` stops on the middle page and
        reports the same "a cap stopped me" as a walk over a collection genuinely larger than the
        caps. Downstream, that put "this meeting has more transcripts than one call reads (200)" on
        a four-transcript meeting. An empty page carrying a next link means keep going.
        """
        graph.get("/me/chats", params={"$skiptoken": "synthetic-page-3"}).mock(
            return_value=httpx.Response(200, json={"value": [chat(4, "newest")]})
        )
        graph.get("/me/chats", params={"$skiptoken": "synthetic-page-2"}).mock(
            return_value=httpx.Response(200, json={"value": [], "@odata.nextLink": THIRD_PAGE})
        )
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [chat(1, "one"), chat(2, "two"), chat(3, "three")],
                    "@odata.nextLink": SECOND_PAGE,
                },
            )
        )
        first = await client.me.chats.get()
        assert first is not None

        collected = await collect_pages(first, client, limit=10)

        assert topics(collected.items) == ["one", "two", "three", "newest"]
        assert not collected.capped, "nothing stopped this walk but the end of the collection"


class TestTheCaps:
    async def test_the_item_limit_stops_the_walk_and_says_it_did(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        mock_two_pages(graph)
        first = await client.me.chats.get()
        assert first is not None

        collected = await collect_pages(first, client, limit=1)

        assert topics(collected.items) == ["keep"]
        assert collected.capped
        assert len(graph.calls) == 1, "the second page must not be fetched to be discarded"

    async def test_filtered_out_items_still_count_against_the_scan_cap(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The teams-mcp lesson: a filtered collection can page a long way for nothing, so the
        cap has to bound what was *looked at*, not what was kept.

        Both of these parameters are used in production, which is why they are here: `matches` by
        each meeting lister (an occurrence window), and `max_scanned` by the walk underneath them
        (`features/transcripts.newest_in_window`), which passes a tighter cap than this module's
        default because a per-meeting collection is a small thing to walk 1000 items of.
        """
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
        assert collected.capped

    async def test_a_filter_that_keeps_everything_available_is_not_capped(
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
        assert not collected.capped

    async def test_a_collection_answering_only_empty_pages_stops_inside_a_request_budget(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Following an empty page means a run of them must be bounded, and bounding items does not
        bound it: a page with nothing in it spends a request and no scan budget at all.

        So there is a request budget — `max_scanned` requests, which is the most that pages carrying
        items can spend, plus `MAX_EMPTY_PAGES` for the ones that carry none. Exhausting it means
        Graph answered that many pages of nothing while still advertising more, which is refused
        rather than answered short: a short answer here means a cap everywhere above, and this is
        not one.
        """
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200, json={"value": [], "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=loop"}
            )
        )
        first = await client.me.chats.get()
        assert first is not None

        with pytest.raises(AssertionError, match="budget"):
            _ = await collect_pages(first, client, limit=10, max_scanned=3)

        assert len(graph.calls) == 3 + MAX_EMPTY_PAGES + 1, (
            "the whole budget was spent — the caller's own first page, the scan cap's worth of "
            "requests and the empty-page allowance — and not one request more"
        )
