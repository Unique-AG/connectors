"""Paging `/me/chats`, against synthesised multi-page responses."""

import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import respx
from kiota_abstractions.api_error import APIError
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.chat import Chat
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import GraphPagingUnending, collect_pages, pagination
from office_mcp.graph_client.pagination import MAX_EMPTY_PAGES, MAX_SCANNED_ITEMS

from .conftest import CALLER_TOKEN, GRAPH_V1

SECOND_PAGE = f"{GRAPH_V1}/me/chats?$skiptoken=synthetic-page-2"
THIRD_PAGE = f"{GRAPH_V1}/me/chats?$skiptoken=synthetic-page-3"
# A next link Graph would never send, which is the point: the walk replays what it is given.
OFF_GRAPH_PAGE = "https://attacker.invalid/v1.0/me/chats"


def chat(number: int, topic: str) -> dict[str, object]:
    return {"id": f"19:{number:032x}@thread.v2", "topic": topic, "chatType": "group"}


class RecordedPages:
    """Stands in for `record_pages_scanned` so the count one walk hands it can be read back.

    The histogram itself is asserted on in `tests/test_graph_metrics.py`, from inside a
    `graph_errors` block: `observability` drops a count taken outside one, and every walk here is
    outside one. What is worth pinning in this file is the number this module arrives at.
    """

    def __init__(self) -> None:
        self.counts: list[int] = []

    def record(self, _operation: str | None, pages: int) -> None:
        self.counts.append(pages)


@pytest.fixture
def recorded_pages(monkeypatch: pytest.MonkeyPatch) -> RecordedPages:
    recorded = RecordedPages()
    monkeypatch.setattr(pagination, "record_pages_scanned", recorded.record)
    return recorded


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
        """The SDK quirk this walk exists to close, and what it costs the tools above.

        `PageIterator.enumerate` returns False for a page whose `value` is empty and
        `PageIterator.iterate` reads that as the end of the collection — so the SDK's own walk over
        `[items + nextLink]`, `[nothing + nextLink]`, `[the last item]` stops on the middle page.
        Every tool over this module reports "that is all of it" by coming back short of `limit`, so
        a walk that stops there does not merely lose chats: it turns a window Graph had more behind
        into a claim that the user has no more. An empty page carrying a next link means keep going.
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


class TestAFirstPageCarryingNoValueAtAll:
    """A `200 OK` whose body has no `value`, which is where the SDK disagrees with itself.

    `PageIterator.enumerate` reads that body as an empty page on every request but the first, and
    `PageIterator.__init__` raises a bare `ValueError` on it (page_iterator.py:180-181). A
    `ValueError` is none of the three things `graph_errors` classifies, so it would reach a tool
    with no remedy attached and be counted under the status that means the seam could not describe
    it. The fix is that page one behaves as page two already does.
    """

    async def test_a_first_page_with_no_value_and_no_next_link_collects_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/chats").mock(
            return_value=httpx.Response(200, json={"@odata.context": f"{GRAPH_V1}/$metadata#chats"})
        )
        first = await client.me.chats.get()
        assert first is not None

        collected = await collect_pages(first, client, limit=10)

        assert collected.items == []
        assert not collected.capped, "an empty collection is the whole of it, not a cap"

    async def test_a_first_page_with_no_value_but_a_next_link_is_walked_through(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The shape the known issue on `getAllRecordings`/`getAllTranscripts` produces: a token
        reset answers 200 with nothing in it and a `@odata.nextLink` still set. Landing on the
        first request rather than a later one must not change what the walk does with it."""
        graph.get("/me/chats", params={"$skiptoken": "synthetic-page-2"}).mock(
            return_value=httpx.Response(200, json={"value": [chat(1, "keep")]})
        )
        graph.get("/me/chats").mock(
            return_value=httpx.Response(200, json={"@odata.nextLink": SECOND_PAGE})
        )
        first = await client.me.chats.get()
        assert first is not None

        collected = await collect_pages(first, client, limit=10)

        assert topics(collected.items) == ["keep"]
        assert not collected.capped
        assert str(graph.calls.last.request.url) == SECOND_PAGE

    async def test_the_response_the_caller_passed_in_is_left_as_it_was(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The walk reads page one as empty by standing in a copy for it, not by writing an empty
        list over what the caller handed it — the caller keeps whatever Graph actually sent."""
        graph.get("/me/chats").mock(
            return_value=httpx.Response(200, json={"@odata.context": f"{GRAPH_V1}/$metadata#chats"})
        )
        first = await client.me.chats.get()
        assert first is not None

        _ = await collect_pages(first, client, limit=10)

        assert first.value is None


class TestTheHeadersItCarries:
    async def test_the_headers_it_is_given_go_on_every_page_it_follows(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`PageIterator` starts with an empty header collection and stamps it onto every next-page
        request, so a header the caller's own first request needed reaches page two only if the walk
        is given it. `Prefer: include-unknown-enum-members` is the case that made this a parameter:
        Graph answers an evolvable enum for the header the request carried, so a walk that dropped
        it would answer page one in one shape and page two in another.
        """
        mock_two_pages(graph)
        first = await client.me.chats.get()
        assert first is not None
        headers = HeadersCollection()
        headers.add("Prefer", "include-unknown-enum-members")

        _ = await collect_pages(first, client, limit=10, headers=headers)

        assert graph.calls.last.request.headers["prefer"] == "include-unknown-enum-members"
        assert headers.keys() == ["prefer"], (
            "the walk copies what it was given rather than adding to it — the request adapter puts "
            "`Authorization` on whichever collection it is handed"
        )

    async def test_a_walk_given_no_headers_sends_none_of_its_own(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        mock_two_pages(graph)
        first = await client.me.chats.get()
        assert first is not None

        _ = await collect_pages(first, client, limit=10)

        assert "prefer" not in graph.calls.last.request.headers


class TestTheTokenItWillNotCarryOffGraph:
    """A `@odata.nextLink` is a URL Graph chose, and this walk replays it verbatim. So the walk is
    the one place a hostile or compromised next link could aim the caller's delegated token at a
    host that is not Graph, and `_CallerTokenProvider.get_authorization_token` is the only thing
    that refuses — see the TRAP in `client.py`.
    """

    async def test_a_next_link_off_graph_is_followed_without_the_callers_token(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Three pages, because two cannot show this: the leak needs a page that *deposits*
        `Authorization` in a collection a later page then reuses.

        `BaseBearerTokenAuthenticationProvider` asks the token provider for a token only when the
        request carries no `Authorization` yet, and `PageIterator.fetch_next_page` assigns
        `request_info.headers = self.headers`. Give every page the iterator's one collection and the
        header page two got is already on page three's request, so the provider — and with it the
        allowed-hosts check — is never consulted again for the rest of the walk.

        Asserted with `headers=` passed because that is the case that leaked: a walk given none
        happens to survive on `authenticate_request`'s `if not request.request_headers` replacing
        the collection, which is not a property to hold this walk to.
        """
        off_graph = graph.route(host="attacker.invalid").mock(
            return_value=httpx.Response(200, json={"value": [chat(3, "bait")]})
        )
        on_graph = graph.get("/me/chats", params={"$skiptoken": "synthetic-page-2"}).mock(
            return_value=httpx.Response(
                200,
                json={"value": [chat(2, "second")], "@odata.nextLink": OFF_GRAPH_PAGE},
            )
        )
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={"value": [chat(1, "first")], "@odata.nextLink": SECOND_PAGE},
            )
        )
        first = await client.me.chats.get()
        assert first is not None
        headers = HeadersCollection()
        headers.add("Prefer", "include-unknown-enum-members")

        collected = await collect_pages(first, client, limit=10, headers=headers)

        assert topics(collected.items) == ["first", "second", "bait"]
        assert off_graph.called, (
            "the next link was followed, so the refusal is about the token only"
        )
        off_graph_request = off_graph.calls.last.request
        assert "authorization" not in off_graph_request.headers, (
            "the caller's delegated token reached a host that is not Graph"
        )
        assert off_graph_request.headers["prefer"] == "include-unknown-enum-members", (
            "the caller's own headers still travel; it is the bearer token that does not"
        )
        assert on_graph.calls.last.request.headers["authorization"] == f"Bearer {CALLER_TOKEN}", (
            "and the page before it was authenticated, so the header is genuinely per request"
        )


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

    async def test_a_cap_that_stops_on_the_first_item_of_the_only_page_says_capped(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Capping is not read off @odata.nextLink alone. One page, no next link, and a cap
        that stops on the first item still leaves two items the caller never sees."""
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={"value": [chat(1, "first"), chat(2, "second"), chat(3, "third")]},
            )
        )
        first = await client.me.chats.get()
        assert first is not None

        collected = await collect_pages(first, client, limit=1)

        assert topics(collected.items) == ["first"]
        assert collected.capped

    async def test_filtered_out_items_still_count_against_the_scan_cap(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The teams-mcp lesson: a filtered collection can page a long way for nothing, so the
        cap has to bound what was *looked at*, not what was kept.

        `max_scanned` is a parameter rather than only a constant because a caller with a small
        collection and a tighter request budget passes its own; the default is the safety valve for
        a caller that has no opinion."""
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

        `MAX_EMPTY_PAGES` is that bound, and it is counted against nothing else. The tempting
        arithmetic is to pool it — `max_scanned` requests plus this allowance for the whole walk,
        on the grounds that at most `max_scanned` requests can go on pages that carried anything, so
        the rest bounds the empty ones. A collection answering nothing but empty pages spends *no*
        scan budget, so the whole pool would be theirs. Hence the count is pinned to the requests it
        actually costs rather than to a formula: the caller's own first page plus `MAX_EMPTY_PAGES`
        followed after it, whatever `max_scanned` is.
        """
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200, json={"value": [], "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=loop"}
            )
        )
        first = await client.me.chats.get()
        assert first is not None

        with pytest.raises(GraphPagingUnending, match="in a row"):
            _ = await collect_pages(first, client, limit=10, max_scanned=3)

        assert len(graph.calls) == MAX_EMPTY_PAGES + 1 == 11, (
            "the caller's own first page and the run of empty ones this walk will follow, and not "
            "one request more — the scan cap lends it nothing"
        )

    async def test_the_scan_cap_does_not_lend_the_empty_pages_a_longer_run(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The same collection at the module's own `max_scanned`, which is what production passes.

        This is the measurement a pooled budget would get wrong by two orders of magnitude: the
        bound has to be the same 11 requests whether the walk was allowed 3 items or 1000, because
        neither number says anything about pages that carried none.
        """
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200, json={"value": [], "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=loop"}
            )
        )
        first = await client.me.chats.get()
        assert first is not None

        with pytest.raises(GraphPagingUnending, match="in a row"):
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


class TestWhatOneWalkCost:
    async def test_the_request_that_failed_is_counted_among_the_pages(
        self, client: GraphServiceClient, graph: respx.MockRouter, recorded_pages: RecordedPages
    ) -> None:
        """The walk worth seeing on the histogram is the one that read a long way before giving up,
        and that one leaves by a raise. Counting a page only once its fetch came back drops exactly
        the request that made the walk worth looking at: the one that failed."""
        graph.get("/me/chats", params={"$skiptoken": "synthetic-page-3"}).mock(
            return_value=httpx.Response(
                500, json={"error": {"code": "generalException", "message": "unexpected"}}
            )
        )
        graph.get("/me/chats", params={"$skiptoken": "synthetic-page-2"}).mock(
            return_value=httpx.Response(
                200, json={"value": [chat(2, "two")], "@odata.nextLink": THIRD_PAGE}
            )
        )
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200, json={"value": [chat(1, "one")], "@odata.nextLink": SECOND_PAGE}
            )
        )
        first = await client.me.chats.get()
        assert first is not None

        with pytest.raises(APIError):
            _ = await collect_pages(first, client, limit=10)

        assert recorded_pages.counts == [3], (
            "three requests were made and the third is the one that failed — a walk that reports "
            "two has hidden the page an operator is looking for"
        )


# The one test the run below re-runs under `-O`. Named once, here, so that renaming the test cannot
# silently turn that run into a no-op: `pytest` exits non-zero on a node id it cannot collect.
_ENDLESS_COLLECTION = (
    "tests/graph_client/test_pagination.py::TestTheCaps"
    "::test_a_collection_answering_only_empty_pages_gives_up_in_a_run_of_them"
)

_PROJECT_ROOT = Path(__file__).parents[2]


class TestTheBoundIsNotAnAssertion:
    """The bound on empty pages has to hold in the interpreter production runs, `-O` included."""

    async def test_the_refusal_names_the_run_and_what_graph_was_still_advertising(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """What an operator gets, and what a model gets: `shared/seam.py` maps `GraphFailure` and
        nothing else onto tool advice, so the type is what makes this reach the caller as something
        it can act on rather than as a crash, and the count is the whole of the evidence."""
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200, json={"value": [], "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=loop"}
            )
        )
        first = await client.me.chats.get()
        assert first is not None

        with pytest.raises(GraphPagingUnending) as raised:
            _ = await collect_pages(first, client, limit=10)

        assert raised.value.empty_pages == MAX_EMPTY_PAGES + 1
        message = str(raised.value)
        assert f"{MAX_EMPTY_PAGES + 1} pages in a row" in message, "the count, for an operator"
        assert "still advertised more of this collection" in message, "and why that is a refusal"
        assert raised.value.status is None, "no request failed; every one of those pages was a 200"

    def test_the_bound_still_stops_the_walk_under_python_O(self) -> None:
        """`python -O` strips `assert` statements, so a bound written as one is not a bound at all.

        This is why the refusal is a raise, and it cannot be tested in-process: `__debug__` is
        fixed when the interpreter starts. So the empty-page test is re-run in a child interpreter
        started with `-O`, where a walk with nothing to stop it follows a collection that never
        ends — which is why the child is given a deadline and why running out of it is reported as
        the failure it is. Write the bound as an `assert` and this test fails: either the child
        hangs on the endless collection, or `pytest.raises` reports that nothing was raised.
        """
        stripped = subprocess.run(
            [sys.executable, "-O", "-c", "print(__debug__)"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert stripped.stdout.strip() == "False", "the child really does drop its assertions"

        try:
            completed = subprocess.run(
                [sys.executable, "-O", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x"]
                + [_ENDLESS_COLLECTION],
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(
                "the walk never stopped under `python -O`: the bound on empty pages is written as "
                + "something the optimiser removed, which is the defect this test exists for"
            )

        assert completed.returncode == 0, (
            "the bound did not hold under `python -O`:\n" + completed.stdout + completed.stderr
        )
