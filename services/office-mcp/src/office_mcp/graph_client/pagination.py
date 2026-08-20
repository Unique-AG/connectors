"""Paging via @odata.nextLink with safety guards from teams-mcp experience.

Graph pages using `@odata.nextLink` as cursor—replayed verbatim, never decomposed. The SDK's
`PageIterator` fetches and deserializes. This module walks with three lessons: scan cap (not just
item cap), empty page handling, and empty page run bounds.

Scan cap: If filtered after fetch (e.g., messages are mostly joins), "give me 20 items" can walk
entire channel history one page at a time. Cap must bound what was looked at, not only what kept.

Empty pages: Graph's paging contract is that "a page of results might contain zero or more results"
and that a caller keeps calling with the `@odata.nextLink` of each response "until the
`@odata.nextLink` property is no longer returned"
(https://learn.microsoft.com/en-us/graph/paging). The SDK breaks that contract in one line —
`page_iterator.py:232-233`, where a page with no items makes `enumerate` return False, which
`iterate` reads as the end of the collection — so a short window comes back as "that's all" instead
of truthfully saying "window stopped at cap". Grep that line on the next SDK bump; this module's
loop follows the link instead.

Not hypothetical here. A live known issue has `getAllRecordings` and `getAllTranscripts` — the
endpoints behind `list_meeting_recordings` and `list_meeting_transcripts` — reset their pagination
token mid-walk and answer "a `200 OK` response with an empty collection and an `@odata.nextLink`",
with Microsoft's own workaround being to "continue following `@odata.nextLink` even when the
collection is empty" (https://learn.microsoft.com/en-us/graph/known-issues, "Teamwork and
communications"). Its expected end date of 2026-08-31 dates that incident, not this guard: the
paging contract above carries no end date.

The same body on the *first* page takes a different SDK path and needs its own answer.
`PageIterator.__init__` runs the caller's response through `convert_to_page`, which raises a bare
`ValueError` for `value: null` (`page_iterator.py:180-181`) rather than reading it as the empty page
it is — see `_readable_first_page`.

Empty run bound: Following empty pages needs its own bound separate from item cap. `MAX_EMPTY_PAGES`
is that bound, counted per run on its own—never pooled with item budget.

A channel's messages are deliberately not walked here at all, and they are the collection the scan
cap was written against — which is worth saying in the same breath. Filtering them after the fact
is exactly the shape that cap exists for, but the throttling limit above is per *app* per tenant on
a given channel, so even a capped walk spends a budget that belongs to every other user of this
connector. `browse_channel` therefore makes one request, uses `$top` as its window, and never comes
here; the cap is for collections whose cost is the caller's own.

Headers do not travel with the cursor: `PageIterator` starts with an empty header collection and
stamps it onto every next-page request. A header the caller's own first request needed—`Prefer:
include-unknown-enum-members`, say—reaches page two only if the walk is given it too. Without that,
page one answers in one shape and page two in another, which is a half-fix that looks like a fix.

Search paging not handled: POST /search/query uses from/size offsets, not cursors.
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
    """Structural type for Graph collection responses. Extracts element type from the caller's
    response."""

    @property
    def value(self) -> list[T] | None: ...

    @property
    def odata_next_link(self) -> str | None: ...


class _WritableCollection[T](Protocol):
    """A collection response seen as writable. Used on this module's own shallow copy of one, and
    never on anything a caller passed in — which is why `GraphCollection` above stays read-only."""

    value: list[T] | None


# How many items may be looked at to satisfy one request, however few of them are kept. A
# safety valve on request count, not a tuning knob: a caller that needs more than this from a
# filtered collection is asking the wrong endpoint (use search). A caller with a smaller
# collection and a tighter budget passes its own `max_scanned` — see shape 2 in the module
# docstring.
MAX_SCANNED_ITEMS = 1000

# How many pages carrying nothing at all, one after another, one walk will follow before it gives up
# on the collection. Counted per run and counted on its own, and both of those are what make the
# number mean what it says:
#
# * **Its own count, not the request budget's.** This used to be half of one pooled number
#   (`max_scanned + MAX_EMPTY_PAGES + 1` requests for the whole walk), defended as "pages carrying
#   items can only spend `max_scanned` of it, so this bounds the rest". That defence is wrong in the
#   case it exists for: a collection answering nothing but empty pages spends *no* scan budget, so
#   the entire pool went to empty pages — a measured 1010 of them on `list_chats` before the walk
#   gave up, two orders of magnitude past what this constant said. A thousand sequential Graph
#   requests take minutes and would trip throttling long before the end, so the empty pages are
#   counted against this and nothing else: an endlessly empty collection now costs 11 requests.
# * **Per run, not per walk.** Graph does answer the odd empty page in the middle of a collection
#   that is otherwise fine—`[3 items, nothing, 1 item]` is the shape this walk exists for—and a
#   per-walk total would give up on a large collection that sprinkles a few of them, which is a walk
#   killed for making progress. A page that carries an item is progress and starts the count again;
#   what a *run* of nothing means is that Graph will not end this collection, which is the thing
#   worth refusing.
#
# The walk is bounded either way, and this is the whole of why: every page it follows either carried
# an item—and at most `max_scanned` items may be looked at—or extended a run at most this long.
# The two together are the only claim worth making about the total, because the arithmetic worst
# case is a collection Graph does not send: one full run of nothing after every single item, which
# is bounded (`max_scanned` runs of this length) but not small. No smaller total is available
# without giving up on a collection that is making progress, which is the trade this constant is one
# side of: a walk answering with items is never refused, and one answering with nothing stops at 11.
#
# `collect_pages` refuses a collection that exhausts this rather than returning what it has, because
# an answer cut short for that reason would be indistinguishable from one cut short by a cap and
# would mean something entirely different—the honesty the tools above are built on is that a short
# answer means a cap. A raise and not an `assert`: this is Microsoft Graph misbehaving, which is the
# system boundary this package's exceptions are for, and `python -O` strips asserts—which would
# leave this walk following an endless collection with nothing to stop it, the exact failure the
# constant above exists to bound.
MAX_EMPTY_PAGES = 10


@dataclass(frozen=True, slots=True)
class CollectedItems[T]:
    """Up to `limit` items, and whether a cap stopped the walk with more still on offer.

    `capped` is a "may be incomplete", not a "was incomplete": it is true when a cap stopped the
    walk while a `@odata.nextLink` or an unread part of a page remained, and Graph's paging gives
    no way to know whether what was left holds anything the filter would have kept.

    What it cannot mean is anything other than a cap. An empty page carrying a next link is walked
    through rather than believed, and a walk that gives up on a collection Graph will not end
    raises instead of returning—so a caller reading this as "the caps stopped me" is reading it
    correctly.
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
    """Walk first_page and successors, keeping matching items up to limit.

    The SDK deserializes every page with `type(first_page)`, so the item a page hands back is
    always what the caller's own collection response declared it holds. The cast to `T` only
    names that guarantee; it does not create it.

    `headers` go on every page this walk fetches. The caller sets them on its own first request and
    passes the same collection here, because the walk's requests are the caller's request continued
    and Graph answers a page for the header it was asked under.
    """
    items: list[T] = []
    scanned = 0
    capped = False
    # The caller's own first request counts: it is the first page this walk read, and the point of
    # the histogram is what one call cost Graph. The operation it is counted under comes from the
    # `graph_errors` block this walk runs inside — see `observability.py`.
    pages = 1

    def visit(item: Parsable) -> bool:
        nonlocal scanned, capped
        scanned += 1
        candidate = cast(T, item)
        if matches is None or matches(candidate):
            items.append(candidate)
        capped = len(items) >= limit or scanned >= max_scanned
        return not capped

    # The SDK leaves `RequestAdapter`'s own type parameter unbound, so `client.request_adapter`
    # reads as unknown-typed. Taking `client` here confines that to this one line instead of
    # every call site.
    iterator = PageIterator(
        _readable_first_page(first_page),
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        error_mapping={"XXX": ODataError},
    )
    if headers is not None:
        # Not `set_headers`: it splats a dict into `add_all`, which takes a `HeadersCollection`.
        # Copying into the iterator's own collection also keeps the caller's untouched — the request
        # adapter adds `Authorization` to whichever one it is handed.
        iterator.headers.add_all(headers)
    empty_pages_in_a_row = 0
    # The count is recorded on the way out however the walk ended: the walk worth seeing on a
    # dashboard is the one that read fifty pages before giving up, and that one leaves by a raise.
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
            # Counted before the request rather than after it: a walk that gave up on its Nth page
            # spent N requests, and the one that failed is the page a dashboard came here to see.
            pages += 1
            page = await iterator.next()
            # Unreachable, and kept for what it narrows: `next()` answers None only for a page with
            # no next link, which the check above already returned on. Every other path builds a
            # `PageResult`, and this is what says so to the SDK's `Optional` return.
            assert page is not None, "Graph advertised a next link and then had no next page"
            # `iterate` also resets `pause_index` here; this walk can never need that.
            # `enumerate` sets it only where `visit` asked to stop, which is `capped`, and `capped`
            # returned above.
            iterator.current_page = page
    finally:
        record_pages_scanned(current_graph_operation(), pages)


def _readable_first_page[T](page: GraphCollection[T]) -> GraphCollection[T]:
    """`page`, or a stand-in for it carrying an empty list where its `value` was null.

    `PageIterator.__init__` runs the response through `convert_to_page`, which raises a bare
    `ValueError` for `value: null` (`page_iterator.py:180-181`). Nothing classifies that:
    `graph_errors` knows `APIError`, `httpx.TransportError` and `GraphFailure`, so it would reach a
    tool with no remedy and be counted under the status meaning "an exception this seam cannot
    describe". Every *later* page with the same body is read as an empty page and walked through
    correctly, so page one is made to look like the rest of them.

    The copy is shallow and the caller's own response is left as it was. `PageIterator` deserialises
    every successor with `type()` of what it is handed, which the copy preserves.
    """
    if page.value is not None:
        return page
    stand_in: GraphCollection[T] = copy(page)
    # Through `object` because the two protocols deliberately do not overlap: one of them is what a
    # caller hands over, and the other is only ever this module's own copy of it.
    writable = cast(_WritableCollection[T], cast(object, stand_in))
    writable.value = []
    return stand_in


def _more_was_on_offer(iterator: PageIterator) -> bool:
    """True if the page has unread items or a next link (more was available when walk stopped)."""
    page = iterator.current_page
    unread_in_page = iterator.pause_index < len(page.value or [])
    return unread_in_page or bool(page.odata_next_link)
