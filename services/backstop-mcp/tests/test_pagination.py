import httpx
import pytest
import respx
from pydantic import BaseModel, ValidationError

from backstop_mcp.backstop_client import (
    BackstopResponseSchemaError,
    PageResult,
    SinglePage,
    paginate_all,
    parse_page,
)
from tests.helpers import recorded_params

_BASE_URL = "https://example.backstopsolutions.com"


class _Record(BaseModel):
    id: str


def _page(
    data: list[dict[str, object]],
    *,
    next_path: str | None = None,
    total_count: int | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "data": data,
        "links": {"self": "/records", "next": next_path, "prev": None},
    }
    if total_count is not None:
        body["meta"] = {"totalResourceCount": total_count}
    return body


async def _fetch_page(path: str, params: dict[str, object] | None) -> httpx.Response:
    async with httpx.AsyncClient(base_url=_BASE_URL) as client:
        return await client.get(path, params=params)  # pyright: ignore[reportArgumentType]


def _offset_params(offset: int, page_size: int) -> dict[str, object]:
    return {"page[limit]": page_size, "page[offset]": offset}


def _requested_offsets(route: respx.Route) -> list[str]:
    return [params["page[offset]"] for params in recorded_params(route)]


class TestParsePage:
    """`parse_page` is the primitive both `fetch_page` and `paginate_all` share."""

    def test_parses_items_included_total_count_and_next_path(self) -> None:
        content = _page(
            [{"id": "1"}, {"id": "2"}],
            next_path="/records?page[offset]=25",
            total_count=42,
        )
        content["included"] = [{"type": "lov-system-sets", "id": "9"}]

        result = parse_page(httpx.Response(200, json=content).content, _Record, path="/records")

        assert result == SinglePage(
            items=[_Record(id="1"), _Record(id="2")],
            included=[{"type": "lov-system-sets", "id": "9"}],
            total_count=42,
            next_path="/records?page[offset]=25",
        )

    def test_defaults_when_no_meta_or_next_link(self) -> None:
        result = parse_page(
            httpx.Response(200, json=_page([{"id": "1"}])).content, _Record, path="/records"
        )

        assert result == SinglePage(items=[_Record(id="1")], total_count=None, next_path=None)

    def test_malformed_item_raises_backstop_response_schema_error(self) -> None:
        content = _page([{"not_id": "1"}])

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            parse_page(httpx.Response(200, json=content).content, _Record, path="/records")

        assert exc_info.value.path == "/records"
        assert exc_info.value.schema_name == "_Page[_Record]"


class TestPaginateAll:
    @pytest.mark.asyncio
    @respx.mock
    async def test_single_page_with_no_links_next_is_not_truncated(self) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json=_page([{"id": "1"}, {"id": "2"}]))
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=None,
        )

        assert result == PageResult(
            items=[_Record(id="1"), _Record(id="2")], total_count=None, truncated=False
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_follows_links_next_across_multiple_pages(self) -> None:
        # A single route matches every request to /records regardless of its query string
        # (respx routes without a `params=` constraint match any query string, and route
        # matching is order-independent per-route rather than per-query-string). Using
        # `side_effect` with a list serves each response exactly once, in order, which is
        # what we actually need to test here — the sequence `paginate_all` follows.
        respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200, json=_page([{"id": "1"}], next_path="/records?page[cursor]=abc")
                ),
                httpx.Response(
                    200, json=_page([{"id": "2"}], next_path="/records?page[cursor]=def")
                ),
                httpx.Response(200, json=_page([{"id": "3"}])),
            ]
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=None,
        )

        assert result.items == [_Record(id="1"), _Record(id="2"), _Record(id="3")]
        assert result.truncated is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_stops_early_once_max_records_reached_and_keeps_last_page_whole(
        self,
    ) -> None:
        # See the note in test_follows_links_next_across_multiple_pages: a single route with
        # `side_effect` serves each response exactly once, in order, regardless of the query
        # string paginate_all actually requests.
        route = respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=_page([{"id": "1"}, {"id": "2"}], next_path="/records?page[cursor]=abc"),
                ),
                httpx.Response(
                    200,
                    json=_page([{"id": "3"}, {"id": "4"}], next_path="/records?page[cursor]=def"),
                ),
                httpx.Response(200, json=_page([{"id": "5"}])),
            ]
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=3,
        )

        # max_records=3 is reached mid-second-page (4 accumulated) — the page that crosses
        # the threshold is kept in full rather than trimmed, so 4 items come back, not 3.
        assert result.items == [
            _Record(id="1"),
            _Record(id="2"),
            _Record(id="3"),
            _Record(id="4"),
        ]
        assert result.truncated is True
        # Only the first two responses should have been consumed — the third page must not
        # be fetched once max_records is reached.
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_surfaces_total_resource_count_from_meta(self) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json=_page([{"id": "1"}], total_count=1234))
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=None,
        )

        assert result.total_count == 1234

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_page_envelope_raises_backstop_response_schema_error(
        self,
    ) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json={"data": "not-a-list"})
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await paginate_all(
                fetch_page=_fetch_page,
                first_path="/records",
                schema=_Record,
                max_records=None,
            )

        assert exc_info.value.path == "/records"
        assert exc_info.value.schema_name == "_Page[_Record]"
        assert isinstance(exc_info.value.cause, ValidationError)

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_item_raises_backstop_response_schema_error(self) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json=_page([{"not_id": "1"}]))
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await paginate_all(
                fetch_page=_fetch_page,
                first_path="/records",
                schema=_Record,
                max_records=None,
            )

        assert exc_info.value.path == "/records"
        assert exc_info.value.schema_name == "_Page[_Record]"
        assert isinstance(exc_info.value.cause, ValidationError)

    @pytest.mark.asyncio
    @respx.mock
    async def test_dict_schema_keeps_raw_item_dicts(self) -> None:
        respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json=_page([{"id": "1", "extra": True}]))
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=dict[str, object],
            max_records=None,
        )

        assert result.items == [{"id": "1", "extra": True}]


class TestPaginateOffsets:
    """`offset_params` opts page two onwards into being requested concurrently by offset."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_fans_out_to_every_offset_the_total_implies(self) -> None:
        route = respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(200, json=_page([{"id": "1"}, {"id": "2"}], total_count=5)),
                httpx.Response(200, json=_page([{"id": "3"}, {"id": "4"}], total_count=5)),
                httpx.Response(200, json=_page([{"id": "5"}], total_count=5)),
            ]
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=None,
            first_page_params={"page[limit]": 2, "page[offset]": 0},
            offset_params=_offset_params,
        )

        assert [record.id for record in result.items] == ["1", "2", "3", "4", "5"]
        assert result.truncated is False
        assert result.total_count == 5
        # Strided by the page size the first page actually returned, never by links.next.
        assert sorted(_requested_offsets(route)) == ["0", "2", "4"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_later_pages_use_the_served_page_size_not_the_requested_limit(self) -> None:
        # Backstop caps some collections below the asked-for limit. Offsets must be
        # multiples of the limit on the wire, so later pages have to send the size
        # page one actually returned — not the 10 that was asked for.
        route = respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(200, json=_page([{"id": "1"}, {"id": "2"}], total_count=5)),
                httpx.Response(200, json=_page([{"id": "3"}, {"id": "4"}], total_count=5)),
                httpx.Response(200, json=_page([{"id": "5"}], total_count=5)),
            ]
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=None,
            first_page_params={"page[limit]": 10, "page[offset]": 0},
            offset_params=_offset_params,
        )

        assert [record.id for record in result.items] == ["1", "2", "3", "4", "5"]
        requested = recorded_params(route)
        assert requested[0]["page[limit]"] == "10"
        assert sorted(params["page[offset]"] for params in requested) == ["0", "2", "4"]
        assert [params["page[limit]"] for params in requested[1:]] == ["2", "2"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_items_are_ordered_by_offset_not_by_completion(self) -> None:
        # Concurrent pages can land in any order; the result must still read like the collection.
        respx.get(f"{_BASE_URL}/records", params={"page[offset]": "0"}).mock(
            return_value=httpx.Response(200, json=_page([{"id": "1"}, {"id": "2"}], total_count=6))
        )
        respx.get(f"{_BASE_URL}/records", params={"page[offset]": "2"}).mock(
            return_value=httpx.Response(200, json=_page([{"id": "3"}, {"id": "4"}], total_count=6))
        )
        respx.get(f"{_BASE_URL}/records", params={"page[offset]": "4"}).mock(
            return_value=httpx.Response(200, json=_page([{"id": "5"}, {"id": "6"}], total_count=6))
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=None,
            first_page_params={"page[limit]": 2, "page[offset]": 0},
            offset_params=_offset_params,
        )

        assert [record.id for record in result.items] == ["1", "2", "3", "4", "5", "6"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_links_next_when_there_is_no_total(self) -> None:
        # No `meta.totalResourceCount` means no offsets can be derived — the walk must degrade
        # to the chain rather than stop at page one.
        route = respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(200, json=_page([{"id": "1"}], next_path="/records?page[offset]=1")),
                httpx.Response(200, json=_page([{"id": "2"}])),
            ]
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=None,
            first_page_params={"page[limit]": 2, "page[offset]": 0},
            offset_params=_offset_params,
        )

        assert [record.id for record in result.items] == ["1", "2"]
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_single_page_collection_asks_for_nothing_more(self) -> None:
        route = respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json=_page([{"id": "1"}, {"id": "2"}], total_count=2))
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=None,
            first_page_params={"page[limit]": 2, "page[offset]": 0},
            offset_params=_offset_params,
        )

        assert [record.id for record in result.items] == ["1", "2"]
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_empty_first_page_strides_by_nothing(self) -> None:
        # A zero-length page gives no stride to offset by; asking anyway would divide by zero.
        route = respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json=_page([], total_count=9))
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=None,
            first_page_params={"page[limit]": 2, "page[offset]": 0},
            offset_params=_offset_params,
        )

        assert result.items == []
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_stops_at_max_records_keeping_the_crossing_page_whole(self) -> None:
        route = respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(200, json=_page([{"id": "1"}, {"id": "2"}], total_count=100)),
                httpx.Response(200, json=_page([{"id": "3"}, {"id": "4"}], total_count=100)),
            ]
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=3,
            first_page_params={"page[limit]": 2, "page[offset]": 0},
            offset_params=_offset_params,
        )

        # Same boundary as the serial walk: 4 items back for max_records=3, marked truncated.
        assert [record.id for record in result.items] == ["1", "2", "3", "4"]
        assert result.truncated is True
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_max_records_reached_on_the_first_page_asks_for_nothing_more(self) -> None:
        route = respx.get(f"{_BASE_URL}/records").mock(
            return_value=httpx.Response(200, json=_page([{"id": "1"}, {"id": "2"}], total_count=99))
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=2,
            first_page_params={"page[limit]": 2, "page[offset]": 0},
            offset_params=_offset_params,
        )

        assert [record.id for record in result.items] == ["1", "2"]
        assert result.truncated is True
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_included_is_deduplicated_across_concurrent_pages(self) -> None:
        shared = {"type": "products", "id": "9"}
        first = _page([{"id": "1"}, {"id": "2"}], total_count=4)
        first["included"] = [shared]
        second = _page([{"id": "3"}, {"id": "4"}], total_count=4)
        second["included"] = [shared, {"type": "products", "id": "10"}]
        respx.get(f"{_BASE_URL}/records").mock(
            side_effect=[
                httpx.Response(200, json=first),
                httpx.Response(200, json=second),
            ]
        )

        result = await paginate_all(
            fetch_page=_fetch_page,
            first_path="/records",
            schema=_Record,
            max_records=None,
            first_page_params={"page[limit]": 2, "page[offset]": 0},
            offset_params=_offset_params,
        )

        assert result.included == [shared, {"type": "products", "id": "10"}]

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_failed_page_fails_the_whole_walk(self) -> None:
        # A silently short collection is worse than an error the caller can see.
        respx.get(f"{_BASE_URL}/records", params={"page[offset]": "0"}).mock(
            return_value=httpx.Response(200, json=_page([{"id": "1"}, {"id": "2"}], total_count=4))
        )
        respx.get(f"{_BASE_URL}/records", params={"page[offset]": "2"}).mock(
            return_value=httpx.Response(200, json=_page([{"not_id": "3"}], total_count=4))
        )

        with pytest.raises(BackstopResponseSchemaError):
            await paginate_all(
                fetch_page=_fetch_page,
                first_path="/records",
                schema=_Record,
                max_records=None,
                first_page_params={"page[limit]": 2, "page[offset]": 0},
                offset_params=_offset_params,
            )
