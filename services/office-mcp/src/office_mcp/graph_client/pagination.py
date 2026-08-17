"""Paging via @odata.nextLink, with the guards teams-mcp learned it needed.

Graph pages every list endpoint using opaque @odata.nextLink URLs that must be replayed
verbatim. The SDK's PageIterator does the walk. This module adds two lessons from teams-mcp:

1. A scan cap as well as item cap. Filtered collections (channel messages are mostly system
   messages) can walk long histories for few kept items. A 20-item limit can scan thousands of
   messages at 1 request per second per chat per tenant.

2. Truncation signalling. A partial answer that looks complete misleads callers (models will
   summarize 20 of 4000 messages as "the discussion").

Search paging is not handled here. POST /search/query takes from/size offsets instead of a
cursor, so stateless tools resume by re-issuing with a larger from value.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from kiota_abstractions.serialization.parsable import Parsable
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.graph_service_client import GraphServiceClient
from msgraph_core.tasks import PageIterator


class GraphCollection[T](Protocol):
    """Structural type for Graph collection response fields paging needs.

    Structural typing extracts the element type from the caller's own response. `await
    client.me.chats.get()` returns ChatCollectionResponse, and matching it against this
    protocol makes `collect_pages` return Chat items. The SDK's generated collection responses
    inherit these fields from BaseCollectionPaginationCountResponse.
    """

    @property
    def value(self) -> list[T] | None: ...

    @property
    def odata_next_link(self) -> str | None: ...


# Safety valve on items examined, not a tuning knob. Callers needing more from a filtered
# collection should use the search endpoint instead.
MAX_SCANNED_ITEMS = 1000


@dataclass(frozen=True, slots=True)
class CollectedItems[T]:
    """Items collected and truncation flag.

    `truncated` is "may be incomplete", not "was incomplete". It is true when a cap stopped the
    walk while @odata.nextLink remained. Graph's paging gives no way to know whether the next
    page holds anything the filter would have kept.
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
    """Walk first_page and successors, keeping matching items up to limit.

    first_page is an already-awaited collection response; client is what fetched it and will
    fetch successive pages via its request adapter. The cast recovers the element type: the
    SDK's page walker hands items over as Parsable, deserialized with type(first_page), so the
    output type matches the caller's collection response declaration.
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

    # TRAP: SDK leaves RequestAdapter type parameter and iterate callback untyped. Taking client
    # instead of adapter keeps the unknowns to these two lines, not every call site.
    iterator = PageIterator(
        first_page,
        client.request_adapter,  # pyright: ignore[reportUnknownMemberType]
        error_mapping={"XXX": ODataError},
    )
    await iterator.iterate(visit)  # pyright: ignore[reportUnknownMemberType]
    return CollectedItems(items=items, truncated=_stopped_short(iterator))


def _stopped_short(iterator: PageIterator) -> bool:
    """Whether the walk stopped with items still on offer.

    Two scenarios: a page was left part-read, or the last page read carried an @odata.nextLink.
    An empty page with a next link also counts; Graph returns those, and the iterator treats
    empty pages as the end.

    pause_index is a resume offset, not an item position. It counts the items consumed from the
    current page, so a stop on the first item leaves 1. A value above zero and below the page
    length means some but not all of this page was read.
    """
    page = iterator.current_page
    part_read = 0 < iterator.pause_index < len(page.value or [])
    return part_read or bool(page.odata_next_link)
