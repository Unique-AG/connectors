from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel, ValidationError

from backstop_mcp.backstop_client import PageResult
from backstop_mcp.backstop_client.errors import BackstopResponseSchemaError
from backstop_mcp.backstop_client.pagination import paginate_all

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
            schema=dict[str, Any],
            max_records=None,
        )

        assert result.items == [{"id": "1", "extra": True}]
