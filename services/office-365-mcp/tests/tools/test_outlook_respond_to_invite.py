import json
from collections.abc import Mapping
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient
from pydantic import ValidationError

from office_365_mcp.graph_client import GraphNotFound, GraphThrottled, GraphUnavailable
from office_365_mcp.shared.calendar import SUMMARY_FIELDS
from office_365_mcp.shared.handles import EventHandle
from office_365_mcp.shared.seam import Confirm
from office_365_mcp.tools.outlook_respond_to_invite import (
    InvitationResponse,
    ProposedTime,
    Response,
    respond_to_invite,
)

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0001="
_EVENT_ID = "AAMkAGI2SYNTHETIC-event-0001="

_EVENT_PATH = f"/me/calendars/{quote(_CALENDAR_ID, safe='')}/events/{quote(_EVENT_ID, safe='')}"
_ACCEPT_PATH = f"{_EVENT_PATH}/accept"
_DECLINE_PATH = f"{_EVENT_PATH}/decline"
_TENTATIVE_PATH = f"{_EVENT_PATH}/tentativelyAccept"

_URI = EventHandle(_CALENDAR_ID, _EVENT_ID).uri

_ADA = "ada@example.invalid"

_NEXT_DAY = ProposedTime(
    starts_at="2026-03-03T14:00", ends_at="2026-03-03T15:00", time_zone="W. Europe Standard Time"
)


def _event(
    *,
    subject: str | None = "Pricing review",
    organizer: Mapping[str, object] | None = None,
    allow_new_time_proposals: bool | None = True,
) -> dict[str, object]:
    return {
        "id": _EVENT_ID,
        "subject": subject,
        "bodyPreview": "",
        "start": {"dateTime": "2026-03-02T14:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-03-02T15:00:00.0000000", "timeZone": "UTC"},
        "isAllDay": False,
        "isCancelled": False,
        "type": "singleInstance",
        "seriesMasterId": None,
        "sensitivity": "normal",
        "showAs": "busy",
        "location": None,
        "isOnlineMeeting": False,
        "onlineMeeting": None,
        "organizer": (
            dict(organizer)
            if organizer is not None
            else {"emailAddress": {"name": "Ada Lovelace", "address": _ADA}}
        ),
        "isOrganizer": False,
        "responseStatus": {"response": "notResponded", "time": "0001-01-01T00:00:00Z"},
        "attendees": [],
        "webLink": "https://outlook.office365.invalid/calendar/item/synthetic-event",
        "allowNewTimeProposals": allow_new_time_proposals,
    }


def _reads(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    return graph.get(_EVENT_PATH).mock(
        return_value=httpx.Response(200, json=payload if payload is not None else _event())
    )


def _accepts(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_ACCEPT_PATH).mock(return_value=httpx.Response(202))


def _declines(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_DECLINE_PATH).mock(return_value=httpx.Response(202))


def _tentatively_accepts(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_TENTATIVE_PATH).mock(return_value=httpx.Response(202))


async def _agrees(question: str, about: str) -> str | None:
    assert question
    assert about
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "No response was sent."


async def _respond(
    client: GraphServiceClient,
    *,
    uri: str = _URI,
    response: Response = "accept",
    comment: str | None = None,
    send_response: bool = True,
    proposed_new_time: ProposedTime | None = None,
    confirm: Confirm = _agrees,
) -> InvitationResponse:
    answer = await respond_to_invite(
        client,
        uri=uri,
        response=response,
        comment=comment,
        send_response=send_response,
        proposed_new_time=proposed_new_time,
        confirm=confirm,
    )
    assert isinstance(answer, InvitationResponse), "this call was answered with a question"
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


class TestWhatItSendsToGraph:
    async def test_accept_reaches_the_accept_endpoint_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        accept = _accepts(graph)
        decline = _declines(graph)
        tentative = _tentatively_accepts(graph)

        _ = await _respond(client, response="accept")

        assert read.call_count == 1
        assert accept.call_count == 1
        assert decline.call_count == 0
        assert tentative.call_count == 0

    async def test_decline_reaches_the_decline_endpoint(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        accept = _accepts(graph)
        decline = _declines(graph)

        _ = await _respond(client, response="decline")

        assert decline.call_count == 1
        assert accept.call_count == 0

    async def test_tentative_reaches_the_tentativelyaccept_endpoint(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        tentative = _tentatively_accepts(graph)

        _ = await _respond(client, response="tentative")

        assert tentative.call_count == 1

    async def test_the_comment_and_send_response_reach_graph_verbatim(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        accept = _accepts(graph)

        _ = await _respond(client, response="accept", comment="See you there", send_response=True)

        sent = _sent(accept)
        assert sent["Comment"] == "See you there"
        assert sent["SendResponse"] is True

    async def test_send_response_false_reaches_graph_with_no_elicitation(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        accept = _accepts(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _respond(client, response="accept", send_response=False, confirm=counting)

        assert asked == [], "a response nobody is told about interrupted the user anyway"
        assert _sent(accept)["SendResponse"] is False

    async def test_the_read_selects_whether_the_organizer_allows_a_new_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        _ = _accepts(graph)

        _ = await _respond(client, response="accept")

        selected = read.calls.last.request.url.params["$select"].split(",")
        assert selected == [*SUMMARY_FIELDS, "allowNewTimeProposals"]


class TestTheNewTimeItProposes:
    @pytest.mark.parametrize(
        ("response", "path"), [("decline", _DECLINE_PATH), ("tentative", _TENTATIVE_PATH)]
    )
    async def test_the_proposed_time_reaches_graph_as_one_time_slot(
        self, client: GraphServiceClient, graph: respx.MockRouter, response: Response, path: str
    ) -> None:
        _ = _reads(graph)
        posted = graph.post(path).mock(return_value=httpx.Response(202))

        _ = await _respond(client, response=response, proposed_new_time=_NEXT_DAY)

        assert _sent(posted)["ProposedNewTime"] == {
            "start": {"dateTime": "2026-03-03T14:00", "timeZone": "W. Europe Standard Time"},
            "end": {"dateTime": "2026-03-03T15:00", "timeZone": "W. Europe Standard Time"},
        }
        assert _sent(posted)["SendResponse"] is True

    @pytest.mark.parametrize(
        ("response", "path"),
        [("accept", _ACCEPT_PATH), ("decline", _DECLINE_PATH), ("tentative", _TENTATIVE_PATH)],
    )
    async def test_a_response_with_no_proposed_time_carries_none(
        self, client: GraphServiceClient, graph: respx.MockRouter, response: Response, path: str
    ) -> None:
        _ = _reads(graph)
        posted = graph.post(path).mock(return_value=httpx.Response(202))

        _ = await _respond(client, response=response)

        assert "ProposedNewTime" not in _sent(posted)

    async def test_an_event_graph_said_nothing_about_still_gets_the_proposal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(allow_new_time_proposals=None))
        decline = _declines(graph)

        _ = await _respond(client, response="decline", proposed_new_time=_NEXT_DAY)

        assert "ProposedNewTime" in _sent(decline)

    async def test_the_answer_echoes_the_proposed_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _tentatively_accepts(graph)

        answer = await _respond(client, response="tentative", proposed_new_time=_NEXT_DAY)

        assert answer.proposed_new_time == _NEXT_DAY
        assert answer.response == "tentativelyAccepted"


class TestThePersonBetweenTheRequestAndTheOrganizersInbox:
    async def test_a_refusal_sends_nothing_after_the_read_that_precedes_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        accept = _accepts(graph)

        with pytest.raises(ToolError, match="No response was sent"):
            _ = await _respond(client, response="accept", confirm=_refuses)

        assert read.call_count == 1
        assert accept.call_count == 0

    async def test_send_response_true_is_put_to_a_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(subject="Weekly sync"))
        _ = _accepts(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _respond(client, response="accept", confirm=counting)

        assert len(asked) == 1
        assert "Weekly sync" in asked[0]
        assert "cannot recall" in asked[0]

    async def test_the_question_names_the_organizer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(organizer={"emailAddress": {"name": None, "address": _ADA}}))
        _ = _declines(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _respond(client, response="decline", confirm=capturing)

        assert _ADA in asked[0]

    async def test_the_question_names_the_proposed_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _declines(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _respond(
            client, response="decline", proposed_new_time=_NEXT_DAY, confirm=capturing
        )

        assert (
            "propose the new time from 2026-03-03T14:00 to 2026-03-03T15:00 W. Europe Standard Time"
            in asked[0]
        )

    async def test_the_confirmation_id_changes_with_the_proposed_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _declines(graph)
        abouts: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            abouts.append(about)
            return None

        later = ProposedTime(
            starts_at="2026-03-03T16:00", ends_at="2026-03-03T17:00", time_zone=_NEXT_DAY.time_zone
        )
        for proposal in (None, _NEXT_DAY, later, _NEXT_DAY):
            _ = await _respond(
                client, response="decline", proposed_new_time=proposal, confirm=capturing
            )

        assert len(set(abouts[:3])) == 3, "an agreement to one time answers for another"
        assert abouts[3] == abouts[1], "the same proposal asks under a new id"


class TestWhatItRefuses:
    async def test_a_handle_that_is_not_an_event_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not one"):
            _ = await _respond(client, uri="outlook:///calendars/x")

        assert len(graph.calls) == 0

    async def test_a_proposed_time_on_an_accept_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="only with a decline or a tentative response"):
            _ = await _respond(client, response="accept", proposed_new_time=_NEXT_DAY)

        assert len(graph.calls) == 0

    async def test_a_proposed_time_with_send_response_false_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="a proposal needs `send_response` true"):
            _ = await _respond(
                client, response="decline", send_response=False, proposed_new_time=_NEXT_DAY
            )

        assert len(graph.calls) == 0

    async def test_a_proposed_time_the_organizer_does_not_allow_sends_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _event(allow_new_time_proposals=False))
        decline = _declines(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="does not allow new time proposals") as refused:
            _ = await _respond(
                client, response="decline", proposed_new_time=_NEXT_DAY, confirm=counting
            )

        assert _ADA in str(refused.value)
        assert "NO RESPONSE WAS SENT" in str(refused.value)
        assert read.call_count == 1
        assert decline.call_count == 0
        assert asked == [], "the user was asked about a proposal Microsoft refuses"

    async def test_an_event_that_allows_no_proposal_still_takes_a_plain_decline(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(allow_new_time_proposals=False))
        decline = _declines(graph)

        _ = await _respond(client, response="decline")

        assert decline.call_count == 1

    async def test_a_proposed_time_that_ends_before_it_starts_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        backward = ProposedTime(
            starts_at="2026-03-03T15:00", ends_at="2026-03-03T14:00", time_zone="UTC"
        )

        with pytest.raises(ToolError, match="not after its `starts_at`"):
            _ = await _respond(client, response="decline", proposed_new_time=backward)

        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        "starts_at", ["2026-03-03T14:00Z", "2026-03-03T14:00+01:00", "2026-03-03", "tomorrow"]
    )
    async def test_a_proposed_start_that_is_not_a_wall_clock_time_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, starts_at: str
    ) -> None:
        proposal = ProposedTime(starts_at=starts_at, ends_at="2026-03-03T15:00", time_zone="UTC")

        with pytest.raises(ToolError, match=r"`proposed_new_time\.starts_at`"):
            _ = await _respond(client, response="tentative", proposed_new_time=proposal)

        assert len(graph.calls) == 0

    def test_a_zone_name_with_a_character_no_zone_name_uses_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _ = ProposedTime(
                starts_at="2026-03-03T14:00", ends_at="2026-03-03T15:00", time_zone="UTC;DROP"
            )


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_an_accept_graph_answers_503_is_never_posted_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        accept = graph.post(_ACCEPT_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _respond(client, response="accept")

        assert accept.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_decline_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        decline = graph.post(_DECLINE_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "5"})
        )

        with pytest.raises(GraphThrottled):
            _ = await _respond(client, response="decline")

        assert decline.call_count == 1


class TestGraphErrors:
    async def test_the_event_not_being_found_propagates_as_graph_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_EVENT_PATH).mock(return_value=httpx.Response(404))

        with pytest.raises(GraphNotFound):
            _ = await _respond(client, response="accept")


class TestWhatItAnswers:
    @pytest.mark.parametrize(
        ("response", "recorded_as"),
        [("accept", "accepted"), ("decline", "declined"), ("tentative", "tentativelyAccepted")],
    )
    async def test_the_answer_spells_the_response_in_microsofts_own_vocabulary(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        response: Response,
        recorded_as: str,
    ) -> None:
        _ = _reads(graph, _event(subject="Weekly sync"))
        _ = _accepts(graph)
        _ = _declines(graph)
        _ = _tentatively_accepts(graph)

        answer = await _respond(client, response=response)

        assert answer.response == recorded_as
        assert answer.uri == _URI
        assert answer.subject == "Weekly sync"
        assert answer.sent_response is True
        assert answer.proposed_new_time is None

    async def test_send_response_false_is_echoed_in_the_answer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _accepts(graph)

        answer = await _respond(client, response="accept", send_response=False)

        assert answer.sent_response is False
