"""Paging via `@odata.nextLink`, walked by hand rather than by `PageIterator.iterate`.

TRAP: the SDK breaks Graph's paging contract in one line. Graph's rule is to keep following
`@odata.nextLink` until it stops coming, empty pages included
(https://learn.microsoft.com/en-us/graph/paging), but `page_iterator.py:232-233` makes `enumerate`
return False for a page with no items and `iterate` reads that as the end of the collection. Grep
that line on the next SDK bump.

Not hypothetical: a live known issue has `getAllRecordings` and `getAllTranscripts` — behind
`list_meeting_recordings` and `list_meeting_transcripts` — reset their pagination token mid-walk
and answer 200 with an empty collection and an `@odata.nextLink`
(https://learn.microsoft.com/en-us/graph/known-issues, "Teamwork and communications"). Its expected
end date of 2026-08-31 dates that incident, not this guard.

TRAP: a channel's messages are deliberately not walked here, though they are what the scan cap was
written against. Graph's throttling limit there is per *app* per tenant on a given channel, so even
a capped walk spends a budget belonging to every other user of this connector; `browse_channel`
makes one request, uses `$top` as its window, and never comes here.

TRAP: headers do not travel with the cursor. `PageIterator` starts with an empty header collection,
so a header the caller's first request needed — say `Prefer: include-unknown-enum-members` — reaches
page two only if the walk is given it too, and without it the two pages answer in different shapes.

Search paging is not handled: `POST /search/query` uses from-and-size offsets, not cursors.
"""

from collections.abc import Callable
from copy import copy
from dataclasses import dataclass
from typing import Protocol, cast

from kiota_abstractions.headers_collection import HeadersCollection
from kiota_abstractions.serialization.parsable import Parsable
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.graph_service_client import GraphServiceClient
from msgraph_core.tasks import PageIterator

from office_mcp.graph_client.errors import GraphPagingUnending
from office_mcp.graph_client.observability import current_graph_operation, record_pages_scanned


class GraphCollection[T](Protocol):
    @property
    def value(self) -> list[T] | None: ...

    @property
    def odata_next_link(self) -> str | None: ...


class _WritableCollection[T](Protocol):
    """Only ever this module's own shallow copy, never a caller's response."""

    value: list[T] | None


# Items that may be looked at to satisfy one request, however few are kept. A safety valve, not a
# tuning knob: a caller needing more than this from a filtered collection wants search instead.
MAX_SCANNED_ITEMS = 1000

# Consecutive pages carrying nothing that a walk will follow before giving up: an endlessly empty
# collection costs 11 requests.
#
# TRAP for anyone tempted to pool this with `max_scanned`: a collection answering nothing but empty
# pages spends *no* scan budget, so the whole pool goes to empty pages — a measured 1010 of them on
# `list_chats` when the budgets were shared.
#
# Per run, not per walk: `[3 items, nothing, 1 item]` is a shape Graph really sends, so a page
# carrying an item restarts the count and only an unbroken run means Graph will not end this
# collection.
#
# A `raise` and not an `assert`, because `python -O` strips assertions and this bound is all that
# stops the walk. `test_the_bound_still_stops_the_walk_under_python_O` re-runs it under `-O`.
MAX_EMPTY_PAGES = 10


@dataclass(frozen=True, slots=True)
class CollectedItems[T]:
    """Up to `limit` items, and whether a cap stopped the walk with more still on offer.

    TRAP: `capped` means "may be incomplete", not "was incomplete" — Graph's paging gives no way to
    know whether what was left holds anything the filter would have kept. It cannot mean anything
    other than a cap: a walk that gives up on a collection Graph will not end raises instead.
    """

    items: list[T]
    capped: bool


async def collect_pages[T](
    first_page: GraphCollection[T],
    client: GraphServiceClient,
    *,
    limit: int,
    matches: Callable[[T], bool] | None = None,
    max_scanned: int = MAX_SCANNED_ITEMS,
    headers: HeadersCollection | None = None,
) -> CollectedItems[T]:
    """Walk `first_page` and its successors, keeping matching items up to `limit`.

    The SDK deserialises every page with `type(first_page)`, so the cast to `T` names a guarantee
    rather than creating one. `headers` must be the collection the caller set on its first request.
    """
    items: list[T] = []
    scanned = 0
    capped = False
    # The caller's own first request counts: it is the first page this walk read.
    pages = 1

    def visit(item: Parsable) -> bool:
        nonlocal scanned, capped
        scanned += 1
        candidate = cast("T", item)
        if matches is None or matches(candidate):
            items.append(candidate)
        capped = len(items) >= limit or scanned >= max_scanned
        return not capped

    # The SDK leaves `RequestAdapter`'s own type parameter unbound, so `client.request_adapter`
    # reads as unknown-typed. Taking `client` confines that here instead of to every call site.
    iterator = PageIterator(
        _readable_first_page(first_page),
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        error_mapping={"XXX": ODataError},
    )
    empty_pages_in_a_row = 0
    # Recorded on the way out however the walk ended: the walk worth seeing on a dashboard is the
    # one that read fifty pages before giving up, and that one leaves by a raise.
    try:
        while True:
            looked_at_before = scanned
            # `enumerate`'s return value conflates two different stops: the page ran out, or `visit`
            # asked to stop. `capped` is `visit`'s own answer, so it is read instead.
            _ = iterator.enumerate(visit)  # pyright: ignore[reportUnknownMemberType]
            if capped or not iterator.current_page.odata_next_link:
                return CollectedItems(items=items, capped=capped and _more_was_on_offer(iterator))
            empty_pages_in_a_row = 0 if scanned > looked_at_before else empty_pages_in_a_row + 1
            if empty_pages_in_a_row > MAX_EMPTY_PAGES:
                raise GraphPagingUnending(
                    f"Microsoft Graph answered {empty_pages_in_a_row} pages in a row with nothing "
                    + "in them and still advertised more of this collection "
                    + f"({scanned} items looked at, {len(items)} kept)",
                    empty_pages=empty_pages_in_a_row,
                )
            # Counted before the request: a walk that gave up on its Nth page spent N requests.
            pages += 1
            iterator.headers = _headers_for_one_page(headers)
            page = await iterator.next()
            # Unreachable, and kept for what it narrows: `next()` answers None only for a page with
            # no next link, which the check above already returned on.
            assert page is not None, "Graph advertised a next link and then had no next page"
            # `iterate` also resets `pause_index` here and this walk never needs that: `enumerate`
            # sets it only where `visit` asked to stop, which is `capped`, and `capped` returned.
            iterator.current_page = page
    finally:
        record_pages_scanned(current_graph_operation(), pages)


def _readable_first_page[T](page: GraphCollection[T]) -> GraphCollection[T]:
    """`page`, or a stand-in for it carrying an empty list where its `value` was null.

    TRAP: `PageIterator.__init__` runs the response through `convert_to_page`, which raises a bare
    `ValueError` for `value: null` (`page_iterator.py:180-181`) that nothing here classifies. Every
    *later* page with the same body is read as an empty page and walked through correctly, so page
    one is made to look like the rest.

    The copy is shallow, leaving the caller's response as it was, and preserves the `type()`
    `PageIterator` deserialises every successor with.
    """
    if page.value is not None:
        return page
    stand_in: GraphCollection[T] = copy(page)
    # Through `object` because the two protocols deliberately do not overlap.
    writable = cast(_WritableCollection[T], cast(object, stand_in))
    writable.value = []
    return stand_in


def _headers_for_one_page(headers: HeadersCollection | None) -> HeadersCollection:
    """A collection of the caller's headers for exactly one next-page request.

    TRAP: one per page, and re-assigned before every `next()`. `PageIterator.fetch_next_page` does
    `request_info.headers = self.headers` — an assignment, so every page's request would otherwise
    share the iterator's one long-lived collection. `BaseBearerTokenAuthenticationProvider` asks
    `AccessTokenProvider` for a token only when the request carries no `Authorization` yet, so the
    header the first followed page deposits in a shared collection means no page after it consults
    the provider again — and that provider (`_CallerTokenProvider` in `client.py`) is where the
    allowed-hosts check lives, the one thing that refuses to hand the caller's delegated token to an
    `@odata.nextLink` pointing off Graph.

    A copy rather than the caller's own collection for the same reason in the other direction: the
    adapter adds `Authorization` to whichever collection it is handed, and the caller's is also on
    the caller's own first request.

    Not `PageIterator.set_headers`: it splats a dict into `add_all`, which takes a
    `HeadersCollection`.
    """
    for_this_page = HeadersCollection()
    if headers is not None:
        for_this_page.add_all(headers)
    return for_this_page


def _more_was_on_offer(iterator: PageIterator) -> bool:
    page = iterator.current_page
    unread_in_page = iterator.pause_index < len(page.value or [])
    return unread_in_page or bool(page.odata_next_link)
