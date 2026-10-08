import logging
from datetime import date
from typing import cast, final

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.activity_history import (
    EntityActivitiesFetchDto,
    EntityActivityType,
    SearchActivitiesQuery,
)
from backstop_mcp.features.collection_scan import SearchCursor
from backstop_mcp.features.entity_types import SearchType
from tests.features.activity_history.conftest import (
    make_search_activities_query,
    serve_entity_activities,
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
    attendee_ids: tuple[str, ...] = (),
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
        attendee_ids=attendee_ids,
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
            attendee_ids=("341763143", "341663859"),
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
        assert attributes["sorts"] == [
            {"columnName": "effectiveDate", "ascending": False},
            {"columnName": "id", "ascending": True},
        ]
        assert attributes["entityId"] == 354566359
        assert attributes["resourceType"] == "organizations"
        assert "filters" not in attributes
        new_filters = object_dict(attributes["newFilters"])
        assert new_filters["effectiveDate"] == {
            "startTimestamp": "2025-08-20T00:00:00",
            "endTimestamp": "2026-08-20T23:59:59",
        }
        assert new_filters["types"] == [
            {"searchValues": [{"value": "meeting_call"}, {"value": "email"}]}
        ]
        assert new_filters["activityTags"] == [
            {"searchValues": [{"value": "9001"}, {"value": "9002"}]}
        ]
        assert new_filters["authors"] == [
            {"searchValues": [{"value": "cara@contoso.example", "isEmail": True}]}
        ]
        assert new_filters["attendees"] == [
            {
                "type": 0,
                "searchValues": [
                    {"value": "PartyBean_341763143"},
                    {"value": "PartyBean_341663859"},
                ],
            }
        ]

    def test_attendees_are_omitted_when_none_are_asked_for(self) -> None:
        attributes = _body_attributes(
            _request_body(
                page_num=1, page_size=50, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
            )
        )

        assert "attendees" not in object_dict(attributes["newFilters"])

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


def _on(row_id: int, day: str) -> dict[str, object]:
    return _meeting(row_id) | {"effectiveDate": day}


def _page_nums(route: respx.Route) -> list[object]:
    return [_body_attributes(body)["pageNum"] for body in recorded_json_bodies(route)]


_FINGERPRINT = "test-search"


def _cursor(offset: int) -> str:
    return SearchCursor(offsets=(offset,), fingerprint=_FINGERPRINT).encode()


def _resume_offset(result: EntityActivitiesFetchDto) -> int | None:
    """The offset the result's continuation resumes from."""
    if result.continuation is None:
        return None
    return SearchCursor.decode(
        result.continuation.cursor, fingerprint=_FINGERPRINT, collections=1
    ).offsets[0]


async def _read_every_page(
    client: BackstopClient, *, min_result_size: int, page_size: int
) -> list[EntityActivitiesFetchDto]:
    pages: list[EntityActivitiesFetchDto] = []
    cursor: str | None = None
    while True:
        page = await make_search_activities_query(client).run(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 20),
            cursor=cursor,
            fingerprint=_FINGERPRINT,
            min_result_size=min_result_size,
            page_size=page_size,
        )
        pages.append(page)
        if page.continuation is None:
            return pages
        cursor = page.continuation.cursor


_DAYS = ("8/5/2026", "8/4/2026", "8/3/2026", "8/2/2026", "8/1/2026", "7/31/2026")
# 3 rows on the first day, 2 on each later one: 13 rows.
_SET = tuple(
    _on(row_id, day)
    for row_id, day in enumerate(
        (day for index, day in enumerate(_DAYS) for _ in range(3 if index == 0 else 2)), start=1
    )
)


class TestResultPages:
    """Rows mode returns whole pages until `min_result_size`; the cursor is the next offset."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_whole_pages_and_points_past_the_last_one(
        self, client: BackstopClient
    ) -> None:
        respx.post(_URL).mock(side_effect=serve_entity_activities(_SET))

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 20),
            min_result_size=2,
            fingerprint=_FINGERPRINT,
            page_size=4,
        )

        assert [row.id for row in result.rows] == ["1", "2", "3", "4"]
        assert _resume_offset(result) == 4
        assert result.rows_received == 4

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_mid_page_offset_rereads_the_page_and_skips_what_came_before(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(_URL).mock(side_effect=serve_entity_activities(_SET))

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 20),
            cursor=_cursor(3),
            min_result_size=2,
            fingerprint=_FINGERPRINT,
            page_size=2,
        )

        assert _page_nums(route) == [2, 3]
        assert [row.id for row in result.rows] == ["4", "5", "6"]
        assert _resume_offset(result) == 6

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize(("min_result_size", "page_size"), [(1, 1), (2, 2), (2, 3), (5, 2)])
    async def test_reading_every_page_returns_each_row_once(
        self, client: BackstopClient, min_result_size: int, page_size: int
    ) -> None:
        respx.post(_URL).mock(side_effect=serve_entity_activities(_SET))

        pages = await _read_every_page(client, min_result_size=min_result_size, page_size=page_size)

        assert [row.id for page in pages for row in page.rows] == [str(row["id"]) for row in _SET]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_page_short_by_a_hidden_record_is_not_the_end(
        self, client: BackstopClient
    ) -> None:
        """Probed: page 1 of 100 held 99 rows and page 2 began at position 100."""
        rows = tuple(
            _on(row_id, "8/3/2026") | ({"_hidden": True} if row_id == 2 else {})
            for row_id in range(1, 8)
        )
        route = respx.post(_URL).mock(side_effect=serve_entity_activities(rows))

        pages = await _read_every_page(client, min_result_size=3, page_size=3)

        assert [row.id for page in pages for row in page.rows] == ["1", "3", "4", "5", "6", "7"]
        assert _resume_offset(pages[0]) == 6
        assert _page_nums(route) == [1, 2, 3]

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_unreadable_row_still_advances_the_offset(
        self, client: BackstopClient
    ) -> None:
        respx.post(_URL).mock(
            side_effect=serve_entity_activities(
                (
                    _on(1, "8/3/2026"),
                    _on(9, "8/2/2026") | {"attendees": "nope"},
                    _on(2, "8/2/2026"),
                )
            )
        )

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 20),
            min_result_size=1,
            fingerprint=_FINGERPRINT,
            page_size=2,
        )

        assert [row.id for row in result.rows] == ["1"]
        assert result.rows_dropped == 1
        assert _resume_offset(result) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_the_wall_ends_the_walk_without_a_resume_point(
        self, client: BackstopClient
    ) -> None:
        route = respx.post(_URL).mock(side_effect=serve_entity_activities(_SET, wall=4))

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 20),
            min_result_size=5,
            fingerprint=_FINGERPRINT,
            page_size=2,
            max_retrievable=4,
        )

        assert _page_nums(route) == [1, 2]
        assert [row.id for row in result.rows] == ["1", "2", "3", "4"]
        assert result.continuation is None
        assert result.ceiling_clamped is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_filling_on_the_last_servable_record_ends_at_the_wall(
        self, client: BackstopClient
    ) -> None:
        respx.post(_URL).mock(side_effect=serve_entity_activities(_SET, wall=4))

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 20),
            cursor=_cursor(2),
            min_result_size=2,
            fingerprint=_FINGERPRINT,
            page_size=2,
            max_retrievable=4,
        )

        assert [row.id for row in result.rows] == ["3", "4"]
        assert result.continuation is None
        assert result.ceiling_clamped is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_filling_on_the_last_record_ends_without_a_resume_point(
        self, client: BackstopClient
    ) -> None:
        respx.post(_URL).mock(return_value=_page(_on(1, "8/3/2026"), _on(2, "8/2/2026")))

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 20),
            min_result_size=2,
            fingerprint=_FINGERPRINT,
            page_size=5,
        )

        assert [row.id for row in result.rows] == ["1", "2"]
        assert result.continuation is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_ignored_filter_ends_the_page_without_a_resume_point(
        self, client: BackstopClient
    ) -> None:
        respx.post(_URL).mock(
            return_value=_page(_on(1, "8/3/2026"), _on(2, "8/2/2026"), _on(3, "1/1/2020"), total=50)
        )

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 8, 20),
            min_result_size=1,
            fingerprint=_FINGERPRINT,
            page_size=3,
        )

        assert [row.id for row in result.rows] == ["1", "2"]
        assert result.server_filter_ignored == ("effective_date",)
        assert result.continuation is None


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
        respx.post(_URL).mock(side_effect=[_page(_meeting(1), total=10_000), _page(total=10_000)])

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
            side_effect=[
                _page(
                    _party_row(1, effective_date="9/22/2026", party_id="341764767"),
                    total=10_000,
                ),
                _page(total=10_000),
            ]
        )

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 30),
            party_id="341764767",
            resource_type="organizations",
        )

        assert [row.id for row in result.rows] == ["1"]
        assert result.server_filter_ignored == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_opportunity_ref_on_an_org_search_does_not_drop_the_page(
        self, client: BackstopClient
    ) -> None:
        """Only party refs contradict. A row tied to a deal names the opportunity, not a rival."""
        row = _party_row(1, effective_date="9/22/2026", party_id=None)
        row["associatedWith"] = [{"resourceType": "opportunities", "resourceId": "55"}]
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
    @pytest.mark.parametrize("resource_type", ["people", "contacts", "employees"])
    async def test_an_organization_ref_on_a_person_search_is_neutral(
        self, client: BackstopClient, resource_type: SearchType
    ) -> None:
        row = _party_row(1, effective_date="9/22/2026", party_id="1")
        respx.post(_URL).mock(return_value=_page(row, total=1))

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 30),
            party_id="357918383",
            resource_type=resource_type,
        )

        assert [kept.id for kept in result.rows] == ["1"]
        assert result.server_filter_ignored == ()

    @pytest.mark.asyncio
    @respx.mock
    @pytest.mark.parametrize("ref_kind", ["people", "contacts", "employees"])
    async def test_another_person_on_a_contacts_search_drops_the_page(
        self, client: BackstopClient, ref_kind: str
    ) -> None:
        """people / contacts / employees are one person under three names, so any rivals."""
        row = _party_row(1, effective_date="9/22/2026", party_id=None)
        row["associatedWith"] = [{"resourceType": ref_kind, "resourceId": "2"}]
        respx.post(_URL).mock(return_value=_page(row, total=1))

        result = await make_search_activities_query(client).run(
            start_date=date(2026, 6, 1),
            end_date=date(2026, 9, 30),
            party_id="357918383",
            resource_type="contacts",
        )

        assert result.rows == ()
        assert result.server_filter_ignored == ("party",)


@final
class _StubCounter:
    """Stands in for `BACKSTOP_FILTER_IGNORED`, recording each increment's attributes."""

    def __init__(self) -> None:
        self.recorded: list[dict[str, object]] = []

    def add(self, _amount: int, attributes: dict[str, object] | None = None) -> None:
        self.recorded.append(dict(attributes or {}))


class TestFilterIgnoredMetric:
    """`backstop_filter_ignored_total` pages on any increase, so only real ignored filters count."""

    @staticmethod
    def _counter(monkeypatch: pytest.MonkeyPatch) -> _StubCounter:
        counter = _StubCounter()
        # Patched where it is bound at import, not on `metrics`.
        monkeypatch.setattr(
            "backstop_mcp.features.activity_history.queries.search_activities_query"
            + ".BACKSTOP_FILTER_IGNORED",
            counter,
        )
        return counter

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_saturated_total_is_a_hint_logged_at_info_and_not_counted(
        self,
        client: BackstopClient,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        counter = self._counter(monkeypatch)
        respx.post(_URL).mock(side_effect=[_page(_meeting(1), total=10_000), _page(total=10_000)])

        with caplog.at_level(logging.INFO):
            result = await make_search_activities_query(client).run(
                start_date=date(2026, 6, 1),
                end_date=date(2026, 9, 30),
                activity_tags=("9001",),
            )

        assert result.server_filter_ignored == ("total_count",)
        assert counter.recorded == []
        ignored_logs = [
            record
            for record in caplog.records
            if record.message == "activity_history.entity_activities.filter_ignored"
        ]
        assert [record.levelno for record in ignored_logs] == [logging.INFO]

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_ignored_filter_is_counted_once_and_warned(
        self,
        client: BackstopClient,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        counter = self._counter(monkeypatch)
        untagged: dict[str, object] = {**_meeting(2), "activityTags": []}
        respx.post(_URL).mock(return_value=_page(_meeting(1), untagged, total=10_000))

        with caplog.at_level(logging.INFO):
            result = await make_search_activities_query(client).run(
                start_date=date(2026, 6, 1),
                end_date=date(2026, 9, 30),
                activity_tags=("9001",),
            )

        assert result.server_filter_ignored == ("activity_tags", "total_count")
        assert counter.recorded == [{"endpoint": "entity-activities", "filter": "activity_tags"}]
        levels = {
            record.__dict__["filter"]: record.levelno
            for record in caplog.records
            if record.message == "activity_history.entity_activities.filter_ignored"
        }
        assert levels == {"activity_tags": logging.WARNING, "total_count": logging.INFO}
