from datetime import date

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.activity_history import (
    entity_activities_request_body,
    fetch_entity_activities,
    party_bean,
)
from tests.helpers import BASE_URL, recorded_json_bodies
from tests.server.tools.helpers import object_dict

_URL = f"{BASE_URL}/entity-activities"


def _body_attributes(body: dict[str, object]) -> dict[str, object]:
    return object_dict(object_dict(body["data"])["attributes"])


def _page(*rows: dict[str, object], total: int | None = None) -> httpx.Response:
    return httpx.Response(
        201,
        json={
            "data": {
                "id": -1,
                "type": "entity-activities",
                "attributes": {
                    "totalCount": len(rows) if total is None else total,
                    "results": list(rows),
                    "shouldIncludeDescription": False,
                },
            }
        },
    )


def _meeting(row_id: int, *, title: str = "Meeting") -> dict[str, object]:
    return {
        "id": row_id,
        "type": "Meeting",
        "activityType": "meeting",
        "title": title,
        "effectiveDate": "8/3/2026",
        "createdAt": "8/3/2026",
        "modifiedAt": "8/3/2026",
        "startDate": "2026-08-03T11:00:00.000-0400",
        "stopDate": "2026-08-03T12:00:00.000-0400",
        "meetingType": "Face to Face",
        "activityTags": [{"id": 474963, "name": "AT: Dispersion"}],
        "attendees": [{"name": "Ada"}],
        "author": {"name": "Emily Orscheln", "id": 3566561},
        "associatedWith": [
            {
                "resourceType": "organizations",
                "resourceId": "341681749",
                "resourceLink": "https://example.backstopsolutions.com/backstop/api/organizations/341681749",
            }
        ],
        "attachmentsCount": 0,
    }


class TestPartyBean:
    def test_encodes_the_measured_associated_withs_form(self) -> None:
        assert party_bean("354566359") == "PartyBean_354566359"


class TestEntityActivitiesRequestBody:
    def test_pins_the_measured_search_envelope(self) -> None:
        body = entity_activities_request_body(
            page_num=1,
            page_size=500,
            start_date=date(2025, 8, 20),
            end_date=date(2026, 8, 20),
            types=("meeting_call", "email"),
            associated_withs=("PartyBean_354566359",),
            activity_tags=("474963", "455289"),
            authors=("achandrinou@deepcapitalgroup.com",),
            include_description=False,
        )

        attributes = _body_attributes(body)
        assert object_dict(body["data"])["type"] == "entity-activities"
        assert attributes["pageNum"] == 1
        assert attributes["pageSize"] == 500
        assert "shouldIncludeDescription" not in attributes
        assert attributes["includeFields"] == ["associatedWith"]
        assert attributes["sorts"] == [{"columnName": "effectiveDate", "ascending": False}]
        filters = object_dict(attributes["filters"])
        assert filters["effectiveDate"] == {
            "startTimestamp": "2025-08-20T00:00:00",
            "endTimestamp": "2026-08-20T23:59:59",
        }
        assert filters["types"] == ["meeting_call", "email"]
        assert filters["associatedWiths"] == ["PartyBean_354566359"]
        assert filters["activityTags"] == ["474963", "455289"]
        assert filters["authors"] == [
            {"searchValue": "achandrinou@deepcapitalgroup.com", "isEmail": True}
        ]

    def test_description_flag_is_opt_in(self) -> None:
        attributes = _body_attributes(
            entity_activities_request_body(
                page_num=1,
                page_size=50,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
                types=(),
                associated_withs=(),
                activity_tags=("474963",),
                authors=(),
                include_description=True,
            )
        )

        assert attributes["shouldIncludeDescription"] is True
        assert attributes["includeFields"] == ["associatedWith", "description"]


class TestFetchEntityActivities:
    @pytest.mark.asyncio
    @respx.mock
    async def test_one_page_projects_us_dates_and_pins_the_body(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(_URL).mock(return_value=_page(_meeting(76715331), total=1))

        result = await fetch_entity_activities(
            client,
            start_date=date(2025, 8, 20),
            end_date=date(2026, 8, 20),
            page_size=5,
        )

        assert route.call_count == 1
        body = recorded_json_bodies(route)[0]
        assert _body_attributes(body)["pageNum"] == 1
        assert result.pages_fetched == 1
        assert result.total_count == 1
        assert result.rows_dropped == 0
        row = result.rows[0]
        assert row.id == "76715331"
        assert row.effective_date == date(2026, 8, 3)
        assert row.meeting_type == "Face to Face"
        assert row.tags[0].id == "474963"
        assert row.associated_with[0].id == "341681749"
        assert row.author is not None
        assert row.author.id == "3566561"

    @pytest.mark.asyncio
    @respx.mock
    async def test_walks_page_num_until_a_short_page(self, client: BackstopClient) -> None:
        route = respx.post(_URL).mock(
            side_effect=[
                _page(_meeting(1), _meeting(2), total=3),
                _page(_meeting(3), total=3),
            ]
        )

        result = await fetch_entity_activities(
            client,
            start_date=date(2024, 1, 1),
            end_date=date(2026, 8, 20),
            page_size=2,
        )

        assert route.call_count == 2
        assert [_body_attributes(body)["pageNum"] for body in recorded_json_bodies(route)] == [
            1,
            2,
        ]
        assert [row.id for row in result.rows] == ["1", "2", "3"]
        assert result.truncated_by_row_cap is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_clamps_page_num_times_page_size_before_requesting(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(_URL).mock(
            side_effect=[
                _page(*(_meeting(index) for index in range(10)), total=100),
                _page(*(_meeting(index) for index in range(10, 20)), total=100),
            ]
        )

        result = await fetch_entity_activities(
            client,
            start_date=date(2000, 1, 1),
            end_date=date(2026, 12, 31),
            page_size=10,
            max_retrievable=20,
        )

        assert result.ceiling_clamped is True
        assert route.call_count == 2
        assert [row.id for row in result.rows] == [str(index) for index in range(20)]

    @pytest.mark.asyncio
    @respx.mock
    async def test_row_cap_stops_after_one_page(self, client: BackstopClient) -> None:
        route = respx.post(_URL).mock(
            return_value=_page(_meeting(1), _meeting(2), _meeting(3), total=50)
        )

        result = await fetch_entity_activities(
            client,
            start_date=date(2024, 1, 1),
            end_date=date(2026, 8, 20),
            page_size=3,
            max_rows=2,
        )

        assert route.call_count == 1
        assert [row.id for row in result.rows] == ["1", "2"]
        assert result.truncated_by_row_cap is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_unreadable_row_is_dropped(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(return_value=_page({"title": "no id"}, _meeting(9), total=2))

        result = await fetch_entity_activities(
            client, start_date=date(2024, 1, 1), end_date=date(2026, 8, 20)
        )

        assert [row.id for row in result.rows] == ["9"]
        assert result.rows_dropped == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_later_page_failure_returns_partial(self, client: BackstopClient) -> None:
        route = respx.post(_URL).mock(
            side_effect=[
                _page(_meeting(1), _meeting(2), total=4),
                httpx.Response(500, json={"errors": [{"title": "InternalServerException"}]}),
            ]
        )

        result = await fetch_entity_activities(
            client,
            start_date=date(2024, 1, 1),
            end_date=date(2026, 8, 20),
            page_size=2,
        )

        assert route.call_count == 2
        assert [row.id for row in result.rows] == ["1", "2"]
        assert result.partial_due_to_error is True
        assert result.truncated_by_row_cap is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_max_rows_narrows_page_size_on_the_wire(self, client: BackstopClient) -> None:
        route = respx.post(_URL).mock(return_value=_page(_meeting(1), _meeting(2), total=50))

        result = await fetch_entity_activities(
            client,
            start_date=date(2024, 1, 1),
            end_date=date(2026, 8, 20),
            max_rows=2,
        )

        assert _body_attributes(recorded_json_bodies(route)[0])["pageSize"] == 2
        assert [row.id for row in result.rows] == ["1", "2"]
        assert result.truncated_by_row_cap is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_missing_associated_with_projects_without_raising(
        self, client: BackstopClient
    ) -> None:
        row = _meeting(1)
        del row["associatedWith"]
        respx.post(_URL).mock(return_value=_page(row, total=1))

        result = await fetch_entity_activities(
            client, start_date=date(2024, 1, 1), end_date=date(2026, 8, 20)
        )

        assert result.rows[0].associated_with == ()
        assert result.rows_dropped == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_unreadable_attendees_drop_the_row(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(
            return_value=_page(_meeting(1) | {"attendees": "nope"}, _meeting(2), total=2)
        )

        result = await fetch_entity_activities(
            client, start_date=date(2024, 1, 1), end_date=date(2026, 8, 20)
        )

        assert [row.id for row in result.rows] == ["2"]
        assert result.rows_dropped == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_first_page_error_propagates(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(
            return_value=httpx.Response(404, json={"errors": [{"title": "Not Found"}]})
        )

        with pytest.raises(BackstopApiError) as raised:
            await fetch_entity_activities(
                client, start_date=date(2024, 1, 1), end_date=date(2026, 8, 20)
            )

        assert raised.value.status_code == 404
