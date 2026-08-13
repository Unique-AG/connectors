"""Following `@odata.nextLink`, with the caps `services/teams-mcp` learned it needed.

Graph pages every list endpoint, and the whole `@odata.nextLink` URL is the cursor: it is
replayed verbatim, never decomposed (https://learn.microsoft.com/en-us/graph/paging). The SDK's
`PageIterator` does that walk, so this module is only the two lessons teams-mcp paid for in
`src/msgraph/graph-pagination.ts`:

* a scan cap as well as an item cap. Where a collection is filtered after the fact — channel
  messages are mostly system messages about members joining — "give me 20" can otherwise walk
  the entire history of a busy channel one page at a time, at 1 request per second per chat per
  tenant for the whole app (https://learn.microsoft.com/en-us/graph/throttling-limits).
* saying so. A truncated answer that looks complete is the failure mode, because the caller
  above is a language model that will summarise 20 of 4000 messages as "the discussion".

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
# filtered collection is asking the wrong endpoint (use search).
MAX_SCANNED_ITEMS = 1000


@dataclass(frozen=True, slots=True)
class CollectedItems[T]:
    """Up to `limit` items, and whether Graph might still have had more.

    `truncated` is a "may be incomplete", not a "was incomplete": it is true when a cap stopped
    the walk while a `@odata.nextLink` remained, and Graph's paging gives no way to know whether
    that next page holds anything the filter would have kept.
    """

    items: list[T]
    truncated: bool


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
    """
    items: list[T] = []
    scanned = 0

    def visit(item: Parsable) -> bool:
        nonlocal scanned
        scanned += 1
        candidate = cast(T, item)
        if matches is None or matches(candidate):
            items.append(candidate)
        return len(items) < limit and scanned < max_scanned

    # The SDK leaves `RequestAdapter`'s own type parameter unbound and `iterate`'s callback
    # untyped, so both reads are unknown-typed everywhere. Taking the client rather than its
    # adapter is what keeps that confined to these two lines instead of every call site.
    iterator = PageIterator(
        first_page,
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        error_mapping={"XXX": ODataError},
    )
    await iterator.iterate(visit)  # pyright: ignore[reportUnknownMemberType]
    return CollectedItems(items=items, truncated=_stopped_short(iterator))


def _stopped_short(iterator: PageIterator) -> bool:
    """Whether the walk ended with items still on offer.

    Two ways it can: a page was left part-read because a cap was hit mid-page (`pause_index`
    lands between the first and last item), or the last page read still advertised a next link.
    The second case also covers an empty page carrying a next link — Graph does return those,
    and the iterator treats an empty page as the end.
    """
    page = iterator.current_page
    part_read = 0 < iterator.pause_index < len(page.value or [])
    return part_read or bool(page.odata_next_link)
