"""Read a server-ordered collection until one page of matches is full, and say where to resume.

The search tools filter part of what they read in memory, so a Backstop page and a result page
are different sizes. This reads Backstop pages from a record offset, keeps the rows `select`
accepts, and stops at `output_page_size` rows (`page_full`) or the end of the collection
(`exhausted`). `next_offset` is the record right after the last one this call consumed, so a
resumed call neither repeats nor skips a row.

Offsets on the wire stay multiples of `api_page_size` (Backstop rejects anything else); a cursor
that lands mid-page re-reads that page and skips the rows before it.

A hidden record can keep its position but be left out of a page, so the end is where positions
reach the total, and a result that fills on a short page resumes at the next page.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import SinglePage

__all__ = ["CollectedPage", "StopReason", "collect_page"]

type StopReason = Literal["page_full", "exhausted"]


class CollectedPage[R](BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    rows: tuple[R, ...]
    # Record offset the next call starts from; `None` when nothing is left to read.
    next_offset: int | None
    stop_reason: StopReason
    records_scanned: int
    request_count: int
    total_count: int | None


async def collect_page[I, R](
    *,
    read_at: Callable[[int], Awaitable[SinglePage[I]]],
    select: Callable[[SinglePage[I]], Sequence[tuple[int, R]]],
    start_offset: int,
    output_page_size: int,
    api_page_size: int,
    concurrency: int = 1,
) -> CollectedPage[R]:
    """Fill one result page from `start_offset`.

    `read_at(offset)` fetches the Backstop page at a record offset (a multiple of
    `api_page_size`). `select(page)` returns `(index in page.items, row)` for every record that
    matches, in page order. After the first page, up to `concurrency` pages are read at once:
    a sparse in-memory filter otherwise pays one round trip per page. Pages read past the one
    that filled the result are discarded; the cursor points at the exact row.
    """
    assert output_page_size > 0 and api_page_size > 0 and concurrency > 0
    first_page_offset = start_offset - start_offset % api_page_size
    rows: list[R] = []
    scanned = 0
    requests = 0
    total_count: int | None = None
    wave = [first_page_offset]

    while True:
        pages = await asyncio.gather(*(read_at(offset) for offset in wave))
        requests += len(wave)
        for offset, page in zip(wave, pages, strict=True):
            if total_count is None:
                total_count = page.total_count
            end = offset + len(page.items)
            # Without a total, a short page is the end. With one, a short page may only be
            # missing a record this credential cannot see.
            is_last = (
                offset + api_page_size >= total_count
                if total_count is not None
                else len(page.items) < api_page_size
            )
            # Every index is a position only when the page holds all it should: the last page of
            # a collection is short without missing anything.
            complete = (
                len(page.items) == min(api_page_size, total_count - offset)
                if total_count is not None
                else True
            )
            for index, row in select(page):
                if offset + index < start_offset:
                    continue
                rows.append(row)
                if complete and len(rows) == output_page_size:
                    consumed = offset + index + 1
                    done = is_last and consumed >= end
                    return CollectedPage[R](
                        rows=tuple(rows),
                        next_offset=None if done else consumed,
                        stop_reason="exhausted" if done else "page_full",
                        records_scanned=scanned + index + 1 - max(0, start_offset - offset),
                        request_count=requests,
                        total_count=total_count,
                    )
            scanned += len(page.items) - max(0, start_offset - offset)
            if is_last:
                return CollectedPage[R](
                    rows=tuple(rows),
                    next_offset=None,
                    stop_reason="exhausted",
                    records_scanned=scanned,
                    request_count=requests,
                    total_count=total_count,
                )
            # Filled inside a short page: no index there is a known position, so take the whole
            # page and resume at the next one rather than risk a repeated or skipped row.
            if len(rows) >= output_page_size:
                return CollectedPage[R](
                    rows=tuple(rows),
                    next_offset=offset + api_page_size,
                    stop_reason="page_full",
                    records_scanned=scanned,
                    request_count=requests,
                    total_count=total_count,
                )
        wave = _next_wave(
            after=wave[-1] + api_page_size,
            api_page_size=api_page_size,
            concurrency=concurrency,
            total_count=total_count,
        )


def _next_wave(
    *, after: int, api_page_size: int, concurrency: int, total_count: int | None
) -> list[int]:
    offsets = [after + step * api_page_size for step in range(concurrency)]
    if total_count is None:
        return offsets
    # Only called when the last page read was not the end, so the first offset is in range.
    return [offset for offset in offsets if offset < total_count] or offsets[:1]
