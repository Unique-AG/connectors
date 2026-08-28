import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import ClassVar, Generic, TypeVar, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client.utils import deserialize

FetchPage = Callable[[str, dict[str, object] | None], Awaitable[httpx.Response]]
# Query params for the page at a given offset, using the page size the first page actually
# returned. Supplied by the caller that owns the limit/offset parameter *names*
# (`BackstopClient.paginate`), so this module never has to know them: it decides which
# offsets to ask for, not what they are called on the wire.
# `(offset, page_size)` — `page_size` is what Backstop served on page one, which later
# pages must send as the limit. Offsets are multiples of that size; keeping the originally
# requested limit after a cap would make them illegal.
OffsetPageParams = Callable[[int, int], dict[str, object]]

T = TypeVar("T", default=dict[str, object])


class _PageLinks(BaseModel):
    next: str | None = None


class _PageMeta(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    total_resource_count: int | None = Field(default=None, alias="totalResourceCount")


class _Page(BaseModel, Generic[T]):
    data: list[T]
    # JSON:API puts `?include=`d resources in a top-level `included` array, *not* inside the
    # primary resource's `attributes`. Backstop's `include` targets are relationships (the
    # only value custom-field-definitions accepts is `lovSet`), so dropping this array would
    # silently discard everything a caller asked to side-load.
    included: list[dict[str, object]] = Field(default_factory=list)
    links: _PageLinks = _PageLinks()
    meta: _PageMeta | None = None


def _resource_identity(resource: dict[str, object]) -> tuple[str, str]:
    return (str(resource.get("type", "")), str(resource.get("id", "")))


class SinglePage[T](BaseModel):
    """One parsed JSON:API page — the primitive both `fetch_page` and `paginate_all` share.

    `total_count` is `meta.totalResourceCount` verbatim — untrustworthy on any endpoint where a
    date filter degrades it to a running count rather than a true total (see activity streams).
    `next_path` is `links.next` verbatim; a caller doing explicit offset paging should ignore it
    rather than follow it, since some endpoints drop the link under a date filter while
    pagination still works via `page[offset]`.
    """

    items: list[T] = Field(default_factory=list)
    included: list[dict[str, object]] = Field(default_factory=list)
    total_count: int | None = None
    next_path: str | None = None


def parse_page(content: bytes, schema: type[T], *, path: str) -> SinglePage[T]:
    """Parse one page's response body as `_Page[schema]` — the one parsing path.

    Shared by `BackstopClient.fetch_page` (single explicit page) and `paginate_all` (the
    `links.next` walk), so a malformed envelope or item fails the same way — a
    `BackstopResponseSchemaError` — no matter which caller triggered it.
    """
    # Parameterized page model — `adapter_for` caches the compiled adapter process-wide under
    # this GenericAlias key, so a 10k-record walk does not rebuild schemas per page/item.
    page_schema = _Page[schema]
    page = cast(_Page[T], deserialize(content, page_schema, path=path))
    # Already validated as `_Page[T]`; `model_construct` skips a second pass over every item.
    return SinglePage[T].model_construct(
        items=page.data,
        included=page.included,
        total_count=page.meta.total_resource_count if page.meta is not None else None,
        next_path=page.links.next,
    )


class PageResult[T](BaseModel):
    """Accumulated result of reading every page of a JSON:API collection.

    `included` holds the side-loaded resources from every page, deduplicated by
    (`type`, `id`) — JSON:API repeats an included resource on each page that references it.

    `request_count` is how many pages were actually fetched, which is the walk's real cost. A
    caller cannot infer it from `len(items)`: the page size Backstop serves may be below the one
    asked for, the last page is short, and a cap keeps the page that crossed it in full. A tool
    that publishes its request count to the model has to be told, not guess.
    """

    items: list[T] = Field(default_factory=list)
    included: list[dict[str, object]] = Field(default_factory=list)
    total_count: int | None = None
    truncated: bool = False
    request_count: int = 0


@dataclass
class _Accumulator(Generic[T]):
    """Pages in, one `PageResult` out — the part both walk strategies share.

    Owns the `included` dedup set alongside the result it belongs to, so neither strategy can
    accumulate one without the other. `total_count` is kept from the first page that reports
    one: later pages of the same chain repeat it, and some endpoints omit it after page one.
    One `absorb` is one page fetched, so counting requests here counts them for both strategies.
    """

    result: PageResult[T]
    _seen_included: set[tuple[str, str]] = field(default_factory=set)

    def absorb(self, page: SinglePage[T]) -> None:
        self.result.request_count += 1
        self.result.items.extend(page.items)
        for resource in page.included:
            identity = _resource_identity(resource)
            if identity in self._seen_included:
                continue
            self._seen_included.add(identity)
            self.result.included.append(resource)
        if self.result.total_count is None and page.total_count is not None:
            self.result.total_count = page.total_count

    def filled(self, max_records: int | None) -> bool:
        return max_records is not None and len(self.result.items) >= max_records


async def paginate_all(
    *,
    fetch_page: FetchPage,
    first_path: str,
    schema: type[T],
    max_records: int | None,
    first_page_params: dict[str, object] | None = None,
    offset_params: OffsetPageParams | None = None,
) -> PageResult[T]:
    """Read every page of a JSON:API collection, accumulating `data` from all of them.

    `fetch_page` fetches a single page given a path/URL and query params (the caller supplies
    auth, retries, and the shared client); this function parses each response via `parse_page`
    (envelope + typed items in one pass). Stops once accumulated items reach `max_records` (if
    given), setting `truncated=True` — the triggering page is kept in full rather than trimmed to
    the exact count, since callers can trim further themselves and this keeps the truncation
    boundary simple to reason about.

    `first_page_params` is applied to `first_path` only. By default every later page is driven
    entirely by the literal URL Backstop returns in `links.next`, which already encodes its own
    query params — and strictly one at a time, since each URL is only known once its predecessor
    has been read.

    Passing `offset_params` opts that second page onwards into being requested *concurrently* by
    offset instead, which is worth real wall clock: the per-user gate allows five in flight, so a
    serial chain runs at an effective concurrency of one. It is opt-in because it trades
    `links.next` — which is always right — for `meta.totalResourceCount`, which is not: on
    endpoints where a date filter degrades it to a running count (see `SinglePage`), the fan-out
    would ask for the wrong number of pages and quietly return a short answer. Opt in only where
    the total is known to be a true total. A collection changing under a concurrent walk can also
    duplicate or skip a row across the offset boundary, exactly as it can under a serial one.

    Each later call is `offset_params(offset, page_size)` where `page_size` is `len(first.items)`
    — the limit Backstop actually served, which may be below what was asked. Offsets stride by
    that size and the callback must send it as the limit; Backstop rejects an offset that is not
    a multiple of the limit on the wire.
    """
    accumulator: _Accumulator[T] = _Accumulator(PageResult[T].model_construct())
    first = parse_page(
        (await fetch_page(first_path, first_page_params)).content, schema, path=first_path
    )
    accumulator.absorb(first)
    if accumulator.filled(max_records):
        accumulator.result.truncated = True
        return accumulator.result

    # `first.items` is the page size Backstop actually served, which is what offsets have to be
    # multiples of — it rejects an offset that is not, and it caps the limit on some collections
    # below what was asked for. An empty first page leaves nothing to stride by, so that case
    # falls through to `links.next`.
    if offset_params is not None and first.total_count is not None and first.items:
        page_size = len(first.items)
        pages = await _fetch_offsets(
            fetch_page=fetch_page,
            path=first_path,
            schema=schema,
            page_size=page_size,
            offsets=_offsets(
                total_count=first.total_count,
                page_size=page_size,
                max_records=max_records,
            ),
            offset_params=offset_params,
        )
        for page in pages:
            accumulator.absorb(page)
        accumulator.result.truncated = accumulator.filled(max_records)
        return accumulator.result

    path = first.next_path
    while path is not None:
        page = parse_page((await fetch_page(path, None)).content, schema, path=path)
        accumulator.absorb(page)
        if accumulator.filled(max_records):
            accumulator.result.truncated = True
            break
        path = page.next_path

    return accumulator.result


def _offsets(*, total_count: int, page_size: int, max_records: int | None) -> range:
    """Offsets of every page after the first.

    Capped at `max_records` the same way the serial walk stops: the page that crosses the
    threshold is requested whole, so this can return slightly more than `max_records` items.
    """
    wanted = total_count if max_records is None else min(total_count, max_records)
    return range(page_size, wanted, page_size)


async def _fetch_offsets(
    *,
    fetch_page: FetchPage,
    path: str,
    schema: type[T],
    page_size: int,
    offsets: range,
    offset_params: OffsetPageParams,
) -> list[SinglePage[T]]:
    """Fetch the given offsets concurrently, parsed, in offset order.

    Concurrency is bounded by whatever gate `fetch_page` holds rather than by anything here —
    `BackstopClient` acquires the per-user slot around each single request. No
    `return_exceptions`: one failed page makes the whole collection incomplete, and a caller
    handed a silently short list has no way to tell.
    """
    responses = await asyncio.gather(
        *(fetch_page(path, offset_params(offset, page_size)) for offset in offsets)
    )
    return [parse_page(response.content, schema, path=path) for response in responses]
