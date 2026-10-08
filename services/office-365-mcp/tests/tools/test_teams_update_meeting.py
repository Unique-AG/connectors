import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.tools import FunctionTool, Tool
from mcp.types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import meeting_handle, meeting_uri_for
from office_365_mcp.shared.identity import Person
from office_365_mcp.shared.meetings import not_a_meeting_handle
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm, Confirmed
from office_365_mcp.tools import teams_update_meeting as updater
from office_365_mcp.tools.teams_update_meeting import (
    UpdatedMeeting,
    a_person_agrees,
    update_meeting,
)

from .conftest import (
    JOIN_WEB_URL,
    ME,
    MEETING_ID,
    OTHER_USER_ID,
    SIGNED_IN_USER_ID,
    meeting_payload,
)

_MEETINGS = "/me/onlineMeetings"
_MEETING = f"/me/onlineMeetings/{MEETING_ID}"

_URI = meeting_uri_for(JOIN_WEB_URL) or ""

_GRACE_ID = "00000000-0000-4000-8000-000000000003"
_DAVE_ID = "00000000-0000-4000-8000-000000000004"
_GRACE = Person(user_id=_GRACE_ID, name="Grace Hopper")
_BOB = Person(user_id=OTHER_USER_ID, name="Bob Kelso")

_NOTHING_CHANGED = "No meeting was changed."
_FAILS_THE_SAME_WAY = (
    "If you call this tool again with the same arguments, the call will fail the same way."
)


def _shown(user_id: str, name: str) -> str:
    return (
        f"the person with the Microsoft Entra object id '{user_id}' "
        + f"(the name '{name}' is only a label from the request)"
    )


def _invitee(
    user_id: str | None, *, name: str | None = None, upn: str | None = None
) -> dict[str, object]:
    return {
        "upn": upn,
        "role": "attendee",
        "identity": {"user": {"id": user_id, "displayName": name}},
    }


_BOB_INVITEE = _invitee(OTHER_USER_ID, name="Bob Kelso", upn="bob@contoso.invalid")
_CAROL_INVITEE = _invitee(None, upn="carol@fabrikam.com")


def _stored(
    *,
    subject: str | None = "Pricing review",
    organizer: str | None = SIGNED_IN_USER_ID,
    attendees: Sequence[Mapping[str, object]] | None = (_BOB_INVITEE,),
) -> dict[str, object]:
    participants: dict[str, object] = {
        "organizer": {"identity": {"user": {"id": organizer}}, "role": "presenter"},
    }
    if attendees is not None:
        participants["attendees"] = [dict(attendee) for attendee in attendees]
    return {**meeting_payload(subject=subject), "participants": participants}


def _resolves(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.get(_MEETINGS).mock(
        return_value=httpx.Response(
            200, json={"value": [dict(payload) if payload is not None else _stored()]}
        )
    )


def _me(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me").mock(return_value=httpx.Response(200, json=ME))


def _patches(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.patch(_MEETING).mock(
        return_value=httpx.Response(200, json=dict(payload) if payload is not None else _stored())
    )


def _ready(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    _ = _resolves(graph, payload)
    _ = _me(graph)
    return _patches(graph)


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_CHANGED


async def _update(
    client: GraphServiceClient,
    *,
    meeting_uri: str = _URI,
    subject: str | None = None,
    starts_at: str | None = None,
    ends_at: str | None = None,
    attendees: Sequence[Person] | None = None,
    confirm: Confirm = _agrees,
) -> UpdatedMeeting | InputRequiredResult:
    return await update_meeting(
        client,
        meeting_uri=meeting_uri,
        subject=subject,
        starts_at=starts_at,
        ends_at=ends_at,
        attendees=attendees,
        confirm=confirm,
    )


async def _bound(
    client: GraphServiceClient,
    *,
    subject: str | None = None,
    starts_at: str | None = None,
    ends_at: str | None = None,
    attendees: Sequence[Person] | None = None,
) -> str:
    bound: list[str] = []

    async def capturing(_question: str, about: str) -> Confirmed:
        bound.append(about)
        return None

    _ = await _update(
        client,
        subject=subject,
        starts_at=starts_at,
        ends_at=ends_at,
        attendees=attendees,
        confirm=capturing,
    )
    return bound[0]


def _sent(route: respx.Route) -> Mapping[str, object]:
    body = cast("Mapping[str, object]", json.loads(route.calls.last.request.content))
    return {key: value for key, value in body.items() if key != "@odata.type"}


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


class _Session:
    def __init__(
        self,
        *,
        modern: bool = True,
        answers: Mapping[str, InputResponse] | None = None,
        state: str | None = None,
        elicited: object = None,
    ) -> None:
        self.request_context: _ModernRequest | None = _ModernRequest() if modern else None
        self.input_responses: Mapping[str, InputResponse] | None = answers
        self.request_state: str | None = state
        self.asked: list[str] = []
        self._elicited: object = elicited

    async def elicit(self, message: str, response_type: object = None) -> object:
        assert response_type is not None
        self.asked.append(message)
        if self._elicited is None:
            raise AssertionError(f"a connection with no back-channel was asked {message!r}")
        return self._elicited

    @property
    def context(self) -> Context:
        return cast("Context", cast("object", self))


def _the_question(answer: object) -> tuple[str, str, str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams)
    schema = cast("Mapping[str, object]", params.requested_schema)
    properties = cast("Mapping[str, object]", schema["properties"])
    choices = cast("Sequence[str]", cast("Mapping[str, object]", properties["value"])["enum"])
    assert answer.request_state
    return key, answer.request_state, choices[0], params.message


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    updater.register(mcp, transport)
    tool = await mcp.get_tool(updater.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


class TestWhatItSendsToGraph:
    async def test_it_resolves_the_meeting_reads_the_user_and_patches_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        resolve = _resolves(graph)
        me = _me(graph)
        patch = _patches(graph)

        _ = await _update(client, subject="Pricing review (moved)")

        assert (resolve.call_count, me.call_count, patch.call_count) == (1, 1, 1)
        assert len(graph.calls) == 3

    async def test_a_new_subject_alone_reaches_graph_alone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(client, subject="Pricing review (moved)")

        assert _sent(patch) == {"subject": "Pricing review (moved)"}

    async def test_both_times_reach_graph_together_in_utc(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(
            client, starts_at="2026-03-02T15:00:00+01:00", ends_at="2026-03-02T16:30:00+01:00"
        )

        assert _sent(patch) == {
            "startDateTime": "2026-03-02T14:00:00+00:00",
            "endDateTime": "2026-03-02T15:30:00+00:00",
        }

    async def test_the_full_attendee_list_reaches_graph_and_no_organizer_does(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(client, attendees=[_GRACE, _BOB])

        assert _sent(patch) == {
            "participants": {
                "attendees": [
                    {"identity": {"user": {"id": OTHER_USER_ID}}},
                    {"identity": {"user": {"id": _GRACE_ID}}},
                ]
            }
        }

    async def test_an_invitee_with_no_entra_id_never_goes_back_to_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _stored(attendees=[_BOB_INVITEE, _CAROL_INVITEE]))

        _ = await _update(client, attendees=[_BOB])

        assert _sent(patch) == {
            "participants": {"attendees": [{"identity": {"user": {"id": OTHER_USER_ID}}}]}
        }

    async def test_an_empty_attendee_list_reaches_graph_as_an_empty_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(client, attendees=[])

        assert _sent(patch) == {"participants": {"attendees": []}}

    async def test_a_repeated_attendee_goes_out_once_in_lowercase(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)
        shouted = "ABCDEF00-0000-4000-8000-000000000004"

        _ = await _update(
            client,
            attendees=[
                Person(user_id=shouted, name="Eve"),
                Person(user_id=shouted.lower(), name="E"),
            ],
        )

        assert _sent(patch) == {
            "participants": {"attendees": [{"identity": {"user": {"id": shouted.lower()}}}]}
        }


class TestTheBothTimesRule:
    @pytest.mark.parametrize(
        ("starts_at", "ends_at"),
        [
            pytest.param("2026-03-02T15:00:00+01:00", None, id="start-only"),
            pytest.param(None, "2026-03-02T16:00:00+01:00", id="end-only"),
        ],
    )
    async def test_one_time_without_the_other_never_reaches_graph(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        starts_at: str | None,
        ends_at: str | None,
    ) -> None:
        with pytest.raises(ToolError, match="without the other") as refused:
            _ = await _update(client, starts_at=starts_at, ends_at=ends_at)

        assert _NOTHING_CHANGED in str(refused.value)
        assert len(graph.calls) == 0

    async def test_an_end_that_is_not_after_the_start_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not after `starts_at`"):
            _ = await _update(
                client, starts_at="2026-03-02T15:00:00Z", ends_at="2026-03-02T15:00:00Z"
            )

        assert len(graph.calls) == 0

    async def test_a_time_with_no_offset_never_reaches_graph_and_names_its_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="`ends_at`. This time has no offset"):
            _ = await _update(
                client, starts_at="2026-03-02T15:00:00Z", ends_at="2026-03-02T16:00:00"
            )

        assert len(graph.calls) == 0

    async def test_a_time_it_cannot_read_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not an ISO-8601"):
            _ = await _update(client, starts_at="next Tuesday", ends_at="2026-03-02T16:00:00Z")

        assert len(graph.calls) == 0

    async def test_no_change_at_all_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="received no change"):
            _ = await _update(client)

        assert len(graph.calls) == 0


class TestTheOrganizerRule:
    async def test_a_meeting_the_user_does_not_organize_is_refused_with_no_question_or_patch(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolves(graph, _stored(organizer=OTHER_USER_ID))
        _ = _me(graph)
        patch = _patches(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="not name the signed-in user as the organizer") as no:
            _ = await _update(client, subject="Mine now", confirm=counting)

        assert _NOTHING_CHANGED in str(no.value)
        assert asked == [], "a person was asked about a meeting this tool must refuse"
        assert patch.call_count == 0

    async def test_a_meeting_that_names_no_organizer_is_refused_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolves(graph, _stored(organizer=None))
        _ = _me(graph)
        patch = _patches(graph)

        with pytest.raises(ToolError, match="organizer"):
            _ = await _update(client, subject="Mine now")

        assert patch.call_count == 0


class TestThePersonBeforeTheChange:
    async def test_the_question_comes_after_the_reads_and_before_the_patch(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await _update(client, subject="Pricing review (moved)", confirm=watching)

        assert calls_when_asked == [2], "the question did not sit between the reads and the write"
        assert patch.call_count == 1

    async def test_a_refusal_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        with pytest.raises(ToolError, match=_NOTHING_CHANGED):
            _ = await _update(client, subject="Pricing review (moved)", confirm=_refuses)

        assert patch.call_count == 0

    async def test_a_decline_over_the_back_channel_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)
        session = _Session(modern=False, elicited=DeclinedElicitation())

        with pytest.raises(ToolError, match=_NOTHING_CHANGED):
            _ = await _update(
                client, subject="Pricing review (moved)", confirm=a_person_agrees(session.context)
            )

        assert len(session.asked) == 1
        assert patch.call_count == 0

    async def test_agreeing_over_the_back_channel_changes_the_meeting(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)
        session = _Session(modern=False, elicited=AcceptedElicitation(data="change"))

        _ = await _update(
            client, subject="Pricing review (moved)", confirm=a_person_agrees(session.context)
        )

        assert patch.call_count == 1

    async def test_the_question_names_the_meeting_and_every_change(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _update(
            client,
            subject="Pricing review (moved)",
            starts_at="2026-03-02T15:00:00+01:00",
            ends_at="2026-03-02T16:00:00+01:00",
            attendees=[_GRACE],
            confirm=capturing,
        )

        assert len(asked) == 1
        question = asked[0]
        assert question.startswith("Change the Teams meeting 'Pricing review':")
        assert "'Pricing review (moved)'" in question
        assert "2026-03-02T15:00:00+01:00 until 2026-03-02T16:00:00+01:00" in question
        assert f"the attendee list to 1 person: {_shown(_GRACE_ID, 'Grace Hopper')}?" in question
        assert question.endswith(" The change removes 'Bob Kelso'.")

    async def test_the_question_says_when_nobody_stays_on_the_attendee_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _update(client, attendees=[], confirm=capturing)

        assert "the attendee list to nobody" in asked[0]
        assert asked[0].endswith(" The change removes 'Bob Kelso'.")

    async def test_the_question_names_who_the_change_removes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _stored(attendees=[_BOB_INVITEE, _CAROL_INVITEE]))
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _update(client, attendees=[_BOB, _GRACE], confirm=capturing)

        assert asked == [
            "Change the Teams meeting 'Pricing review': the attendee list to 2 people: "
            + f"{_shown(OTHER_USER_ID, 'Bob Kelso')}, {_shown(_GRACE_ID, 'Grace Hopper')}? "
            + "The change removes 'carol@fabrikam.com'."
        ]

    async def test_a_name_that_does_not_match_its_id_still_shows_the_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _update(
            client,
            attendees=[Person(user_id=OTHER_USER_ID, name="Grace Hopper")],
            confirm=capturing,
        )

        assert _shown(OTHER_USER_ID, "Grace Hopper") in asked[0]
        assert _GRACE_ID not in asked[0]
        assert _sent(patch) == {
            "participants": {"attendees": [{"identity": {"user": {"id": OTHER_USER_ID}}}]}
        }

    @pytest.mark.parametrize(
        ("invitee", "named"),
        [
            pytest.param(_BOB_INVITEE, "'Bob Kelso'", id="display-name"),
            pytest.param(_CAROL_INVITEE, "'carol@fabrikam.com'", id="upn-only"),
            pytest.param(_invitee(_DAVE_ID), f"'{_DAVE_ID}'", id="id-only"),
            pytest.param({"role": "attendee"}, "an invitee with no name", id="nothing"),
        ],
    )
    async def test_a_removed_invitee_is_named_by_name_then_upn_then_id(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        invitee: Mapping[str, object],
        named: str,
    ) -> None:
        _ = _ready(graph, _stored(attendees=[invitee]))
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _update(client, attendees=[_GRACE], confirm=capturing)

        assert asked[0].endswith(f"? The change removes {named}.")

    @pytest.mark.parametrize(
        "attendees",
        [pytest.param([_BOB], id="same-list"), pytest.param([_BOB, _GRACE], id="one-more")],
    )
    async def test_a_change_that_removes_nobody_says_nothing_about_removal(
        self, client: GraphServiceClient, graph: respx.MockRouter, attendees: list[Person]
    ) -> None:
        _ = _ready(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _update(client, attendees=attendees, confirm=capturing)

        assert asked[0].endswith("?")
        assert "removes" not in asked[0]

    async def test_a_change_that_leaves_the_attendees_alone_says_nothing_about_them(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _stored(attendees=[_CAROL_INVITEE]))
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _update(client, subject="Pricing review (moved)", confirm=capturing)

        assert asked == [
            "Change the Teams meeting 'Pricing review': the subject to 'Pricing review (moved)'?"
        ]

    async def test_the_binding_differs_for_every_change(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        bound = await _bound(client, subject="A")

        assert bound == await _bound(client, subject="A")
        assert bound != await _bound(client, subject="B")
        assert bound != await _bound(client, subject="A", attendees=[])
        assert bound != await _bound(
            client, subject="A", starts_at="2026-03-02T15:00:00Z", ends_at="2026-03-02T16:00:00Z"
        )

    async def test_keeping_the_attendees_and_removing_every_attendee_bind_differently(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        keeps = await _bound(client, subject="A")
        removes = await _bound(client, subject="A", attendees=[])

        assert keeps != removes

    async def test_the_same_ids_under_other_names_bind_the_same_way(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        named = await _bound(client, attendees=[_BOB, _GRACE])
        renamed = await _bound(
            client,
            attendees=[
                Person(user_id=_GRACE_ID.upper(), name="Admiral Hopper"),
                Person(user_id=OTHER_USER_ID, name="bob@contoso.invalid"),
            ],
        )

        assert named == renamed

    async def test_the_same_name_over_another_id_binds_differently(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        shown = await _bound(client, attendees=[_GRACE])
        swapped = await _bound(client, attendees=[Person(user_id=OTHER_USER_ID, name=_GRACE.name)])

        assert shown != swapped


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_patches(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        answer = await _update(
            client, subject="Pricing review (moved)", confirm=a_person_agrees(_Session().context)
        )

        _key, _state, agrees_with, question = _the_question(answer)
        assert agrees_with == "change"
        assert "Pricing review (moved)" in question
        assert patch.call_count == 0, "an unanswered question changed the meeting anyway"

    async def test_the_second_round_patches_the_change_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)
        key, state, agrees_with, _question = _the_question(
            await _update(
                client,
                subject="Pricing review (moved)",
                confirm=a_person_agrees(_Session().context),
            )
        )

        answer = await _update(
            client,
            subject="Pricing review (moved)",
            confirm=a_person_agrees(
                _Session(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                ).context
            ),
        )

        assert patch.call_count == 1, "the agreed change did not happen exactly once"
        assert isinstance(answer, UpdatedMeeting)

    async def test_an_answer_bound_to_another_change_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)
        key, state, agrees_with, _question = _the_question(
            await _update(
                client,
                subject="Pricing review (moved)",
                confirm=a_person_agrees(_Session().context),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _update(
                client,
                subject="Something else",
                confirm=a_person_agrees(
                    _Session(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    ).context
                ),
            )

        assert patch.call_count == 0, "a meeting changed under an answer nobody gave for it"


class TestTheHandle:
    @pytest.mark.parametrize(
        "meeting_uri",
        [
            JOIN_WEB_URL,
            "teams:///transcripts/MSpi/MSMj",
            "teams:///meetings/%20",
            "teams:///chats/19%3Arelease%40thread.v2",
        ],
    )
    async def test_a_value_that_is_not_a_meeting_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, meeting_uri: str
    ) -> None:
        with pytest.raises(ToolError, match="not one") as refused:
            _ = await _update(client, meeting_uri=meeting_uri, subject="Pricing review (moved)")

        assert str(refused.value) == not_a_meeting_handle(
            updater.TOOL_NAME, tail=f"{_NOTHING_CHANGED} {_FAILS_THE_SAME_WAY}"
        )
        assert "teams:///meetings/{join_web_url}" in str(refused.value)
        assert "A `teams:///transcripts/...` handle is not a meeting handle." in str(refused.value)
        assert _NOTHING_CHANGED in str(refused.value)
        assert len(graph.calls) == 0

    async def test_a_handle_that_matches_no_meeting_is_refused_with_no_patch(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        resolve = graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))
        me = _me(graph)
        patch = _patches(graph)

        with pytest.raises(ToolError, match="has no meeting with this handle") as refused:
            _ = await _update(client, subject="Pricing review (moved)")

        assert _NOTHING_CHANGED in str(refused.value)
        assert (resolve.call_count, me.call_count, patch.call_count) == (1, 0, 0)

    async def test_the_registered_tool_hands_every_argument_to_the_question(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)
        tool = await _registered(transport)
        assert isinstance(tool, FunctionTool)

        answer = cast(
            "object",
            await tool.fn(
                meeting_uri=_URI,
                ctx=_Session().context,
                subject="Pricing review (moved)",
                starts_at="2026-03-02T15:00:00+01:00",
                ends_at="2026-03-02T16:00:00+01:00",
                attendees=[_GRACE],
                client=client,
            ),
        )

        _key, _state, _agrees_with, question = _the_question(answer)
        assert "'Pricing review (moved)'" in question
        assert "2026-03-02T15:00:00+01:00 until 2026-03-02T16:00:00+01:00" in question
        assert _shown(_GRACE_ID, "Grace Hopper") in question
        assert patch.call_count == 0


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_patch_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolves(graph)
        _ = _me(graph)
        patch = graph.patch(_MEETING).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _update(client, subject="Pricing review (moved)")

        assert patch.call_count == 1


class TestTheFailuresItPassesOn:
    async def test_a_meeting_that_is_gone_by_the_patch_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolves(graph)
        _ = _me(graph)
        _ = graph.patch(_MEETING).mock(return_value=httpx.Response(404))

        with pytest.raises(GraphNotFound):
            _ = await _update(client, subject="Pricing review (moved)")


class TestWhatItAnswers:
    async def test_the_answer_is_read_from_the_meeting_microsoft_returns(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolves(graph)
        _ = _me(graph)
        _ = _patches(
            graph, _stored(subject="Pricing review (moved)", attendees=[_invitee(_GRACE_ID)])
        )

        answer = await _update(client, subject="Pricing review (moved)")

        assert answer == UpdatedMeeting.model_validate(
            {
                "meeting_uri": _URI,
                "subject": "Pricing review (moved)",
                "start": "2026-02-10T14:00:00Z",
                "end": "2026-02-10T15:00:00Z",
                "attendee_ids": [_GRACE_ID],
            }
        )

    async def test_an_answer_with_no_attendee_list_reports_null_and_not_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolves(graph)
        _ = _me(graph)
        _ = _patches(graph, _stored(attendees=None))

        answer = await _update(client, subject="Pricing review (moved)")

        assert isinstance(answer, UpdatedMeeting)
        assert answer.attendee_ids is None


class TestHowItDeclaresItself:
    def test_it_writes_under_the_meeting_write_permission_and_reads_the_user(self) -> None:
        assert updater.GRAPH_PERMISSIONS == ("OnlineMeetings.ReadWrite", "User.Read")

    def test_its_write_step_is_update_meeting(self) -> None:
        assert updater.STEP_UPDATE == "update_meeting"

    def test_it_declares_no_tool_to_look_for_a_landed_change(self) -> None:
        assert not hasattr(updater, "CHANGE_SHOWN_BY")

    def test_its_example_call_is_a_meeting_handle_and_a_change(self) -> None:
        example = cast("Mapping[str, str]", updater.GRAPH_CALL_EXAMPLE)

        assert meeting_handle(example["meeting_uri"]) is not None
        assert example["subject"]

    async def test_it_announces_itself_as_a_destructive_write_that_a_repeat_does_not_double(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"]
        assert annotations.open_world_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["openWorldHint"]

    async def test_the_description_says_it_asks_every_time_and_touches_no_calendar(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert (
            "This tool asks the user to agree before it changes anything, every time. This tool "
            + "changes nothing unless the user agrees."
        ) in description
        assert (
            "This tool sends its change to the Teams online meeting only, and never to a calendar "
            + "event."
        ) in description
        assert "outlook_update_event" not in description
        assert "This call is safe to repeat after a timeout." in description

    async def test_the_description_says_the_question_shows_the_object_id(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert (
            "The question shows the Microsoft Entra object id of each person in the new list."
        ) in description
        assert (
            "The name is only a label, because Teams identifies each attendee by the object id."
        ) in description

    async def test_the_description_says_the_new_list_replaces_and_who_it_removes(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert (
            "- Before you change `attendees`, read the current list with teams_read_meeting. The "
            + "new list replaces the current list. An invitee without a Microsoft Entra id cannot "
            + "be in the new list, so the change removes that invitee. The question to the user "
            + "names each person that the change removes."
        ) in description

    async def test_the_description_keeps_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert 45 <= len((tool.description or "").split()) <= 210

    async def test_the_arguments_are_the_handle_and_three_changes_and_only_the_handle_is_required(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(properties) == {"meeting_uri", "subject", "starts_at", "ends_at", "attendees"}
        assert set(cast("Sequence[str]", tool.parameters["required"])) == {"meeting_uri"}
        assert set(updater.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_every_argument_is_described_within_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        lengths = {
            name: len(str(schema.get("description", "")).split())
            for name, schema in properties.items()
        }
        assert all(15 <= length <= 60 for length in lengths.values()), lengths

    async def test_the_handle_names_both_tools_that_report_one(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        assert "the `meeting_uri` handle from teams_list_chats or teams_create_meeting:" in str(
            properties["meeting_uri"]["description"]
        )

    async def test_the_attendees_name_every_tool_that_reports_an_id(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        definitions = cast("Mapping[str, Mapping[str, object]]", tool.parameters["$defs"])
        person = cast("Mapping[str, Mapping[str, object]]", definitions["Person"]["properties"])
        assert (
            "Copy it from the `user_id` of get_me, of a teams_list_chat_members row, or of a "
            + "teams_list_chats member. Never build it from a name or an email address."
        ) in str(person["user_id"]["description"])
        assert "as a label only" in str(person["name"]["description"])

    async def test_the_attendees_say_what_an_empty_list_and_an_omitted_list_do(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        description = " ".join(str(properties["attendees"]["description"]).split())
        assert "An empty list removes every attendee." in description
        assert "Omit it to keep the current attendees." in description

    async def test_an_attendee_by_email_address_never_reaches_graph(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        tool = await _registered(transport)

        with pytest.raises(ValidationError, match="match pattern"):
            _ = await tool.run(
                {
                    **updater.GRAPH_CALL_EXAMPLE,
                    "attendees": [{"user_id": "jane@example.invalid", "name": "Jane"}],
                }
            )

        assert len(graph.calls) == 0, "an attendee the schema refuses reached Graph"
