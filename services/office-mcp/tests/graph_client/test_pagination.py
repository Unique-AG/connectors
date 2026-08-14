"""Paging `/me/chats`, against synthesised multi-page responses."""

import httpx
import pytest
import respx
from msgraph.generated.models.chat import Chat
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import collect_pages
from office_mcp.graph_client.pagination import MAX_EMPTY_PAGES, MAX_SCANNED_ITEMS

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

    async def test_a_collection_answering_only_empty_pages_gives_up_in_a_run_of_them(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Following an empty page means a run of them must be bounded, and bounding items does not
        bound it: a page with nothing in it spends a request and no scan budget at all.

        `MAX_EMPTY_PAGES` is that bound, and it is counted against nothing else. It used to be half
        of one pooled request budget — `max_scanned` requests plus this allowance — defended as "at
        most `max_scanned` requests can go on pages that carried anything, so this bounds the rest".
        A collection answering nothing but empty pages spends *no* scan budget, so the whole pool
        was theirs: this same walk followed 13 pages of nothing with `max_scanned=3`, and
        `list_chats` followed 1010 of them at the default. So the count is pinned to the requests it
        actually costs, not to the formula: the caller's own first page plus `MAX_EMPTY_PAGES`
        followed after it, whatever `max_scanned` is.
        """
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200, json={"value": [], "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=loop"}
            )
        )
        first = await client.me.chats.get()
        assert first is not None

        with pytest.raises(AssertionError, match="in a row"):
            _ = await collect_pages(first, client, limit=10, max_scanned=3)

        assert len(graph.calls) == MAX_EMPTY_PAGES + 1 == 11, (
            "the caller's own first page and the run of empty ones this walk will follow, and not "
            "one request more — the scan cap lends it nothing"
        )

    async def test_the_scan_cap_does_not_lend_the_empty_pages_a_longer_run(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The same collection at the module's own `max_scanned`, which is what production passes.

        This is the measurement the pooled budget got wrong by two orders of magnitude: the bound
        has to be the same 11 requests whether the walk was allowed 3 items or 1000, because neither
        number says anything about pages that carried none.
        """
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200, json={"value": [], "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=loop"}
            )
        )
        first = await client.me.chats.get()
        assert first is not None

        with pytest.raises(AssertionError, match="in a row"):
            _ = await collect_pages(first, client, limit=10, max_scanned=MAX_SCANNED_ITEMS)

        assert len(graph.calls) == MAX_EMPTY_PAGES + 1

    async def test_a_collection_sprinkling_empty_pages_between_items_is_walked_to_its_end(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Why the bound is per run rather than per walk. Graph does answer the occasional empty
        page in the middle of a collection that is otherwise fine, so a walk over more of them *in
        total*
        than the allowance — with an item between each — is making progress and must not be given up
        on. A page carrying an item starts the count again; only a run of nothing is refused.
        """
        pages = MAX_EMPTY_PAGES + 4
        for index in range(pages):
            last = index == pages - 1
            graph.get("/me/chats", params={"$skiptoken": f"page-{index}"}).mock(
                return_value=httpx.Response(
                    200,
                    json={"value": [chat(index, "keep")]}
                    if last
                    # One item, then nothing, then on: the empty page carries the cursor to the next
                    # pair, so `pages` runs of length one add up to more empties than the allowance.
                    else {
                        "value": [chat(index, "keep")],
                        "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=empty-{index}",
                    },
                )
            )
            graph.get("/me/chats", params={"$skiptoken": f"empty-{index}"}).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "value": [],
                        "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=page-{index + 1}",
                    },
                )
            )
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200, json={"value": [], "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=page-0"}
            )
        )
        first = await client.me.chats.get()
        assert first is not None

        collected = await collect_pages(first, client, limit=100)

        assert len(collected.items) == pages, "every item page was reached"
        assert not collected.capped, "nothing stopped this walk but the end of the collection"
