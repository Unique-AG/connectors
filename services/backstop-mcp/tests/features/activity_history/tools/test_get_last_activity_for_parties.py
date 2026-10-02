import json
from collections.abc import Mapping
from datetime import date
from typing import cast

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_history import (
    GetLastActivityForPartiesQuery,
    LastActivityForPartiesResolvedResponse,
    SearchActivitiesUnavailableResponse,
)
from backstop_mcp.features.activity_history.tools.get_last_activity_for_parties import (
    PartyRef,
    get_last_activity_for_parties,
)
from backstop_mcp.server.tools import TOOLS
from tests.features.activity_history.conftest import make_search_activities_query
from tests.helpers import BASE_URL, recorded_json_bodies
from tests.server.tools.helpers import object_dict, object_list, tool_model

_URL = f"{BASE_URL}/entity-activities"
_END = date(2026, 9, 30)
_START = date(2025, 9, 30)


def _page(*rows: dict[str, object], total: int) -> httpx.Response:
    return httpx.Response(
        201,
        json={
            "data": {
                "id": 1,
                "type": "entity-activities",
                "attributes": {"totalCount": total, "results": list(rows)},
            }
        },
    )


def _row(party_id: str, *, row_id: int, effective_date: str) -> dict[str, object]:
    return {
        "id": row_id,
        "type": "Meeting",
        "title": "Quarterly review",
        "effectiveDate": effective_date,
        "associatedWith": [{"resourceType": "organizations", "resourceId": party_id}],
    }


def _by_entity(responses: Mapping[int, httpx.Response]) -> respx.Route:
    def respond(request: httpx.Request) -> httpx.Response:
        body = object_dict(cast("object", json.loads(request.content)))
        entity_id = object_dict(object_dict(body["data"])["attributes"])["entityId"]
        assert isinstance(entity_id, int)
        return responses[entity_id]

    return respx.post(_URL).mock(side_effect=respond)


def _query(client: BackstopClient) -> GetLastActivityForPartiesQuery:
    return GetLastActivityForPartiesQuery(
        search_activities_query=make_search_activities_query(client)
    )


class TestGetLastActivityForParties:
    def test_is_registered_and_says_absence_from_a_sample_is_not_inactivity(self) -> None:
        assert get_last_activity_for_parties in TOOLS
        doc = " ".join((get_last_activity_for_parties.__doc__ or "").split())
        assert "search_opportunities" in doc
        assert "investor.search_type" in doc
        assert "never infer inactivity" in doc
        assert "never as inactive" in doc

    @pytest.mark.asyncio
    @respx.mock
    async def test_reports_found_none_and_unknown_per_party(self, client: BackstopClient) -> None:
        route = _by_entity(
            {
                100: _page(_row("100", row_id=11, effective_date="8/20/2026"), total=7),
                200: _page(total=0),
                300: _page(_row("999", row_id=31, effective_date="9/1/2026"), total=10),
            }
        )

        result = tool_model(
            await get_last_activity_for_parties(
                parties=[
                    PartyRef(party_id="100", search_type="organizations"),
                    PartyRef(party_id="200", search_type="organizations"),
                    PartyRef(party_id="300", search_type="people"),
                ],
                start_date=_START,
                end_date=_END,
                get_last_activity_for_parties_query=_query(client),
            ),
            LastActivityForPartiesResolvedResponse,
        )

        assert route.call_count == 3
        bodies = {
            object_dict(object_dict(body["data"])["attributes"])["entityId"]: object_dict(
                object_dict(body["data"])["attributes"]
            )
            for body in recorded_json_bodies(route)
        }
        assert bodies[100]["pageSize"] == 1
        assert bodies[100]["resourceType"] == "organizations"
        assert bodies[300]["resourceType"] == "people"
        type_filter = object_dict(object_list(object_dict(bodies[100]["newFilters"])["types"])[0])
        sent_types = {
            object_dict(item)["value"] for item in object_list(type_filter["searchValues"])
        }
        assert "email_blast" not in sent_types
        assert {"meeting", "call", "note", "email", "document"} <= sent_types

        found, none, unknown = result.parties
        assert found.party_id == "100"
        assert found.status == "found"
        assert found.last_activity is not None
        assert found.last_activity.id == "11"
        assert found.last_activity.effective_date == date(2026, 8, 20)
        assert found.days_since_last_activity == 41
        assert found.activity_count == 7
        assert none.status == "none_in_window"
        assert none.activity_count == 0
        assert unknown.status == "unknown"
        assert unknown.last_activity is None
        assert unknown.activity_count is None
        assert unknown.reason is not None
        assert "party" in unknown.reason
        assert result.unknown_count == 1
        assert (result.start_date, result.end_date) == (_START, _END)

    @pytest.mark.asyncio
    @respx.mock
    async def test_checks_a_repeated_party_once(self, client: BackstopClient) -> None:
        route = _by_entity({100: _page(total=0)})

        result = tool_model(
            await get_last_activity_for_parties(
                parties=[
                    PartyRef(party_id="100", search_type="organizations"),
                    PartyRef(party_id="100", search_type="organizations"),
                ],
                end_date=_END,
                types=["meeting", "meeting_call"],
                get_last_activity_for_parties_query=_query(client),
            ),
            LastActivityForPartiesResolvedResponse,
        )

        assert route.call_count == 1
        assert len(result.parties) == 1
        assert result.types == ("meeting", "meeting_call")
        assert result.start_date == date(2025, 9, 30)

    @pytest.mark.asyncio
    @respx.mock
    async def test_one_failed_party_is_unknown_not_inactive(self, client: BackstopClient) -> None:
        _by_entity(
            {
                100: _page(_row("100", row_id=11, effective_date="9/29/2026"), total=1),
                200: httpx.Response(404, json={"errors": [{"title": "Not Found"}]}),
            }
        )

        result = tool_model(
            await get_last_activity_for_parties(
                parties=[
                    PartyRef(party_id="100", search_type="organizations"),
                    PartyRef(party_id="200", search_type="organizations"),
                ],
                end_date=_END,
                get_last_activity_for_parties_query=_query(client),
            ),
            LastActivityForPartiesResolvedResponse,
        )

        assert [party.status for party in result.parties] == ["found", "unknown"]
        assert result.parties[0].days_since_last_activity == 1
        assert result.parties[1].reason is not None
        assert result.unknown_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_every_party_failing_names_the_fallback(self, client: BackstopClient) -> None:
        respx.post(_URL).mock(
            return_value=httpx.Response(404, json={"errors": [{"title": "Not Found"}]})
        )

        result = tool_model(
            await get_last_activity_for_parties(
                parties=[PartyRef(party_id="100", search_type="organizations")],
                end_date=_END,
                get_last_activity_for_parties_query=_query(client),
            ),
            SearchActivitiesUnavailableResponse,
        )

        assert result.fallback_tool == "get_activity_history"
        assert "not 'no activity'" in result.message

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_saturated_count_still_reports_the_newest_activity(
        self, client: BackstopClient
    ) -> None:
        _by_entity({100: _page(_row("100", row_id=11, effective_date="8/20/2026"), total=10_000)})

        result = tool_model(
            await get_last_activity_for_parties(
                parties=[PartyRef(party_id="100", search_type="organizations")],
                end_date=_END,
                get_last_activity_for_parties_query=_query(client),
            ),
            LastActivityForPartiesResolvedResponse,
        )

        found = result.parties[0]
        assert found.status == "found"
        assert found.last_activity is not None
        assert found.last_activity.id == "11"
        assert found.activity_count == 10_000
        assert result.unknown_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_an_activity_that_names_only_a_person_is_found(
        self, client: BackstopClient
    ) -> None:
        _by_entity(
            {
                100: _page(
                    {
                        "id": 11,
                        "type": "Email",
                        "title": "Follow-up",
                        "effectiveDate": "8/20/2026",
                        "associatedWith": [{"resourceType": "people", "resourceId": "357918383"}],
                    },
                    total=1,
                )
            }
        )

        result = tool_model(
            await get_last_activity_for_parties(
                parties=[PartyRef(party_id="100", search_type="organizations")],
                end_date=_END,
                get_last_activity_for_parties_query=_query(client),
            ),
            LastActivityForPartiesResolvedResponse,
        )

        found = result.parties[0]
        assert found.status == "found"
        assert found.last_activity is not None
        assert found.last_activity.id == "11"
        assert found.activity_count == 1
        assert result.unknown_count == 0
