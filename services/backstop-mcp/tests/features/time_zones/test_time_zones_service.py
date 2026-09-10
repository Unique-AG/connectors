import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.features.time_zones import TimeZoneDto, TimeZonesService
from tests.helpers import BASE_URL, recorded_requests, resource, time_zones_service, tool_client


def tenant(name: str) -> str:
    return f"{BASE_URL}/{name}"


def _collection_page(*items: dict[str, object], next_url: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": list(items), "links": {"next": next_url}},
    )


def _zone(
    zone_id: str,
    *,
    short_name: str,
    name: str,
) -> dict[str, object]:
    return resource(zone_id, "time-zones", name=name, shortName=short_name)


_CATALOG = (
    _zone("america_new_york", short_name="US/Eastern", name="Eastern Standard Time"),
    _zone("america_chicago", short_name="America/Chicago", name="Central Standard Time"),
    _zone("pacific_honolulu", short_name="Pacific/Honolulu", name="Hawaii Standard Time"),
    _zone("us_hawaii", short_name="US/Hawaii", name="Hawaii Standard Time"),
    _zone("pacific_johnston", short_name="Pacific/Johnston", name="Hawaii Standard Time"),
    _zone("decoy_named_eastern", short_name="Not/Eastern", name="US/Eastern"),
)


def _filter_params(params: httpx.QueryParams) -> list[str]:
    return [name for name in params.keys() if name.startswith("filter[")]


class TestResolve:
    @respx.mock
    async def test_resolves_short_name_to_that_zone(self) -> None:
        base_url = tenant("tz-short-name")
        zones_route = respx.get(f"{base_url}/time-zones").mock(
            return_value=_collection_page(*_CATALOG)
        )

        async with tool_client(base_url) as client:
            service = time_zones_service(client)
            result = await service.resolve("US/Eastern")

        assert type(service) is TimeZonesService
        assert zones_route.call_count == 1
        assert _filter_params(recorded_requests(zones_route.calls)[0].url.params) == []
        assert type(result) is TimeZoneDto
        assert result.id == "america_new_york"
        assert result.short_name == "US/Eastern"

    @respx.mock
    async def test_matches_short_name_case_insensitively(self) -> None:
        base_url = tenant("tz-short-name-case")
        respx.get(f"{base_url}/time-zones").mock(return_value=_collection_page(*_CATALOG))

        async with tool_client(base_url) as client:
            result = await time_zones_service(client).resolve("us/eastern")

        assert result.id == "america_new_york"
        assert result.short_name == "US/Eastern"

    @respx.mock
    async def test_resolves_id_to_that_zone_short_name(self) -> None:
        base_url = tenant("tz-id")
        respx.get(f"{base_url}/time-zones").mock(return_value=_collection_page(*_CATALOG))

        async with tool_client(base_url) as client:
            result = await time_zones_service(client).resolve("america_chicago")

        assert result.id == "america_chicago"
        assert result.short_name == "America/Chicago"

    @respx.mock
    async def test_unique_name_resolves(self) -> None:
        base_url = tenant("tz-unique-name")
        respx.get(f"{base_url}/time-zones").mock(return_value=_collection_page(*_CATALOG))

        async with tool_client(base_url) as client:
            result = await time_zones_service(client).resolve("Eastern Standard Time")

        assert result.id == "america_new_york"
        assert result.short_name == "US/Eastern"

    @respx.mock
    async def test_ambiguous_name_raises_with_candidate_short_names(self) -> None:
        base_url = tenant("tz-ambiguous-name")
        respx.get(f"{base_url}/time-zones").mock(return_value=_collection_page(*_CATALOG))

        async with tool_client(base_url) as client:
            with pytest.raises(ToolError, match="Hawaii Standard Time") as raised:
                await time_zones_service(client).resolve("Hawaii Standard Time")

        message = str(raised.value)
        assert "Pacific/Honolulu" in message
        assert "US/Hawaii" in message
        assert "Pacific/Johnston" in message

    @respx.mock
    async def test_unknown_value_raises(self) -> None:
        base_url = tenant("tz-unknown")
        respx.get(f"{base_url}/time-zones").mock(return_value=_collection_page(*_CATALOG))

        async with tool_client(base_url) as client:
            with pytest.raises(ToolError, match="Mars/Olympus") as raised:
                await time_zones_service(client).resolve("Mars/Olympus")

        assert "US/Eastern" in str(raised.value)
        assert "America/Chicago" in str(raised.value)

    @respx.mock
    async def test_short_name_wins_over_a_matching_name(self) -> None:
        base_url = tenant("tz-short-name-wins")
        respx.get(f"{base_url}/time-zones").mock(return_value=_collection_page(*_CATALOG))

        async with tool_client(base_url) as client:
            result = await time_zones_service(client).resolve("US/Eastern")

        assert result.id == "america_new_york"
        assert result.short_name == "US/Eastern"

    @respx.mock
    async def test_duplicate_short_name_raises_without_picking(self) -> None:
        base_url = tenant("tz-dup-short-name")
        respx.get(f"{base_url}/time-zones").mock(
            return_value=_collection_page(
                _zone("a", short_name="US/Eastern", name="Eastern Standard Time"),
                _zone("b", short_name="US/Eastern", name="Also Eastern"),
            )
        )

        async with tool_client(base_url) as client:
            with pytest.raises(ToolError, match="US/Eastern"):
                await time_zones_service(client).resolve("US/Eastern")

    @respx.mock
    async def test_does_not_send_filter_query_params(self) -> None:
        base_url = tenant("tz-no-filter")
        zones_route = respx.get(f"{base_url}/time-zones").mock(
            return_value=_collection_page(*_CATALOG)
        )

        async with tool_client(base_url) as client:
            await time_zones_service(client).resolve("US/Eastern")

        assert _filter_params(recorded_requests(zones_route.calls)[0].url.params) == []
