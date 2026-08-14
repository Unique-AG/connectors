from collections.abc import AsyncGenerator

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition
from backstop_mcp.features.custom_fields.values import read_custom_field_value
from tests.helpers import BASE_URL, client_factory, credential


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory: BackstopClientFactory = client_factory()
    yield factory.for_credential(credential("values-bob"))
    await factory.aclose()


def _definition(
    definition_id: str, *, is_time_series: bool, name: str = "Grade"
) -> CustomFieldDefinition:
    return CustomFieldDefinition(
        id=definition_id,
        entity_type="OrganizationBean",
        name=name,
        is_time_series=is_time_series,
    )


def _series_entry(entry_id: str, value: str, effective_date: str | None) -> dict[str, object]:
    attributes: dict[str, object] = {"definitionId": "77", "value": value}
    if effective_date is not None:
        attributes["effectiveDate"] = effective_date
    return {"type": "timeSeriesCustomFieldValues", "id": entry_id, "attributes": attributes}


class TestReadCustomFieldValue:
    @pytest.mark.asyncio
    @respx.mock
    async def test_regular_path_uses_regular_custom_field_values(
        self, client: BackstopClient
    ) -> None:
        route = respx.get(f"{BASE_URL}/organizations/o1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "organizations",
                        "id": "o1",
                        "attributes": {
                            "regularCustomFieldValues": [
                                {"definitionId": "55", "value": "A"},
                                {"definitionId": "9", "value": "other"},
                            ]
                        },
                    }
                },
            )
        )

        read = await read_custom_field_value(
            client,
            entity_type="organizations",
            entity_id="o1",
            definition=_definition("55", is_time_series=False),
        )

        assert read.value == "A"
        sent_url = str(route.calls.last.request.url)
        assert "regularCustomFieldValues" in sent_url
        assert "modifiedTimestamp" in sent_url
        assert "timeSeriesCustomFieldValues" not in sent_url

    @pytest.mark.asyncio
    @respx.mock
    async def test_time_series_path_not_regular(self, client: BackstopClient) -> None:
        route = respx.get(f"{BASE_URL}/organizations/o1/timeSeriesCustomFieldValues").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        _series_entry("t1", "Warm", "2026-01-01"),
                        _series_entry("t2", "Hot", "2026-06-01"),
                    ],
                    "links": {"next": None},
                },
            )
        )

        read = await read_custom_field_value(
            client,
            entity_type="organizations",
            entity_id="o1",
            definition=_definition("77", is_time_series=True, name="Status History"),
        )

        assert read.value == "Hot"
        assert read.as_of is None
        sent_url = str(route.calls.last.request.url)
        assert "timeSeriesCustomFieldValues" in sent_url
        assert (
            "filter%5BdefinitionId%5D%5Beq%5D=77" in sent_url
            or "filter[definitionId][eq]=77" in sent_url
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_reads_the_whole_series_before_deciding_which_entry_is_latest(
        self, client: BackstopClient
    ) -> None:
        """The newest entry may be on any page, so the chain is walked to the end.

        With a record cap, `paginate` stopped early and the "latest" value was really the
        newest of an arbitrary prefix — here, the stale 2020 value on page one.
        """
        route = respx.get(f"{BASE_URL}/organizations/o1/timeSeriesCustomFieldValues").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [_series_entry("t1", "Cold", "2020-01-01")],
                        "links": {
                            "next": f"{BASE_URL}/organizations/o1/timeSeriesCustomFieldValues?p=2"
                        },
                    },
                ),
                httpx.Response(
                    200,
                    json={"data": [_series_entry("t2", "Hot", "2026-06-01")], "links": {}},
                ),
            ]
        )

        read = await read_custom_field_value(
            client,
            entity_type="organizations",
            entity_id="o1",
            definition=_definition("77", is_time_series=True),
        )

        assert read.value == "Hot"
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_orders_by_parsed_date_not_string_comparison(
        self, client: BackstopClient
    ) -> None:
        """A lexicographic compare mis-orders anything that isn't zero-padded ISO-8601.

        `"2026-9-01" > "2026-10-01"` as strings, but October is the later date.
        """
        respx.get(f"{BASE_URL}/organizations/o1/timeSeriesCustomFieldValues").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        _series_entry("t1", "September", "2026-9-01"),
                        _series_entry("t2", "October", "2026-10-01"),
                    ],
                    "links": {},
                },
            )
        )

        read = await read_custom_field_value(
            client,
            entity_type="organizations",
            entity_id="o1",
            definition=_definition("77", is_time_series=True),
        )

        assert read.value == "October"

    @pytest.mark.asyncio
    @respx.mock
    async def test_entries_without_a_date_never_win(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/o1/timeSeriesCustomFieldValues").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        _series_entry("t1", "Dated", "2001-01-01"),
                        _series_entry("t2", "Undated", None),
                    ],
                    "links": {},
                },
            )
        )

        read = await read_custom_field_value(
            client,
            entity_type="organizations",
            entity_id="o1",
            definition=_definition("77", is_time_series=True),
        )

        assert read.value == "Dated"

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_for_an_empty_series(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/o1/timeSeriesCustomFieldValues").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {}})
        )

        read = await read_custom_field_value(
            client,
            entity_type="organizations",
            entity_id="o1",
            definition=_definition("77", is_time_series=True),
        )

        assert read.value is None
        assert read.as_of is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_when_the_regular_field_is_absent(
        self, client: BackstopClient
    ) -> None:
        respx.get(f"{BASE_URL}/organizations/o1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "organizations",
                        "id": "o1",
                        "attributes": {"regularCustomFieldValues": []},
                    }
                },
            )
        )

        read = await read_custom_field_value(
            client,
            entity_type="organizations",
            entity_id="o1",
            definition=_definition("55", is_time_series=False),
        )

        assert read.value is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_regular_path_extracts_as_of_from_same_get(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/organizations/o1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "organizations",
                        "id": "o1",
                        "attributes": {
                            "regularCustomFieldValues": [{"definitionId": "55", "value": "A"}],
                            "modifiedTimestamp": "2024-06-01T12:00:00Z",
                            "modifiedBy": "alice",
                        },
                    }
                },
            )
        )

        read = await read_custom_field_value(
            client,
            entity_type="organizations",
            entity_id="o1",
            definition=_definition("55", is_time_series=False),
        )

        assert read.value == "A"
        assert read.as_of is not None
        assert read.as_of.modified_timestamp == "2024-06-01T12:00:00Z"
        assert read.as_of.modified_by == "alice"
