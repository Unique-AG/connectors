from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
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
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE, Confirm, Confirmed
from office_365_mcp.tools import teams_delete_meeting as deleter
from office_365_mcp.tools.teams_delete_meeting import (
    DeletedMeeting,
    a_person_agrees,
    delete_meeting,
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

_NOTHING_DELETED = "No meeting was deleted."


def _stored(
    *, subject: str | None = "Pricing review", organizer: str | None = SIGNED_IN_USER_ID
) -> dict[str, object]:
    return {
        **meeting_payload(subject=subject),
        "participants": {
            "organizer": {"identity": {"user": {"id": organizer}}, "role": "presenter"},
            "attendees": [{"identity": {"user": {"id": OTHER_USER_ID}}, "role": "attendee"}],
        },
    }


def _resolves(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.get(_MEETINGS).mock(
        return_value=httpx.Response(
            200, json={"value": [dict(payload) if payload is not None else _stored()]}
        )
    )


def _me(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me").mock(return_value=httpx.Response(200, json=ME))


def _deletes(graph: respx.MockRouter) -> respx.Route:
    return graph.delete(_MEETING).mock(return_value=httpx.Response(204))


def _ready(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    _ = _resolves(graph, payload)
    _ = _me(graph)
    return _deletes(graph)


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_DELETED


async def _delete(
    client: GraphServiceClient, *, meeting_uri: str = _URI, confirm: Confirm = _agrees
) -> DeletedMeeting | InputRequiredResult:
    return await delete_meeting(client, meeting_uri=meeting_uri, confirm=confirm)


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
    deleter.register(mcp, transport)
    tool = await mcp.get_tool(deleter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


class TestWhatItSendsToGraph:
    async def test_it_resolves_the_meeting_reads_the_user_and_deletes_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        resolve = _resolves(graph)
        me = _me(graph)
        delete = _deletes(graph)

        _ = await _delete(client)

        assert (resolve.call_count, me.call_count, delete.call_count) == (1, 1, 1)
        assert len(graph.calls) == 3
        assert not delete.calls.last.request.content, "a delete carries no body"


class TestTheOrganizerRule:
    async def test_a_meeting_the_user_does_not_organize_is_refused_with_no_question_or_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolves(graph, _stored(organizer=OTHER_USER_ID))
        _ = _me(graph)
        delete = _deletes(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> Confirmed:
            assert about
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="not name the signed-in user as the organizer") as no:
            _ = await _delete(client, confirm=counting)

        assert _NOTHING_DELETED in str(no.value)
        assert asked == [], "a person was asked about a meeting this tool must refuse"
        assert delete.call_count == 0

    async def test_a_meeting_that_names_no_organizer_is_refused_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolves(graph, _stored(organizer=None))
        _ = _me(graph)
        delete = _deletes(graph)

        with pytest.raises(ToolError, match="organizer"):
            _ = await _delete(client)

        assert delete.call_count == 0


class TestThePersonBeforeTheDelete:
    async def test_the_question_comes_after_the_reads_and_before_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await _delete(client, confirm=watching)

        assert calls_when_asked == [2], "the question did not sit between the reads and the write"
        assert delete.call_count == 1

    async def test_a_refusal_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph)

        with pytest.raises(ToolError, match=_NOTHING_DELETED):
            _ = await _delete(client, confirm=_refuses)

        assert delete.call_count == 0

    async def test_a_decline_over_the_back_channel_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph)
        session = _Session(modern=False, elicited=DeclinedElicitation())

        with pytest.raises(ToolError, match=_NOTHING_DELETED):
            _ = await _delete(client, confirm=a_person_agrees(session.context))

        assert len(session.asked) == 1
        assert delete.call_count == 0

    async def test_agreeing_over_the_back_channel_deletes_the_meeting(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph)
        session = _Session(modern=False, elicited=AcceptedElicitation(data="delete"))

        _ = await _delete(client, confirm=a_person_agrees(session.context))

        assert delete.call_count == 1

    async def test_the_question_names_the_meeting_and_when_it_starts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _stored(subject="Weekly sync"))
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _delete(client, confirm=capturing)

        assert len(asked) == 1
        assert asked[0].startswith("Delete the Teams meeting 'Weekly sync'")
        assert "2026-02-10T14:00:00" in asked[0]
        assert "Nothing here can restore the meeting." in asked[0]

    async def test_a_meeting_with_no_subject_is_still_named_in_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _stored(subject=None))
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _delete(client, confirm=capturing)

        assert asked[0].startswith("Delete the Teams meeting that has no subject")


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_deletes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph)

        answer = await _delete(client, confirm=a_person_agrees(_Session().context))

        _key, _state, agrees_with, question = _the_question(answer)
        assert agrees_with == "delete"
        assert "Pricing review" in question
        assert delete.call_count == 0, "an unanswered question deleted the meeting anyway"

    async def test_the_second_round_deletes_the_meeting_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph)
        key, state, agrees_with, _question = _the_question(
            await _delete(client, confirm=a_person_agrees(_Session().context))
        )

        answer = await _delete(
            client,
            confirm=a_person_agrees(
                _Session(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                ).context
            ),
        )

        assert delete.call_count == 1, "the agreed delete did not happen exactly once"
        assert isinstance(answer, DeletedMeeting)

    async def test_an_answer_bound_to_another_meeting_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph)
        key, state, agrees_with, _question = _the_question(
            await _delete(client, confirm=a_person_agrees(_Session().context))
        )
        other = meeting_uri_for(f"{JOIN_WEB_URL}&other=1") or ""

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _delete(
                client,
                meeting_uri=other,
                confirm=a_person_agrees(
                    _Session(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    ).context
                ),
            )

        assert delete.call_count == 0, "a meeting was deleted under an answer nobody gave for it"


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
            _ = await _delete(client, meeting_uri=meeting_uri)

        assert "teams:///meetings/{join_web_url}" in str(refused.value)
        assert _NOTHING_DELETED in str(refused.value)
        assert len(graph.calls) == 0

    async def test_a_handle_that_matches_no_meeting_is_refused_with_no_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        resolve = graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))
        me = _me(graph)
        delete = _deletes(graph)

        with pytest.raises(ToolError, match="has no meeting with this handle") as refused:
            _ = await _delete(client)

        assert _NOTHING_DELETED in str(refused.value)
        assert (resolve.call_count, me.call_count, delete.call_count) == (1, 0, 0)

    async def test_the_registered_tool_hands_the_handle_to_the_question(
        self, transport: httpx.AsyncClient, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph)
        tool = await _registered(transport)
        assert isinstance(tool, FunctionTool)

        answer = cast(
            "object", await tool.fn(meeting_uri=_URI, ctx=_Session().context, client=client)
        )

        _key, _state, agrees_with, question = _the_question(answer)
        assert agrees_with == "delete"
        assert "Pricing review" in question
        assert delete.call_count == 0


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_delete_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolves(graph)
        _ = _me(graph)
        delete = graph.delete(_MEETING).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _delete(client)

        assert delete.call_count == 1


class TestTheFailuresItPassesOn:
    async def test_a_meeting_that_is_gone_by_the_delete_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolves(graph)
        _ = _me(graph)
        _ = graph.delete(_MEETING).mock(return_value=httpx.Response(404))

        with pytest.raises(GraphNotFound):
            _ = await _delete(client)


class TestWhatItAnswers:
    async def test_the_answer_is_read_from_the_meeting_before_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _stored(subject="Weekly sync"))

        answer = await _delete(client)

        assert answer == DeletedMeeting.model_validate(
            {"meeting_uri": _URI, "subject": "Weekly sync", "start": "2026-02-10T14:00:00Z"}
        )


class TestHowItDeclaresItself:
    def test_it_writes_under_the_meeting_write_permission_and_reads_the_user(self) -> None:
        assert deleter.GRAPH_PERMISSIONS == ("OnlineMeetings.ReadWrite", "User.Read")

    def test_its_write_step_is_delete_meeting(self) -> None:
        assert deleter.STEP_DELETE == "delete_meeting"

    def test_teams_read_meeting_shows_the_change(self) -> None:
        assert deleter.CHANGE_SHOWN_BY == ("teams_read_meeting",)

    def test_its_example_call_is_a_meeting_handle(self) -> None:
        example = cast("Mapping[str, str]", deleter.GRAPH_CALL_EXAMPLE)

        assert meeting_handle(example["meeting_uri"]) is not None

    async def test_it_announces_itself_as_a_destructive_write_that_a_repeat_can_do_twice(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE["idempotentHint"]
        assert annotations.open_world_hint is WRITE_DESTRUCTIVE["openWorldHint"]

    async def test_the_description_says_it_asks_every_time_touches_no_calendar_and_how_to_retry(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert (
            "This tool asks the user to agree before it deletes anything, every time. This tool "
            + "deletes nothing unless the user agrees."
        ) in description
        assert (
            "This tool sends its change to the Teams online meeting only, and never to a calendar "
            + "event. For a meeting on a calendar, use outlook_cancel_event."
        ) in description
        assert (
            "If a call times out, do not call this tool again first. Before you call again, make "
            + "sure that teams_read_meeting does not already show the change."
        ) in description

    async def test_the_description_keeps_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert 45 <= len((tool.description or "").split()) <= 210

    async def test_the_one_argument_is_the_required_meeting_handle(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        assert set(properties) == {"meeting_uri"}
        assert set(cast("Sequence[str]", tool.parameters["required"])) == {"meeting_uri"}
        assert set(deleter.GRAPH_CALL_EXAMPLE) == set(properties)
        assert 15 <= len(str(properties["meeting_uri"]["description"]).split()) <= 60
