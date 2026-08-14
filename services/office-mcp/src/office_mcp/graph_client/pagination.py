"""Following `@odata.nextLink`, with the caps `services/teams-mcp` learned it needed.

Graph pages every list endpoint, and the whole `@odata.nextLink` URL is the cursor: it is
replayed verbatim, never decomposed (https://learn.microsoft.com/en-us/graph/paging). The SDK's
`PageIterator` is what fetches a page and deserializes it, and this module is the walk over it —
three lessons' worth, two of them paid for by teams-mcp in `src/msgraph/graph-pagination.ts` and
one by the answer a stopped-short walk used to give:

* **A scan cap as well as an item cap.** Where a collection is filtered after the fact, "give me
  20" can otherwise walk a long way for nothing, so a cap has to bound what was *looked at* and not
  only what was kept.
* **A bound on pages that carry nothing, and its own rather than the scan cap's.** Bounding items
  does not bound requests: a page Graph answers with nothing in it spends a request and no scan
  budget at all. So a run of those is bounded separately, by `MAX_EMPTY_PAGES` — separately because
  a single pooled number (the scan cap's requests plus an allowance) is no bound on empty pages at
  all: a collection answering nothing but empty pages spends no scan budget, so the whole pool was
  theirs and `list_chats` followed a thousand pages of nothing before giving up.
* **An empty page is not the end of a collection.** `PageIterator.enumerate` returns `False` for a
  page whose `value` is empty and `PageIterator.iterate` reads that as "stop", so the SDK's own
  walk ends at the first empty page even when that page carried an `@odata.nextLink`. Graph does
  answer with those, and the cost was not cosmetic: the walk reported the same "stopped short" for
  a four-transcript meeting paged `[3, nothing, 1]` as for a meeting genuinely larger than one call
  reads, which put "this meeting has more transcripts than one call reads" on an answer about four.
  So the page loop below is this module's rather than `iterate`'s: an empty page carrying a next
  link means keep going, and a walk that stops short can then only ever have hit a cap.

Three ways of bounding a read live in this connector, and they are three because the collections
are. This is the one place they are set out together:

1. **Walk, bounded by items kept.** The inventories — `/me/chats`, `/me/joinedTeams`,
   `/teams/{id}/channels` — are unfiltered, so `limit` items kept *is* the work done and
   `MAX_SCANNED_ITEMS` never binds. Nothing filters them after the fact, so nothing more is needed:
   a page short of `limit` with no next link is the end of the collection, and the tools over them
   say so by returning fewer items than were asked for rather than with a flag of their own.
2. **Walk, bounded by items scanned, at a tighter cap.** A meeting's transcripts and its
   recordings are filtered here (an occurrence window) *and* sorted here (newest first), so the
   walk cannot stop at `limit` — it has to see the collection before it can say which of it is
   newest. `max_scanned` is what bounds that, and the meeting listers pass their own
   (`features/transcripts.MAX_ARTIFACT_SCAN`) rather than this module's default, because a
   per-meeting collection is a small thing to walk 1000 items of. The cap is also the limit of
   what "newest" can mean: a walk stopped by it saw a prefix of the collection in Graph's own
   order, `CollectedItems.capped` says so, and it is the *only* thing that says so — which is why
   it must mean the cap and nothing else.
3. **Do not walk at all.** Where the request budget is the point — a channel's messages, at 1
   request per second per app per tenant for a given channel
   (https://learn.microsoft.com/en-us/graph/throttling-limits) — the feature reading them makes
   one request, uses `$top` as the window, and never comes here.

Search paging is deliberately not here. `POST /search/query` takes `from`/`size` offsets instead
of an opaque cursor, so a stateless MCP tool resumes a search by re-issuing it with a larger
`from` — no cursor to carry across calls, and nothing for this module to do.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from kiota_abstractions.serialization.parsable import Parsable
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.graph_service_client import GraphServiceClient
from msgraph_core.tasks import PageIterator


class GraphCollection[T](Protocol):
    """The two members of a Graph collection response that paging needs.

    Structural rather than nominal so that the element type comes from the caller's own
    response: `await client.me.chats.get()` is a `ChatCollectionResponse`, and matching it
    against this is what makes `collect_pages` return `Chat`s. The generated collection
    responses all inherit these from `BaseCollectionPaginationCountResponse`.
    """

    @property
    def value(self) -> list[T] | None: ...

    @property
    def odata_next_link(self) -> str | None: ...


# How many items may be looked at to satisfy one request, however few of them are kept. A
# safety valve on request count, not a tuning knob: a caller that needs more than this from a
# filtered collection is asking the wrong endpoint (use search). A caller with a smaller
# collection and a tighter budget passes its own `max_scanned` — see shape 2 above.
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
#   that is otherwise fine — `[3 items, nothing, 1 item]` is the shape this walk exists for — and a
#   per-walk total would give up on a large collection that sprinkles a few of them, which is a walk
#   killed for making progress. A page that carries an item is progress and starts the count again;
#   what a *run* of nothing means is that Graph will not end this collection, which is the thing
#   worth refusing.
#
# The walk is bounded either way, and this is the whole of why: every page it follows either carried
# an item — and at most `max_scanned` items may be looked at — or extended a run at most this long.
# The two together are the only claim worth making about the total, because the arithmetic worst
# case is a collection Graph does not send: one full run of nothing after every single item, which
# is bounded (`max_scanned` runs of this length) but not small. No smaller total is available
# without giving up on a collection that is making progress, which is the trade this constant is one
# side of: a walk answering with items is never refused, and one answering with nothing stops at 11.
#
# `collect_pages` refuses a collection that exhausts this rather than returning what it has, because
# an answer cut short for that reason would be indistinguishable from one cut short by a cap and
# would mean something entirely different — the honesty the tools above are built on is that a short
# answer means a cap.
MAX_EMPTY_PAGES = 10


@dataclass(frozen=True, slots=True)
class CollectedItems[T]:
    """Up to `limit` items, and whether a cap stopped the walk with more still on offer.

    `capped` is a "may be incomplete", not a "was incomplete": it is true when a cap stopped the
    walk while a `@odata.nextLink` or an unread part of a page remained, and Graph's paging gives
    no way to know whether what was left holds anything the filter would have kept.

    What it cannot mean is anything other than a cap. An empty page carrying a next link is walked
    through rather than believed, and a walk that gives up on a collection Graph will not end
    raises instead of returning — so a caller reading this as "the caps stopped me" is reading it
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
    """Walk `first_page` and its successors, keeping matching items up to `limit`.

    `first_page` is a collection response the caller already awaited (`await
    client.me.chats.get()`), and `client` is what fetched it — its request adapter is what
    fetches every page after the first. The cast is where the element type comes back: the SDK's
    page walker hands items over as `Parsable`, having deserialized each page with
    `type(first_page)`, so what comes out of a page is what the caller's own collection response
    declared it holds.

    The loop over pages is here rather than `PageIterator.iterate`'s for the reason in the module
    docstring: `iterate` ends the walk on a page whose `value` is empty, and an empty page carrying
    an `@odata.nextLink` is Graph saying there is more. The two parts of the SDK's walker worth
    having are kept — `enumerate` reads the current page from wherever the last stop left it, and
    `next` replays the cursor and deserializes the answer — and the stop conditions are this
    module's: a cap, the end of the collection, or a run of pages carrying nothing that only a
    collection Graph will not end can produce.
    """
    items: list[T] = []
    scanned = 0
    capped = False

    def visit(item: Parsable) -> bool:
        nonlocal scanned, capped
        scanned += 1
        candidate = cast(T, item)
        if matches is None or matches(candidate):
            items.append(candidate)
        capped = len(items) >= limit or scanned >= max_scanned
        return not capped

    # The SDK leaves `RequestAdapter`'s own type parameter unbound and its callbacks untyped, so
    # both reads are unknown-typed everywhere. Taking the client rather than its adapter is what
    # keeps that confined to these lines instead of every call site.
    iterator = PageIterator(
        first_page,
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        error_mapping={"XXX": ODataError},
    )
    empty_pages_in_a_row = 0
    while True:
        # The return value says "the page ran out or the callback stopped me", which conflates the
        # empty page with the cap; `capped` is the callback's own answer and is the one read.
        looked_at_before = scanned
        _ = iterator.enumerate(visit)  # pyright: ignore[reportUnknownMemberType]
        if capped or not iterator.current_page.odata_next_link:
            return CollectedItems(items=items, capped=capped and _more_was_on_offer(iterator))
        # A page that carried an item is progress, however few were kept, and it starts the count
        # again; only a run of pages carrying nothing at all is bounded — see `MAX_EMPTY_PAGES` for
        # why that is the run and not the walk, and why it is not pooled with `max_scanned`.
        empty_pages_in_a_row = 0 if scanned > looked_at_before else empty_pages_in_a_row + 1
        assert empty_pages_in_a_row <= MAX_EMPTY_PAGES, (
            f"Microsoft Graph answered {empty_pages_in_a_row} pages in a row with nothing in them "
            f"and still advertised more of this collection ({scanned} items looked at, "
            f"{len(items)} kept)"
        )
        page = await iterator.next()
        assert page is not None, "Graph advertised a next link and then had no next page"
        iterator.current_page = page
        iterator.pause_index = 0


def _more_was_on_offer(iterator: PageIterator) -> bool:
    """Whether the page the walk stopped in still had something after the item it stopped on.

    Only meaningful where a cap stopped the walk, which is the only case it is asked about: the
    item whose visit returned `False` left `pause_index` pointing at the one after it, so a value
    short of the page's length means the rest of that page was never read, and a next link means
    the rest of the collection was not either.
    """
    page = iterator.current_page
    unread_in_page = iterator.pause_index < len(page.value or [])
    return unread_in_page or bool(page.odata_next_link)
