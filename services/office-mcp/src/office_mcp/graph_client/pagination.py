"""Paging via @odata.nextLink with safety guards from teams-mcp experience.

Graph pages using `@odata.nextLink` as cursor—replayed verbatim, never decomposed. The SDK's
`PageIterator` fetches and deserializes. This module walks with three lessons: scan cap (not just
item cap), empty page handling, and empty page run bounds.

Scan cap: If filtered after fetch (e.g., messages are mostly joins), "give me 20 items" can walk
entire channel history one page at a time. Cap must bound what was looked at, not only what kept.

Empty pages: `PageIterator.iterate` stops at empty pages, but Graph sends them with
`@odata.nextLink` still set. The SDK stops early, losing items. A short window comes back as
"that's all" instead of truthfully saying "window stopped at cap". This module's loop handles
empty pages: if it carries nextLink, keep going.

Empty run bound: Following empty pages needs its own bound separate from item cap. `MAX_EMPTY_PAGES`
is that bound, counted per run on its own—never pooled with item budget.

Search paging not handled: POST /search/query uses from/size offsets, not cursors.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

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
) -> CollectedItems[T]:
    """Walk first_page and successors, keeping matching items up to limit.

    The SDK deserializes every page with `type(first_page)`, so the item a page hands back is
    always what the caller's own collection response declared it holds. The cast to `T` only
    names that guarantee; it does not create it.
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
        first_page,
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        error_mapping={"XXX": ODataError},
    )
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
            page = await iterator.next()
            assert page is not None, "Graph advertised a next link and then had no next page"
            iterator.current_page = page
            iterator.pause_index = 0
            pages += 1
    finally:
        record_pages_scanned(current_graph_operation(), pages)


def _more_was_on_offer(iterator: PageIterator) -> bool:
    """True if the page has unread items or a next link (more was available when walk stopped)."""
    page = iterator.current_page
    unread_in_page = iterator.pause_index < len(page.value or [])
    return unread_in_page or bool(page.odata_next_link)
