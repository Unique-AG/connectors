"""Every payload in this file is synthetic. No calendar entry in this file came from a real
mailbox. No address in this file resolves to anything real."""

import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.calendar import MAX_ATTENDEES
from office_365_mcp.tools.outlook_suggest_meeting_times import (
    SuggestedMeetingTimes,
    suggest_meeting_times,
)

_FIND_TIMES_PATH = "/me/findMeetingTimes"

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"


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
    reason: str | None = None,
) -> dict[str, object]:
    return {
        "confidence": confidence,
        "order": order,
        "organizerAvailability": organizer_availability,
        "suggestionReason": reason,
        "attendeeAvailability": [dict(one) for one in attendee_availability],
        "locations": [],
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
) -> SuggestedMeetingTimes:
    return await suggest_meeting_times(
        client,
        attendees=attendees,
        optional_attendees=optional_attendees,
        starts_at=starts_at,
        ends_at=ends_at,
        time_zone=time_zone,
        duration_minutes=duration_minutes,
    )


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


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

    async def test_more_addresses_than_the_ceiling_never_reach_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        too_many = [f"guest{index}@example.invalid" for index in range(MAX_ATTENDEES + 1)]

        with pytest.raises(ToolError, match="between them"):
            _ = await _suggest(client, attendees=too_many)

        assert len(graph.calls) == 0

    async def test_an_end_that_is_not_after_the_start_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not after"):
            _ = await _suggest(client, starts_at="2026-03-06T17:00", ends_at="2026-03-02T09:00")

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
