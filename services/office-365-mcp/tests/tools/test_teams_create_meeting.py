import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.tools import Tool
from mcp.types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphUnavailable
from office_365_mcp.shared.handles import meeting_uri_for
from office_365_mcp.shared.identity import Person
from office_365_mcp.shared.seam import WRITE_IDEMPOTENT, Confirm, Confirmed
from office_365_mcp.tools import teams_create_meeting as creator
from office_365_mcp.tools.teams_create_meeting import (
    CreatedMeeting,
    a_person_agrees,
    create_meeting,
)

from .conftest import JOIN_WEB_URL, OTHER_USER_ID, SIGNED_IN_USER_ID, meeting_payload

_CREATE_PATH = "/me/onlineMeetings/createOrGet"

_SUBJECT = "Pricing review"
_STARTS_AT = "2026-03-02T14:00:00+01:00"
_ENDS_AT = "2026-03-02T15:00:00+01:00"
_GRACE_ID = "00000000-0000-4000-8000-000000000003"
_GRACE = Person(user_id=_GRACE_ID, name="Grace Hopper")
_BOB = Person(user_id=OTHER_USER_ID, name="Bob Kelso")

_NOTHING_CREATED = "No meeting was created."


def _shown(user_id: str, name: str) -> str:
    return (
        f"the person with the Microsoft Entra object id '{user_id}' "
        + f"(the name '{name}' is only a label from the request)"
    )


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_CREATED


def _stored(*, attendees: Sequence[str] = (OTHER_USER_ID,)) -> Mapping[str, object]:
    return {
        **meeting_payload(start="2026-03-02T13:00:00Z", end="2026-03-02T14:00:00Z"),
        "externalId": "synthetic-external-id",
        "participants": {
            "organizer": {"identity": {"user": {"id": SIGNED_IN_USER_ID}}, "role": "presenter"},
            "attendees": [{"identity": {"user": {"id": attendee}}} for attendee in attendees],
        },
    }


def _posts(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.post(_CREATE_PATH).mock(
        return_value=httpx.Response(201, json=payload if payload is not None else _stored())
    )


async def _create(
    client: GraphServiceClient,
    *,
    subject: str = _SUBJECT,
    starts_at: str = _STARTS_AT,
    ends_at: str = _ENDS_AT,
    attendees: Sequence[Person] = (_BOB,),
    confirm: Confirm = _agrees,
) -> CreatedMeeting | InputRequiredResult:
    return await create_meeting(
        client,
        subject=subject,
        starts_at=starts_at,
        ends_at=ends_at,
        attendees=attendees,
        confirm=confirm,
    )


def _sent_body(route: respx.Route) -> Mapping[str, object]:
    return cast("Mapping[str, object]", json.loads(route.calls.last.request.content))


async def _external_id_of(
    client: GraphServiceClient,
    graph: respx.MockRouter,
    *,
    subject: str = _SUBJECT,
    starts_at: str = _STARTS_AT,
    ends_at: str = _ENDS_AT,
    attendees: Sequence[Person] = (_BOB,),
) -> object:
    route = _posts(graph)
    _ = await _create(
        client, subject=subject, starts_at=starts_at, ends_at=ends_at, attendees=attendees
    )
    return _sent_body(route)["externalId"]


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _person_schema(parameters: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    definitions = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
    return cast("Mapping[str, Mapping[str, object]]", definitions["Person"]["properties"])


class TestThePersonBeforeTheCreate:
    async def test_a_refusal_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        with pytest.raises(ToolError, match=_NOTHING_CREATED):
            _ = await _create(client, confirm=_refuses)

        assert post.call_count == 0, "a declined meeting still reached Graph"

    @pytest.mark.parametrize(
        ("attendees", "named"),
        [
            ([_GRACE], f"1 person: {_shown(_GRACE_ID, 'Grace Hopper')}"),
            (
                [Person(user_id=_GRACE_ID.upper(), name="Grace Hopper"), _BOB],
                "2 people: "
                + f"{_shown(OTHER_USER_ID, 'Bob Kelso')}, {_shown(_GRACE_ID, 'Grace Hopper')}",
            ),
        ],
        ids=["one", "two"],
    )
    async def test_the_question_names_the_subject_the_times_and_every_attendee(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        attendees: list[Person],
        named: str,
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _create(client, attendees=attendees, confirm=capturing)

        assert asked == [
            f"Create the Teams meeting {_SUBJECT!r} from {_STARTS_AT} to {_ENDS_AT} with "
            + f"{named}? The meeting is on no calendar, and this tool sends no invitation."
        ]

    async def test_the_question_shows_the_object_id_and_the_label_of_every_attendee(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _create(client, attendees=[_BOB, _GRACE], confirm=capturing)

        assert _shown(OTHER_USER_ID, "Bob Kelso") in asked[0]
        assert _shown(_GRACE_ID, "Grace Hopper") in asked[0]

    async def test_a_name_that_does_not_match_its_id_still_shows_the_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _create(
            client,
            attendees=[Person(user_id=OTHER_USER_ID, name="Grace Hopper")],
            confirm=capturing,
        )

        assert _shown(OTHER_USER_ID, "Grace Hopper") in asked[0]
        assert _GRACE_ID not in asked[0]
        assert _sent_body(post)["participants"] == {
            "attendees": [{"identity": {"user": {"id": OTHER_USER_ID}}}]
        }

    async def test_the_question_says_when_the_meeting_has_no_attendee(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _create(client, attendees=[], confirm=capturing)

        assert asked == [
            f"Create the Teams meeting {_SUBJECT!r} from {_STARTS_AT} to {_ENDS_AT} with no "
            + "attendee? The meeting is on no calendar, and this tool sends no invitation."
        ]

    async def test_the_question_is_bound_to_the_external_id_that_graph_receives(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        bound: list[str] = []

        async def capturing(_question: str, about: str) -> Confirmed:
            bound.append(about)
            return None

        _ = await _create(client, confirm=capturing)

        assert bound == [_sent_body(post)["externalId"]]

    async def test_the_question_comes_before_the_post(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await _create(client, confirm=watching)

        assert calls_when_asked == [0], "asked after the meeting already went to Graph"
        assert post.call_count == 1


class TestHowTheQuestionReachesAPerson:
    @staticmethod
    def _context(answer: object) -> Context:
        class _Client:
            request_context: object = None

            async def elicit(self, message: str, response_type: object = None) -> object:
                assert message
                assert response_type is not None
                if isinstance(answer, Exception):
                    raise answer
                return answer

        return cast("Context", cast("object", _Client()))

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(self._context(AcceptedElicitation(data="create")))

        assert await confirm("Create it?", "Create it?") is None

    async def test_declining_refuses_and_says_no_meeting_was_created(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        confirm = a_person_agrees(self._context(DeclinedElicitation()))

        with pytest.raises(ToolError, match=_NOTHING_CREATED):
            _ = await _create(client, confirm=confirm)

        assert post.call_count == 0


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


def _modern_context(
    *, answers: Mapping[str, InputResponse] | None = None, state: str | None = None
) -> Context:

    class _Client:
        request_context: _ModernRequest = _ModernRequest()
        input_responses: Mapping[str, InputResponse] | None = answers
        request_state: str | None = state

        async def elicit(self, message: str, response_type: object = None) -> object:
            raise AssertionError(
                f"a connection with no back-channel was asked {message!r} over it, expecting "
                + f"{response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


def _the_question(answer: object) -> tuple[str, str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams)
    assert params.message
    schema = cast("Mapping[str, object]", params.requested_schema)
    properties = cast("Mapping[str, object]", schema["properties"])
    choices = cast("Sequence[str]", cast("Mapping[str, object]", properties["value"])["enum"])
    assert answer.request_state
    return key, answer.request_state, choices[0]


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_posts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        answer = await _create(client, confirm=a_person_agrees(_modern_context()))

        _key, _state, agrees_with = _the_question(answer)
        assert agrees_with == "create"
        assert post.call_count == 0, "an unanswered question created the meeting anyway"

    async def test_the_second_round_creates_the_meeting_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await _create(client, confirm=a_person_agrees(_modern_context()))
        )

        answer = await _create(
            client,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                )
            ),
        )

        assert post.call_count == 1, "the agreed create did not happen exactly once"
        assert not isinstance(answer, InputRequiredResult)
        assert _sent_body(post)["externalId"] == state

    async def test_an_answer_bound_to_another_meeting_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await _create(client, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _create(
                client,
                attendees=[_BOB, _GRACE],
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    )
                ),
            )

        assert post.call_count == 0, "a meeting went out under an answer nobody gave for it"

    async def test_the_same_ids_under_other_names_still_create_the_meeting_the_user_agreed_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await _create(client, confirm=a_person_agrees(_modern_context()))
        )

        _ = await _create(
            client,
            attendees=[Person(user_id=OTHER_USER_ID, name="Bob")],
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                )
            ),
        )

        assert post.call_count == 1
        assert _sent_body(post)["externalId"] == state


class TestWhatItAsksGraphFor:
    async def test_it_makes_exactly_one_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await _create(client)

        assert post.call_count == 1
        assert len(graph.calls) == 1, "creating one meeting costs one Graph call, and nothing else"

    async def test_the_body_carries_the_subject_the_times_in_utc_and_the_attendees(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await _create(client, attendees=[_GRACE, _BOB])

        body = _sent_body(post)
        assert body["subject"] == _SUBJECT
        assert body["startDateTime"] == "2026-03-02T13:00:00+00:00"
        assert body["endDateTime"] == "2026-03-02T14:00:00+00:00"
        assert body["participants"] == {
            "attendees": [
                {"identity": {"user": {"id": OTHER_USER_ID}}},
                {"identity": {"user": {"id": _GRACE_ID}}},
            ]
        }
        assert "Grace Hopper" not in json.dumps(body)
        assert "Bob Kelso" not in json.dumps(body)

    async def test_the_external_id_is_the_same_for_the_same_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        first = await _external_id_of(client, graph)
        second = await _external_id_of(client, graph)

        assert first == second

    async def test_the_external_id_is_the_same_for_the_same_instants_in_another_offset(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        local = await _external_id_of(client, graph)
        utc = await _external_id_of(
            client, graph, starts_at="2026-03-02T13:00:00Z", ends_at="2026-03-02T14:00:00Z"
        )

        assert local == utc

    async def test_the_external_id_ignores_the_order_and_the_case_of_the_attendees(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        given = await _external_id_of(client, graph, attendees=[_BOB, _GRACE])
        shuffled = await _external_id_of(
            client,
            graph,
            attendees=[
                Person(user_id=_GRACE_ID.upper(), name=_GRACE.name),
                Person(user_id=OTHER_USER_ID.upper(), name=_BOB.name),
            ],
        )

        assert given == shuffled

    async def test_the_external_id_is_the_same_for_the_same_people_under_other_names(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        given = await _external_id_of(client, graph, attendees=[_BOB, _GRACE])
        renamed = await _external_id_of(
            client,
            graph,
            attendees=[
                Person(user_id=OTHER_USER_ID, name="bob@contoso.invalid"),
                Person(user_id=_GRACE_ID, name="Admiral Hopper"),
            ],
        )

        assert given == renamed

    @pytest.mark.parametrize(
        ("subject", "starts_at", "ends_at", "attendees"),
        [
            ("Pricing review, part two", _STARTS_AT, _ENDS_AT, [_BOB]),
            (_SUBJECT, "2026-03-02T14:30:00+01:00", _ENDS_AT, [_BOB]),
            (_SUBJECT, _STARTS_AT, "2026-03-02T15:30:00+01:00", [_BOB]),
            (_SUBJECT, _STARTS_AT, _ENDS_AT, [Person(user_id=_GRACE_ID, name=_BOB.name)]),
            (_SUBJECT, _STARTS_AT, _ENDS_AT, [_BOB, _GRACE]),
            (_SUBJECT, _STARTS_AT, _ENDS_AT, []),
        ],
        ids=["subject", "start", "end", "other-attendee", "more-attendees", "no-attendee"],
    )
    async def test_the_external_id_differs_when_any_field_differs(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        subject: str,
        starts_at: str,
        ends_at: str,
        attendees: list[Person],
    ) -> None:
        original = await _external_id_of(client, graph)
        other = await _external_id_of(
            client,
            graph,
            subject=subject,
            starts_at=starts_at,
            ends_at=ends_at,
            attendees=attendees,
        )

        assert original != other

    async def test_a_repeated_attendee_goes_out_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await _create(
            client, attendees=[_BOB, Person(user_id=OTHER_USER_ID.upper(), name="Bob")]
        )

        participants = cast("Mapping[str, object]", _sent_body(post)["participants"])
        assert participants["attendees"] == [{"identity": {"user": {"id": OTHER_USER_ID}}}]


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "starts_at", ["2026-03-02T14:00:00", "2026-03-02T14:00", "2026-03-02", "2026-03-02T14"]
    )
    async def test_a_start_with_no_offset_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, starts_at: str
    ) -> None:
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="no offset") as refused:
            _ = await _create(client, starts_at=starts_at, confirm=capturing)

        assert "`starts_at`" in str(refused.value)
        assert "`Z`" in str(refused.value)
        assert _NOTHING_CREATED in str(refused.value)
        assert asked == [], "the user was asked about a time that names no instant"
        assert len(graph.calls) == 0

    async def test_an_end_with_no_offset_is_refused_too_and_names_its_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="`ends_at`. This time has no offset"):
            _ = await _create(client, ends_at="2026-03-02T15:00:00")

        assert len(graph.calls) == 0

    @pytest.mark.parametrize("starts_at", ["tomorrow at 2", "1772719200", "02/03/2026 14:00"])
    async def test_a_time_it_cannot_read_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, starts_at: str
    ) -> None:
        with pytest.raises(ToolError, match="is not an ISO-8601 date and time"):
            _ = await _create(client, starts_at=starts_at)

        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        "ends_at", ["2026-03-02T14:00:00+01:00", "2026-03-02T13:59:00+01:00", "2026-03-02T13:00Z"]
    )
    async def test_an_end_that_is_not_after_the_start_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, ends_at: str
    ) -> None:
        with pytest.raises(ToolError, match="not after `starts_at`") as refused:
            _ = await _create(client, ends_at=ends_at)

        assert _NOTHING_CREATED in str(refused.value)
        assert len(graph.calls) == 0


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_post_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = graph.post(_CREATE_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _create(client)

        assert post.call_count == 1


class TestWhatItAnswers:
    async def test_the_answer_reports_the_meeting_microsoft_stored(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph, _stored(attendees=[OTHER_USER_ID, _GRACE_ID]))

        answer = await _create(client)

        assert not isinstance(answer, InputRequiredResult)
        assert answer.meeting_uri == meeting_uri_for(JOIN_WEB_URL)
        assert answer.join_web_url == JOIN_WEB_URL
        assert answer.subject == _SUBJECT
        assert answer.start is not None and answer.start.isoformat() == "2026-03-02T13:00:00+00:00"
        assert answer.end is not None and answer.end.isoformat() == "2026-03-02T14:00:00+00:00"
        assert answer.attendee_ids == [OTHER_USER_ID, _GRACE_ID]

    async def test_the_answer_leaves_the_organizer_out_of_the_attendees(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph, _stored(attendees=[]))

        answer = await _create(client, attendees=[])

        assert not isinstance(answer, InputRequiredResult)
        assert answer.attendee_ids == []

    async def test_an_answer_with_no_attendee_list_reports_an_empty_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        organizer_only = {"organizer": {"identity": {"user": {"id": SIGNED_IN_USER_ID}}}}
        _ = _posts(graph, {**_stored(), "participants": organizer_only})

        answer = await _create(client)

        assert not isinstance(answer, InputRequiredResult)
        assert answer.attendee_ids == []

    async def test_an_existing_meeting_graph_returns_with_200_is_answered_the_same_way(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_CREATE_PATH).mock(return_value=httpx.Response(200, json=_stored()))

        answer = await _create(client)

        assert not isinstance(answer, InputRequiredResult)
        assert answer.meeting_uri == meeting_uri_for(JOIN_WEB_URL)


class TestTheFailuresItPassesOn:
    async def test_a_refused_post_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_CREATE_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _create(client)


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_microsoft_documents_for_create_or_get(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("OnlineMeetings.ReadWrite",)

    def test_its_one_step_is_the_one_call_it_makes(self) -> None:
        assert creator.STEP == "create_meeting"

    def test_it_declares_no_tool_to_look_for_a_second_meeting(self) -> None:
        assert not hasattr(creator, "CHANGE_SHOWN_BY")

    async def test_it_announces_itself_as_a_write_that_a_repeat_does_not_double(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_IDEMPOTENT["idempotentHint"]

    async def test_the_description_says_it_asks_before_it_creates(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert (
            "This tool asks the user to agree before it creates anything, every time. This tool "
            + "creates nothing unless the user agrees."
        ) in " ".join((tool.description or "").split())

    async def test_the_description_says_the_question_shows_the_object_id(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert "The question shows the Microsoft Entra object id of each attendee." in description
        assert (
            "The name is only a label, because Teams identifies each attendee by the object id."
        ) in description

    async def test_the_description_says_the_meeting_is_on_no_calendar_and_invites_nobody(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert "It is on no calendar, and this tool sends no invitation." in description
        assert "To share the meeting, use the `join_web_url` of the answer." in description
        assert (
            "Microsoft documents a calendar event with an online meeting as the way to read the "
            + "transcript of a meeting later."
        ) in description
        assert "teams_send_chat_message" not in description
        assert "outlook_draft_mail" not in description
        assert "outlook_create_event" not in description

    def test_the_answer_says_to_give_the_join_url_to_the_user(self) -> None:
        join_web_url = str(CreatedMeeting.model_fields["join_web_url"].description)

        assert "Give this URL to the user." in join_web_url

    async def test_the_description_says_a_repeat_creates_no_second_meeting(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert "This call is safe to repeat after a timeout." in description
        assert "creates no second meeting" in description

    async def test_the_description_keeps_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert 45 <= len((tool.description or "").split()) <= 210

    async def test_the_arguments_are_subject_times_and_attendees_and_all_are_required(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"subject", "starts_at", "ends_at", "attendees"}
        assert set(cast("Sequence[str]", parameters["required"])) == set(properties)

    async def test_the_attendees_name_every_tool_that_reports_an_id(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        person = _person_schema(parameters)
        assert (
            "Copy it from the `user_id` of get_me, of a teams_list_chat_members row, or of a "
            + "teams_list_chats member. Never build it from a name or an email address."
        ) in str(person["user_id"]["description"])

    async def test_the_name_is_only_for_the_question_and_never_reaches_microsoft(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        name = str(_person_schema(parameters)["name"]["description"])
        assert "as a label only" in name
        assert "Copy the `display_name` from the same result as `user_id`." in name
        assert "never sends it to Microsoft 365" in name

    async def test_an_attendee_by_email_address_never_reaches_graph(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _parameters, tool = await _registered(transport)

        with pytest.raises(ValidationError, match="match pattern"):
            _ = await tool.run(
                {
                    **creator.GRAPH_CALL_EXAMPLE,
                    "attendees": [{"user_id": "jane@example.invalid", "name": "Jane"}],
                }
            )

        assert len(graph.calls) == 0, "an attendee the schema refuses reached Graph"

    async def test_an_attendee_with_no_name_never_reaches_graph(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _parameters, tool = await _registered(transport)

        with pytest.raises(ValidationError, match="at least 1 character"):
            _ = await tool.run(
                {**creator.GRAPH_CALL_EXAMPLE, "attendees": [{"user_id": _GRACE_ID, "name": ""}]}
            )

        assert len(graph.calls) == 0

    async def test_an_empty_subject_never_reaches_graph(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _parameters, tool = await _registered(transport)

        with pytest.raises(ValidationError, match="at least 1 character"):
            _ = await tool.run({**creator.GRAPH_CALL_EXAMPLE, "subject": ""})

        assert len(graph.calls) == 0
