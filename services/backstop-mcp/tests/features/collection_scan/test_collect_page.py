from collections.abc import Callable, Sequence

import pytest

from backstop_mcp.backstop_client import SinglePage
from backstop_mcp.features.collection_scan import CollectedPage, collect_page

type Record = int


class FakeCollection:
    """A server-ordered collection of ints 0..size-1, read a page at a time."""

    def __init__(self, size: int, *, page_size: int, with_total: bool = True) -> None:
        self.size: int = size
        self.page_size: int = page_size
        self.with_total: bool = with_total
        self.reads: list[int] = []

    async def read_at(self, offset: int) -> SinglePage[Record]:
        assert offset % self.page_size == 0
        self.reads.append(offset)
        return SinglePage[Record](
            items=list(range(offset, min(offset + self.page_size, self.size))),
            total_count=self.size if self.with_total else None,
        )


def evens(page: SinglePage[Record]) -> Sequence[tuple[int, Record]]:
    return [(index, item) for index, item in enumerate(page.items) if item % 2 == 0]


def every(page: SinglePage[Record]) -> Sequence[tuple[int, Record]]:
    return list(enumerate(page.items))


async def collect(
    collection: FakeCollection,
    *,
    start_offset: int = 0,
    output_page_size: int = 5,
    concurrency: int = 1,
    select: Callable[[SinglePage[Record]], Sequence[tuple[int, Record]]] = every,
) -> CollectedPage[Record]:
    return await collect_page(
        read_at=collection.read_at,
        select=select,
        start_offset=start_offset,
        output_page_size=output_page_size,
        api_page_size=collection.page_size,
        concurrency=concurrency,
    )


class TestCollectPage:
    async def test_a_full_page_points_the_cursor_at_the_next_row(self) -> None:
        page = await collect(FakeCollection(20, page_size=10), output_page_size=5)

        assert page.rows == (0, 1, 2, 3, 4)
        assert page.stop_reason == "page_full"
        assert page.next_offset == 5

    async def test_resuming_mid_page_neither_repeats_nor_skips(self) -> None:
        collection = FakeCollection(20, page_size=10)
        first = await collect(collection, output_page_size=7)
        assert first.next_offset is not None
        second = await collect(collection, start_offset=first.next_offset, output_page_size=7)

        assert first.rows + second.rows == tuple(range(14))
        assert collection.reads == [0, 0, 10]

    async def test_the_last_row_of_the_collection_ends_without_a_cursor(self) -> None:
        page = await collect(FakeCollection(10, page_size=10), output_page_size=10)

        assert page.rows == tuple(range(10))
        assert page.stop_reason == "exhausted"
        assert page.next_offset is None

    async def test_a_short_collection_is_exhausted(self) -> None:
        page = await collect(FakeCollection(3, page_size=10), output_page_size=5)

        assert page.rows == (0, 1, 2)
        assert page.stop_reason == "exhausted"
        assert page.next_offset is None

    async def test_without_a_total_a_short_page_is_the_end(self) -> None:
        page = await collect(
            FakeCollection(13, page_size=10, with_total=False), output_page_size=50
        )

        assert page.rows == tuple(range(13))
        assert page.stop_reason == "exhausted"

    async def test_in_memory_filter_reads_on_until_the_page_fills(self) -> None:
        page = await collect(FakeCollection(100, page_size=10), output_page_size=8, select=evens)

        assert page.rows == (0, 2, 4, 6, 8, 10, 12, 14)
        assert page.next_offset == 15

    async def test_a_sparse_filter_reads_on_to_the_end(self) -> None:
        page = await collect(FakeCollection(100, page_size=10), output_page_size=60, select=evens)

        assert page.rows == tuple(range(0, 100, 2))
        assert page.stop_reason == "exhausted"
        assert page.next_offset is None
        assert page.records_scanned == 100

    async def test_later_pages_are_read_in_waves_within_the_total(self) -> None:
        collection = FakeCollection(35, page_size=10)
        page = await collect(collection, output_page_size=50, select=evens, concurrency=5)

        assert page.stop_reason == "exhausted"
        assert collection.reads == [0, 10, 20, 30]
        assert page.request_count == 4

    async def test_a_short_page_mid_collection_is_an_invariant_failure(self) -> None:
        async def short_read(offset: int) -> SinglePage[Record]:
            return SinglePage[Record](items=[offset], total_count=100)

        with pytest.raises(AssertionError, match="offsets would drift"):
            _ = await collect_page(
                read_at=short_read,
                select=every,
                start_offset=0,
                output_page_size=5,
                api_page_size=10,
            )
