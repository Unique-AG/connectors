import logging
from datetime import date
from typing import cast

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.activity_history import (
    EntityActivityType,
    SearchActivitiesQuery,
)
from backstop_mcp.features.entity_types import SearchType
from tests.features.activity_history.conftest import make_search_activities_query
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
        "activityTags": [{"id": 9001, "name": "XY: Alpha"}],
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


def _request_body(
    *,
    page_num: int,
    page_size: int,
    start_date: date,
    end_date: date,
    types: tuple[EntityActivityType, ...] = (),
    party_id: str | None = None,
    resource_type: SearchType | None = None,
    activity_tags: tuple[str, ...] = (),
    authors: tuple[str, ...] = (),
    include_description: bool = False,
) -> dict[str, object]:
    query = SearchActivitiesQuery(client=cast(BackstopClient, object()))
    return query._request_body(  # pyright: ignore[reportPrivateUsage]
        page_num=page_num,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
        types=types,
        party_id=party_id,
        resource_type=resource_type,
        activity_tags=activity_tags,
        authors=authors,
        include_description=include_description,
    )


class TestEntityActivitiesRequestBody:
    def test_pins_the_measured_search_envelope(self) -> None:
        body = _request_body(
            page_num=1,
            page_size=500,
            start_date=date(2025, 8, 20),
            end_date=date(2026, 8, 20),
            types=("meeting_call", "email"),
            party_id="354566359",
            resource_type="organizations",
            activity_tags=("9001", "9002"),
            authors=("cara@contoso.example",),
            include_description=False,
        )

        attributes = _body_attributes(body)
        assert object_dict(body["data"])["type"] == "entity-activities"
        assert attributes["pageNum"] == 1
        assert attributes["pageSize"] == 500
        assert "shouldIncludeDescription" not in attributes
        assert attributes["includeFields"] == [
            "associatedWith",
            "inheritedFrom",
            "primaryEntity",
        ]
        assert attributes["sorts"] == [{"columnName": "effectiveDate", "ascending": False}]
        assert attributes["entityId"] == 354566359
        assert attributes["resourceType"] == "organizations"
        assert "filters" not in attributes
        new_filters = object_dict(attributes["newFilters"])
        assert new_filters["effectiveDate"] == {
            "startTimestamp": "2025-08-20T00:00:00",
            "endTimestamp": "2026-08-20T23:59:59",
        }
        assert new_filters["types"] == [{"searchValues": [{"value": "call"}, {"value": "email"}]}]
        assert new_filters["activityTags"] == [
            {"searchValues": [{"value": "9001"}, {"value": "9002"}]}
        ]
        assert new_filters["authors"] == [
            {"searchValues": [{"value": "cara@contoso.example", "isEmail": True}]}
        ]

    def test_description_flag_is_opt_in(self) -> None:
        attributes = _body_attributes(
            _request_body(
                page_num=1,
                page_size=50,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
                types=(),
                party_id=None,
                activity_tags=("9001",),
                authors=(),
                include_description=True,
            )
        )

        assert attributes["shouldIncludeDescription"] is True
        assert attributes["includeFields"] == [
            "associatedWith",
            "inheritedFrom",
            "primaryEntity",
            "description",
        ]


class TestFetchEntityActivities:
    @pytest.mark.asyncio
    @respx.mock
    async def test_one_page_projects_us_dates_and_pins_the_body(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(_URL).mock(return_value=_page(_meeting(76715331), total=1))

        result = await make_search_activities_query(client).run(
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
        assert row.tags[0].id == "9001"
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

        result = await make_search_activities_query(client).run(
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

        result = await make_search_activities_query(client).run(
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

        result = await make_search_activities_query(client).run(
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

        result = await make_search_activities_query(client).run(
            start_date=date(2024, 1, 1),
            end_date=date(2026, 8, 20),
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

        result = await make_search_activities_query(client).run(
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

        result = await make_search_activities_query(client).run(
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

        result = await make_search_activities_query(client).run(
            start_date=date(2024, 1, 1),
            end_date=date(2026, 8, 20),
        )

        assert result.rows[0].associated_with == ()
        assert result.rows_dropped == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_unreadable_attendees_drop_the_row(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(
            return_value=_page(_meeting(1) | {"attendees": "nope"}, _meeting(2), total=2)
        )

        result = await make_search_activities_query(client).run(
            start_date=date(2024, 1, 1),
            end_date=date(2026, 8, 20),
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
            await make_search_activities_query(client).run(
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 20),
            )

        assert raised.value.status_code == 404


def _party_row(
    row_id: int,
    *,
    effective_date: str,
    party_id: str | None,
    activity_type: str = "Meeting",
    attendees: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "id": row_id,
        "type": activity_type,
        "effectiveDate": effective_date,
        "attendees": attendees or [],
    }
    if party_id is not None:
        row["associatedWith"] = [{"resourceType": "organizations", "resourceId": party_id}]
        row["primaryEntity"] = {"resourceType": "organizations", "resourceId": party_id}
    else:
        row["associatedWith"] = [{"resourceType": "people", "resourceId": "357918383"}]
        row["inheritedFrom"] = [{"name": "Ada North"}]
    return row


class TestIgnoredEntityActivityFilters:
    @pytest.mark.asyncio
    @respx.mock
    async def test_out_of_window_rows_are_dropped_and_flagged(
        self,
        client: BackstopClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        respx.post(_URL).mock(
            return_value=_page(
                _party_row(1, effective_date="10/2/2026", party_id=None),
                _party_row(2, effective_date="9/22/2026", party_id=None),
                total=2,
            )
        )

        with caplog.at_level(logging.WARNING):
            result = await make_search_activities_query(client).run(
                start_date=date(2026, 6, 1),
                end_date=date(2026, 9, 30),
            )

        assert [row.id for row in result.rows] == ["2"]
        assert result.server_filter_ignored == ("effective_date",)
        ignored_logs = [
            record
            for record in caplog.records
            if record.message == "activity_history.entity_activities.filter_ignored"
        ]
        assert len(ignored_logs) == 1
        assert ignored_logs[0].__dict__["filter"] == "effective_date"
        assert ignored_logs[0].__dict__["endpoint"] == "entity-activities"

    @pytest.mark.asyncio
    @respx.mock
    async def test_party_page_with_a_partial_miss_does_not_fire(
        self, client: BackstopClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One row names the party and one does not.

        Trimmed from an entity-activities page on a client-obtained tenant.
        """
        route = respx.post(_URL).mock(
            return_value=_page(
                _party_row(
                    1,
                    effective_date="9/22/2026",
                    party_id="341764767",
                    attendees=[{"name": "Jane Doe"}, {"name": "Sam Roe"}],
                ),
                _party_row(
                    2, effective_date="8/24/2026", party_id=None, activity_type="Email Blast"
                ),
                total=21,
            )
        )

        with caplog.at_level(logging.WARNING):
            result = await make_search_activities_query(client).run(
                start_date=date(2026, 6, 1),
                end_date=date(2026, 9, 30),
                party_id="341764767",
                resource_type="organizations",
            )

        body = _body_attributes(recorded_json_bodies(route)[0])
        assert body["entityId"] == 341764767
        assert body["resourceType"] == "organizations"
        assert "filters" not in body
        assert [row.id for row in result.rows] == ["1", "2"]
        assert result.rows[0].attendees == ("Jane Doe", "Sam Roe")
        assert result.server_filter_ignored == ()
        assert not any(
            record.message == "activity_history.entity_activities.filter_ignored"
            for record in caplog.records
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_person_only_rows_on_an_org_search_are_kept(self, client: BackstopClient) -> None:
        """Inherited activity and email blasts often name only a person, not the organization."""
        respx.post(_URL).mock(
            return_value=_page(
                _party_row(1, effective_date="9/22/2026", party_id=None),
                _party_row(2, effective_date="9/21/2026", party_id=None),
                total=2,
            )
        )

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 30),
            party_id="341764767",
            resource_type="organizations",
        )

        assert [row.id for row in result.rows] == ["1", "2"]
        assert result.server_filter_ignored == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_row_that_names_the_org_only_on_primary_entity_is_kept(
        self, client: BackstopClient
    ) -> None:
        row = _party_row(1, effective_date="9/22/2026", party_id=None)
        row["primaryEntity"] = {"resourceType": "organizations", "resourceId": "341764767"}
        respx.post(_URL).mock(return_value=_page(row, total=1))

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 30),
            party_id="341764767",
            resource_type="organizations",
        )

        assert [kept.id for kept in result.rows] == ["1"]
        assert result.server_filter_ignored == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_primary_entity_for_another_organization_drops_the_page(
        self, client: BackstopClient
    ) -> None:
        row = _party_row(1, effective_date="9/22/2026", party_id=None)
        row["primaryEntity"] = {"resourceType": "organizations", "resourceId": "1"}
        respx.post(_URL).mock(return_value=_page(row, total=1))

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 30),
            party_id="341764767",
            resource_type="organizations",
        )

        assert result.rows == ()
        assert result.server_filter_ignored == ("party",)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_page_naming_another_organization_is_dropped_and_flagged(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(_URL).mock(
            return_value=_page(
                _party_row(1, effective_date="9/22/2026", party_id="1"),
                _party_row(2, effective_date="9/21/2026", party_id="1"),
                total=900,
            )
        )

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 30),
            party_id="341764767",
            resource_type="organizations",
        )

        assert result.rows == ()
        assert result.server_filter_ignored == ("party",)
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_row_of_an_unrequested_type_is_dropped_and_flagged(
        self, client: BackstopClient
    ) -> None:
        respx.post(_URL).mock(
            return_value=_page(
                _party_row(1, effective_date="9/22/2026", party_id=None, activity_type="Note"),
                _party_row(2, effective_date="9/22/2026", party_id=None, activity_type="Meeting"),
                total=2,
            )
        )

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 30),
            types=("note",),
        )

        assert [row.id for row in result.rows] == ["1"]
        assert result.server_filter_ignored == ("types",)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_row_without_a_requested_tag_is_dropped_and_flagged(
        self, client: BackstopClient
    ) -> None:
        tagged = _meeting(1)
        untagged: dict[str, object] = {**_meeting(2), "activityTags": []}
        respx.post(_URL).mock(return_value=_page(tagged, untagged, total=2))

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 30),
            activity_tags=("9001",),
        )

        assert [row.id for row in result.rows] == ["1"]
        assert result.server_filter_ignored == ("activity_tags",)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_scoped_search_saturating_the_total_is_flagged(
        self, client: BackstopClient
    ) -> None:
        respx.post(_URL).mock(return_value=_page(_meeting(1), total=10_000))

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 30),
            activity_tags=("9001",),
        )

        assert [row.id for row in result.rows] == ["1"]
        assert result.server_filter_ignored == ("total_count",)

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_party_search_on_the_ceiling_is_not_an_ignored_filter(
        self, client: BackstopClient
    ) -> None:
        respx.post(_URL).mock(
            return_value=_page(
                _party_row(1, effective_date="9/22/2026", party_id="341764767"),
                total=10_000,
            )
        )

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 30),
            party_id="341764767",
            resource_type="organizations",
        )

        assert [row.id for row in result.rows] == ["1"]
        assert result.server_filter_ignored == ()
