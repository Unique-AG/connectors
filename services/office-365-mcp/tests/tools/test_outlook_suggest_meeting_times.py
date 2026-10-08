import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.tools import outlook_suggest_meeting_times as suggester
from office_365_mcp.tools.outlook_suggest_meeting_times import (
    LocationConstraintInput,
    RoomRequest,
    SuggestedMeetingTimes,
    suggest_meeting_times,
)

_FIND_TIMES_PATH = "/me/findMeetingTimes"

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"
_HOOD = "hood@example.invalid"


def _moment(local: str, zone: str = "UTC") -> dict[str, object]:
    return {"dateTime": local, "timeZone": zone}


def _suggestion(
    *,
    confidence: float = 100.0,
    order: int = 1,
    organizer_availability: str = "free",
    start: str = "2026-03-02T16:00:00.0000000",
    end: str = "2026-03-02T17:00:00.0000000",
    attendee_availability: Sequence[Mapping[str, object]] = (),
    locations: Sequence[Mapping[str, object]] = (),
    reason: str | None = None,
) -> dict[str, object]:
    return {
        "confidence": confidence,
        "order": order,
        "organizerAvailability": organizer_availability,
        "suggestionReason": reason,
        "attendeeAvailability": [dict(one) for one in attendee_availability],
        "locations": [dict(one) for one in locations],
        "meetingTimeSlot": {"start": _moment(start), "end": _moment(end)},
    }


def _attendee_availability(address: str, *, availability: str = "free") -> dict[str, object]:
    return {"availability": availability, "attendee": {"emailAddress": {"address": address}}}


def _finds_times(
    graph: respx.MockRouter,
    suggestions: Sequence[Mapping[str, object]],
    *,
    empty_reason: str = "",
) -> respx.Route:
    return graph.post(_FIND_TIMES_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "emptySuggestionsReason": empty_reason,
                "meetingTimeSuggestions": [dict(one) for one in suggestions],
            },
        )
    )


async def _suggest(
    client: GraphServiceClient,
    *,
    attendees: Sequence[str] = (_ADA,),
    optional_attendees: Sequence[str] = (),
    starts_at: str = "2026-03-02T09:00",
    ends_at: str = "2026-03-06T17:00",
    time_zone: str = "UTC",
    duration_minutes: int = 30,
    location_constraint: LocationConstraintInput | None = None,
) -> SuggestedMeetingTimes:
    return await suggest_meeting_times(
        client,
        attendees=attendees,
        optional_attendees=optional_attendees,
        starts_at=starts_at,
        ends_at=ends_at,
        time_zone=time_zone,
        duration_minutes=duration_minutes,
        location_constraint=location_constraint,
    )


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    suggester.register(mcp, transport)
    tool = await mcp.get_tool(suggester.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_calls_findmeetingtimes_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        find = _finds_times(graph, [_suggestion()])

        _ = await _suggest(client)

        assert find.call_count == 1
        assert len(graph.calls) == 1

    async def test_required_and_optional_attendees_reach_graph_with_the_right_type(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        find = _finds_times(graph, [_suggestion()])

        _ = await _suggest(client, attendees=[_ADA], optional_attendees=[_GRACE])

        sent = _sent(find)
        attendees = cast("Sequence[Mapping[str, object]]", sent["attendees"])
        assert [
            (cast("Mapping[str, object]", a["emailAddress"])["address"], a["type"])
            for a in attendees
        ] == [(_ADA, "required"), (_GRACE, "optional")]

    async def test_twenty_one_attendees_reach_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        find = _finds_times(graph, [_suggestion()])
        many = [f"guest{index}@example.invalid" for index in range(21)]

        _ = await _suggest(client, attendees=many)

        assert len(cast("Sequence[object]", _sent(find)["attendees"])) == 21

    async def test_the_window_and_duration_reach_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        find = _finds_times(graph, [_suggestion()])

        _ = await _suggest(
            client,
            starts_at="2026-03-02T09:00",
            ends_at="2026-03-06T17:00",
            time_zone="Europe/Zurich",
            duration_minutes=45,
        )

        sent = _sent(find)
        constraint = cast("Mapping[str, object]", sent["timeConstraint"])
        slots = cast("Sequence[Mapping[str, object]]", constraint["timeSlots"])
        assert slots[0]["start"] == {"dateTime": "2026-03-02T09:00", "timeZone": "Europe/Zurich"}
        assert slots[0]["end"] == {"dateTime": "2026-03-06T17:00", "timeZone": "Europe/Zurich"}
        assert sent["meetingDuration"] == "PT45M"

    async def test_the_default_activity_domain_is_work(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        find = _finds_times(graph, [_suggestion()])

        _ = await _suggest(client)

        constraint = cast("Mapping[str, object]", _sent(find)["timeConstraint"])
        assert constraint["activityDomain"] == "work"

    async def test_an_omitted_location_constraint_sends_none(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        find = _finds_times(graph, [_suggestion()])

        _ = await _suggest(client)

        assert "locationConstraint" not in _sent(find)

    async def test_a_location_constraint_reaches_graph_with_its_rooms(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        find = _finds_times(graph, [_suggestion()])

        _ = await _suggest(
            client,
            location_constraint=LocationConstraintInput(
                is_required=True,
                suggest_location=True,
                locations=[
                    RoomRequest(display_name="Conf room Hood", address=f" {_HOOD} "),
                    RoomRequest(display_name="Conf room Rainier"),
                ],
            ),
        )

        constraint = cast("Mapping[str, object]", _sent(find)["locationConstraint"])
        rooms = cast("Sequence[Mapping[str, object]]", constraint["locations"])
        assert constraint["isRequired"] is True
        assert constraint["suggestLocation"] is True
        assert [(r["displayName"], r.get("locationEmailAddress")) for r in rooms] == [
            ("Conf room Hood", _HOOD),
            ("Conf room Rainier", None),
        ]

    async def test_a_location_constraint_with_no_rooms_sends_no_room_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        find = _finds_times(graph, [_suggestion()])

        _ = await _suggest(
            client, location_constraint=LocationConstraintInput(suggest_location=True)
        )

        constraint = cast("Mapping[str, object]", _sent(find)["locationConstraint"])
        assert constraint["isRequired"] is False
        assert constraint["suggestLocation"] is True
        assert "locations" not in constraint


class TestWhatItRefuses:
    @pytest.mark.parametrize("address", ["Ada Lovelace <ada@example.invalid>", "ada@"])
    async def test_a_malformed_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, address: str
    ) -> None:
        with pytest.raises(ToolError, match="not one"):
            _ = await _suggest(client, attendees=[address])

        assert len(graph.calls) == 0

    async def test_one_person_in_both_lists_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="both"):
            _ = await _suggest(client, attendees=[_ADA], optional_attendees=[_ADA])

        assert len(graph.calls) == 0

    async def test_an_end_that_is_not_after_the_start_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not after"):
            _ = await _suggest(client, starts_at="2026-03-06T17:00", ends_at="2026-03-02T09:00")

        assert len(graph.calls) == 0

    @pytest.mark.parametrize("address", ["Hood <hood@example.invalid>", "hood@"])
    async def test_a_malformed_room_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, address: str
    ) -> None:
        constraint = LocationConstraintInput(
            locations=[RoomRequest(display_name="Conf room Hood", address=address)]
        )

        with pytest.raises(ToolError, match="not one") as raised:
            _ = await _suggest(client, location_constraint=constraint)

        assert "`location_constraint.locations[].address`" in str(raised.value)
        assert len(graph.calls) == 0

    async def test_a_time_it_cannot_read_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="YYYY-MM-DDTHH:MM"):
            _ = await _suggest(client, starts_at="next Tuesday")

        assert len(graph.calls) == 0


class TestGraphErrors:
    async def test_a_forbidden_response_propagates_as_graph_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_FIND_TIMES_PATH).mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await _suggest(client)


class TestWhatItAnswers:
    async def test_it_reports_suggestions_in_graphs_own_order_with_attendee_availability(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _finds_times(
            graph,
            [
                _suggestion(
                    order=1,
                    confidence=100.0,
                    attendee_availability=[_attendee_availability(_ADA, availability="free")],
                ),
                _suggestion(order=2, confidence=50.0),
            ],
        )

        answer = await _suggest(client)

        assert [s.order for s in answer.suggestions] == [1, 2]
        assert answer.suggestions[0].confidence == 100.0
        assert answer.suggestions[0].attendees[0].address == _ADA
        assert answer.suggestions[0].attendees[0].availability == "free"
        assert answer.suggestions[0].start is not None
        assert answer.suggestions[0].start.local == "2026-03-02T16:00:00.0000000"

    async def test_it_reports_the_rooms_of_each_suggestion(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _finds_times(
            graph,
            [
                _suggestion(
                    order=1,
                    locations=[
                        {"displayName": "Conf room Hood", "locationEmailAddress": _HOOD},
                        {"displayName": "Conf room Rainier"},
                    ],
                ),
                _suggestion(order=2),
            ],
        )

        answer = await _suggest(client)

        assert [(r.display_name, r.address) for r in answer.suggestions[0].locations] == [
            ("Conf room Hood", _HOOD),
            ("Conf room Rainier", None),
        ]
        assert answer.suggestions[1].locations == []

    async def test_no_suggestions_reports_the_empty_reason(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _finds_times(graph, [], empty_reason="attendeesUnavailable")

        answer = await _suggest(client)

        assert answer.suggestions == []
        assert answer.empty_reason == "attendeesUnavailable"

    async def test_an_empty_reason_string_is_reported_as_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _finds_times(graph, [_suggestion()], empty_reason="")

        answer = await _suggest(client)

        assert answer.empty_reason is None

    async def test_the_window_and_duration_are_echoed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _finds_times(graph, [_suggestion()])

        answer = await _suggest(
            client,
            starts_at="2026-03-02T09:00",
            ends_at="2026-03-06T17:00",
            time_zone="UTC",
            duration_minutes=45,
        )

        assert answer.window.starts_at == "2026-03-02T09:00"
        assert answer.window.ends_at == "2026-03-06T17:00"
        assert answer.duration_minutes == 45


class TestWhatItPublishes:
    async def test_a_location_constraint_is_optional_and_its_fields_are_not_required(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert "location_constraint" in properties
        assert set(cast("Sequence[str]", parameters["required"])) == {
            "attendees",
            "starts_at",
            "ends_at",
            "time_zone",
        }
        definitions = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
        assert "required" not in definitions["LocationConstraintInput"]
        assert definitions["RoomRequest"]["required"] == ["display_name"]

    async def test_the_description_still_says_nothing_is_booked_and_names_the_constraint(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "nothing here books, invites, or holds a time" in description
        assert "location_constraint" in description
        assert "must come from the user" in description

    async def test_a_suggested_room_name_says_when_it_is_null_in_full_sentences(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        definitions = cast("Mapping[str, Mapping[str, object]]", answer["$defs"])
        rooms = cast(
            "Mapping[str, Mapping[str, object]]", definitions["SuggestedRoom"]["properties"]
        )
        described = cast("str", rooms["display_name"]["description"])
        assert "The value is null when Microsoft gave no name for the room." in described
        assert 15 <= len(described.split()) <= 60

    async def test_the_room_address_says_it_comes_from_the_user_and_books_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        definitions = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
        rooms = cast("Mapping[str, Mapping[str, object]]", definitions["RoomRequest"]["properties"])
        described = cast("str", rooms["address"]["description"])
        assert "must come from the user" in described
        assert "books nothing" in described
