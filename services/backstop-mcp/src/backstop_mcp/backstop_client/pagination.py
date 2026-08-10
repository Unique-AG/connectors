from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import ClassVar, Generic

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from typing_extensions import TypeVar

from backstop_mcp.backstop_client.utils import deserialize, schema_label

FetchPage = Callable[[str, dict[str, object] | None], Awaitable[httpx.Response]]

T = TypeVar("T", default=dict[str, object])


class _PageLinks(BaseModel):
    next: str | None = None


class _PageMeta(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    total_resource_count: int | None = Field(default=None, alias="totalResourceCount")


class _Page(BaseModel):
    data: list[dict[str, object]]
    # JSON:API puts `?include=`d resources in a top-level `included` array, *not* inside the
    # primary resource's `attributes`. Backstop's `include` targets are relationships (the
    # only value custom-field-definitions accepts is `lovSet`), so dropping this array would
    # silently discard everything a caller asked to side-load.
    included: list[dict[str, object]] = Field(default_factory=list)
    links: _PageLinks = _PageLinks()
    meta: _PageMeta | None = None


_PAGE_ADAPTER = TypeAdapter(_Page)


def _resource_identity(resource: dict[str, object]) -> tuple[str, str]:
    return (str(resource.get("type", "")), str(resource.get("id", "")))


@dataclass
class PageResult(Generic[T]):
    """Accumulated result of walking a JSON:API `links.next` chain.

    `included` holds the side-loaded resources from every page, deduplicated by
    (`type`, `id`) — JSON:API repeats an included resource on each page that references it.
    """

    items: list[T] = field(default_factory=list)
    included: list[dict[str, object]] = field(default_factory=list)
    total_count: int | None = None
    truncated: bool = False


async def paginate_all(
    *,
    fetch_page: FetchPage,
    first_path: str,
    max_records: int | None,
    first_page_params: dict[str, object] | None = None,
) -> PageResult:
    """Walk a JSON:API `links.next` chain, accumulating `data` from every page.

    `fetch_page` fetches a single page given a path/URL and query params (the caller supplies
    auth, retries, and the shared client); this function only parses responses and follows
    `links.next`. Stops once accumulated items reach `max_records` (if given), setting
    `truncated=True` — the triggering page is kept in full rather than trimmed to the exact
    count, since callers can trim further themselves and this keeps the truncation boundary
    simple to reason about.

    `first_page_params` is applied to `first_path` only — every later page is driven
    entirely by the literal URL Backstop returns, which already encodes its own query params.
    """
    result = PageResult()
    seen_included: set[tuple[str, str]] = set()
    path: str | None = first_path
    params = first_page_params

    while path is not None:
        response = await fetch_page(path, params)
        params = None
        # Same typed failure as item validation in `BackstopClient.paginate` — a malformed
        # 200 envelope must not escape as a raw pydantic `ValidationError`.
        page = deserialize(
            response.content,
            _PAGE_ADAPTER,
            path=path,
            schema_name=schema_label(_Page),
        )

        result.items.extend(page.data)
        for resource in page.included:
            identity = _resource_identity(resource)
            if identity in seen_included:
                continue
            seen_included.add(identity)
            result.included.append(resource)

        if result.total_count is None and page.meta is not None:
            result.total_count = page.meta.total_resource_count

        if max_records is not None and len(result.items) >= max_records:
            result.truncated = True
            break

        path = page.links.next

    return result
