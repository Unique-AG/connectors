from collections.abc import Mapping, Sequence
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import Tool
from fastmcp.tools.base import ToolResult
from mcp.shared.exceptions import MCPError
from mcp.types import (
    METHOD_NOT_FOUND,
    CallToolRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphNotFound, GraphUnavailable
from office_365_mcp.shared.calendar import SERIES_MASTER_FIELD, confirmation_id_for
from office_365_mcp.shared.handles import EventHandle, event_handle
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    GraphAdviceMiddleware,
    ToolAdvice,
)
from office_365_mcp.tools import outlook_delete_event as deleter
from office_365_mcp.tools.outlook_delete_event import DeletedEvent, a_person_agrees, delete_event

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0001="
_EVENT_ID = "AAMkAGI2SYNTHETIC-event-0001="

_EVENT_PATH = f"/me/calendars/{quote(_CALENDAR_ID, safe='')}/events/{quote(_EVENT_ID, safe='')}"
_PERMANENT_DELETE_PATH = f"{_EVENT_PATH}/permanentDelete"

_URI = EventHandle(_CALENDAR_ID, _EVENT_ID).uri

_STATE = confirmation_id_for(_URI, "outlook_delete_event")

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"

_NO_RESTORE = "Microsoft does not document whether a deleted event can be restored."
_EVERY_OCCURRENCE = "The delete applies to every occurrence of the series."
_ONE_DATE = (
    "The delete applies only to this one date. The other occurrences of the series stay as they "
    + "are."
)
_SAME_FAILURE = (
    "If you call this tool again with the same arguments, the call will fail the same way."
)


def _attendee(address: str, *, kind: str = "required") -> dict[str, object]:
    return {
        "type": kind,
        "status": {"response": "none", "time": "0001-01-01T00:00:00Z"},
        "emailAddress": {"name": None, "address": address},
    }


def _event(
    *,
    subject: str | None = "Pricing review",
    kind: str = "singleInstance",
    attendees: Sequence[Mapping[str, object]] = (),
    is_organizer: bool | None = True,
) -> dict[str, object]:
    return {
        "id": _EVENT_ID,
        "subject": subject,
        "bodyPreview": "",
        "start": {"dateTime": "2026-03-02T14:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-03-02T15:00:00.0000000", "timeZone": "UTC"},
        "isAllDay": False,
        "isCancelled": False,
        "type": kind,
        "seriesMasterId": None,
        "sensitivity": "normal",
        "showAs": "busy",
        "location": None,
        "isOnlineMeeting": False,
        "onlineMeeting": None,
        "organizer": {"emailAddress": {"name": "Ada Lovelace", "address": _ADA}},
        "isOrganizer": is_organizer,
        "responseStatus": {"response": "organizer", "time": "0001-01-01T00:00:00Z"},
        "attendees": [dict(one) for one in attendees],
        "webLink": "https://outlook.office365.invalid/calendar/item/synthetic-event",
    }


def _reads(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    return graph.get(_EVENT_PATH).mock(
        return_value=httpx.Response(200, json=payload if payload is not None else _event())
    )


def _deletes(graph: respx.MockRouter, *, status: int = 204) -> respx.Route:
    return graph.delete(_EVENT_PATH).mock(return_value=httpx.Response(status))


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "The event was not deleted."


async def _delete(
    client: GraphServiceClient, *, uri: str = _URI, confirm: Confirm = _agrees
) -> DeletedEvent:
    answer = await delete_event(client, uri=uri, confirm=confirm)
    assert isinstance(answer, DeletedEvent), "this call was answered with a question, not a delete"
    return answer


async def _asked(
    client: GraphServiceClient, graph: respx.MockRouter, payload: dict[str, object]
) -> str:
    _ = _reads(graph, payload)
    _ = _deletes(graph)
    asked: list[str] = []

    async def capturing(question: str, about: str) -> str | None:
        assert about
        asked.append(question)
        return None

    _ = await _delete(client, confirm=capturing)
    assert len(asked) == 1, "the person was not asked exactly once"
    return asked[0]


def _made(router: respx.MockRouter) -> Sequence[Call]:
    return cast("Sequence[Call]", router.calls)


async def _advice(client: GraphServiceClient) -> str:
    advice = GraphAdviceMiddleware(
        {
            deleter.TOOL_NAME: ToolAdvice(
                permissions=deleter.GRAPH_PERMISSIONS, not_found=deleter.GRAPH_NOT_FOUND
            )
        }
    )

    async def the_tool(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        _ = context
        _ = await _delete(client)
        raise AssertionError("Graph refused nothing, so there is no advice to read")

    with pytest.raises(ToolError) as raised:
        _ = await advice.on_call_tool(
            MiddlewareContext(message=CallToolRequestParams(name=deleter.TOOL_NAME)), the_tool
        )
    return str(raised.value)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    deleter.register(mcp, transport)
    tool = await mcp.get_tool(deleter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_reads_the_event_then_deletes_it_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        delete_route = _deletes(graph)

        _ = await _delete(client)

        assert [call.request.method for call in _made(graph)] == ["GET", "DELETE"]
        assert read.call_count == 1
        assert delete_route.call_count == 1

    async def test_the_delete_carries_no_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)

        _ = await _delete(client)

        assert delete_route.calls.last.request.content == b""

    async def test_no_request_reaches_the_permanent_delete_route(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(kind="seriesMaster", attendees=[_attendee(_ADA)]))
        _ = _deletes(graph)
        purge = graph.post(_PERMANENT_DELETE_PATH).mock(return_value=httpx.Response(204))

        _ = await _delete(client)

        assert purge.call_count == 0
        assert not [call for call in _made(graph) if "permanentDelete" in call.request.url.path]


class TestThePersonBetweenTheRequestAndTheDelete:
    async def test_an_event_with_nobody_on_it_is_still_put_to_a_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        question = await _asked(client, graph, _event(attendees=[]))

        assert question

    async def test_a_refusal_deletes_nothing_after_the_read_that_precedes_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        delete_route = _deletes(graph)

        with pytest.raises(ToolError, match="The event was not deleted"):
            _ = await _delete(client, confirm=_refuses)

        assert read.call_count == 1
        assert delete_route.call_count == 0

    async def test_the_question_without_attendees_names_the_subject_the_start_and_no_restore(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        question = await _asked(client, graph, _event(subject="Focus time", attendees=[]))

        assert "'Focus time'" in question
        assert "2026-03-02T14:00:00+00:00" in question
        assert _NO_RESTORE in question
        assert "cancellation" not in question
        assert _EVERY_OCCURRENCE not in question

    async def test_the_question_with_attendees_names_each_one_and_the_cancellation(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        question = await _asked(
            client, graph, _event(attendees=[_attendee(_ADA), _attendee(_GRACE)])
        )

        assert f"Microsoft mails a cancellation to {_ADA}, {_GRACE}" in question
        assert "this connector cannot recall it" in question
        assert _NO_RESTORE in question

    async def test_the_question_for_a_series_master_says_every_occurrence_can_go(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        question = await _asked(
            client, graph, _event(kind="seriesMaster", attendees=[_attendee(_ADA)])
        )

        assert _EVERY_OCCURRENCE in question
        assert _ONE_DATE not in question
        assert _ADA in question

    @pytest.mark.parametrize("kind", ["occurrence", "exception"])
    async def test_the_question_for_one_date_of_a_series_says_only_that_date_goes(
        self, client: GraphServiceClient, graph: respx.MockRouter, kind: str
    ) -> None:
        question = await _asked(client, graph, _event(kind=kind, attendees=[_attendee(_ADA)]))

        assert _ONE_DATE in question
        assert _EVERY_OCCURRENCE not in question
        assert _ADA in question

    async def test_the_question_for_a_single_event_names_no_series(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        question = await _asked(client, graph, _event(kind="singleInstance"))

        assert "series" not in question

    async def test_the_question_names_an_event_with_no_subject(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        question = await _asked(client, graph, _event(subject=None))

        assert question.startswith("Delete the event with no subject that starts")

    async def test_the_answer_is_bound_to_this_tool_and_this_event(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _deletes(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert question
            bound.append(about)
            return None

        _ = await _delete(client, confirm=capturing)

        assert bound == [_STATE]


class TestWhatItRefuses:
    async def test_a_handle_that_is_not_an_event_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not one"):
            _ = await _delete(client, uri="outlook:///calendars/x")

        assert len(graph.calls) == 0

    async def test_the_refusal_of_a_bad_handle_ends_with_the_canonical_retry_sentence(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as raised:
            _ = await _delete(client, uri="outlook:///calendars/x")

        assert str(raised.value).endswith(_SAME_FAILURE)

    @pytest.mark.parametrize("is_organizer", [False, None], ids=["attendee", "unknown"])
    async def test_an_event_the_signed_in_user_does_not_organize_is_never_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter, is_organizer: bool | None
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)], is_organizer=is_organizer))
        delete_route = _deletes(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="not report the signed-in user as the organizer"):
            _ = await _delete(client, confirm=counting)

        assert asked == [], "a refused delete interrupted the user first"
        assert delete_route.call_count == 0

    async def test_the_refusal_points_at_declining_the_invitation(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(is_organizer=False))

        with pytest.raises(ToolError) as raised:
            _ = await _delete(client)

        message = str(raised.value)
        assert "outlook_respond_to_invite can decline the invitation" in message
        assert "The event was not deleted." in message
        assert message.endswith(_SAME_FAILURE)


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_delete_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        delete_route = _deletes(graph, status=503)

        with pytest.raises(GraphUnavailable):
            _ = await _delete(client)

        assert delete_route.call_count == 1


class TestGraphErrors:
    async def test_a_404_on_the_read_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_EVENT_PATH).mock(return_value=httpx.Response(404))
        delete_route = _deletes(graph)

        with pytest.raises(GraphNotFound):
            _ = await _delete(client)

        assert delete_route.call_count == 0

    async def test_a_404_on_the_delete_after_the_read_found_the_event_says_nothing_was_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _event(subject="Weekly sync", attendees=[_attendee(_ADA)]))
        delete_route = _deletes(graph, status=404)

        message = await _advice(client)

        assert read.call_count == 1
        assert delete_route.call_count == 1
        assert message.startswith(deleter.GRAPH_NOT_FOUND)
        assert "this call deleted nothing" in message
        assert "The event is probably already gone." in message


class TestWhatItAnswers:
    async def test_the_answer_is_built_from_the_read_before_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(subject="Weekly sync", attendees=[_attendee(_ADA)]))
        _ = _deletes(graph)

        answer = await _delete(client)

        assert answer.uri == _URI
        assert answer.subject == "Weekly sync"
        assert answer.start is not None
        assert answer.start.iso == "2026-03-02T14:00:00+00:00"
        assert [one.address for one in answer.attendees] == [_ADA]
        assert answer.series_master is False

    async def test_a_series_master_is_reported_as_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(kind="seriesMaster"))
        _ = _deletes(graph)

        answer = await _delete(client)

        assert answer.series_master is True
        assert answer.attendees == []


def _context(answer: object) -> Context:
    class _Client:
        request_context: object = None

        async def elicit(self, message: str, response_type: object = None) -> object:
            assert message
            assert response_type is not None, "the caller must say what it expects back"
            if isinstance(answer, Exception):
                raise answer
            return answer

    return cast("Context", cast("object", _Client()))


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
                f"a connection with no back-channel was asked {message!r} over it, "
                + f"expecting {response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


class TestTheEraWithABackChannel:
    async def test_agreeing_deletes_the_event_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        delete_route = _deletes(graph)

        answer = await delete_event(
            client, uri=_URI, confirm=a_person_agrees(_context(AcceptedElicitation(data="delete")))
        )

        assert isinstance(answer, DeletedEvent)
        assert delete_route.call_count == 1

    @pytest.mark.parametrize(
        "answer",
        [DeclinedElicitation(), CancelledElicitation(), AcceptedElicitation(data="keep the event")],
        ids=["declined", "cancelled", "another-answer"],
    )
    async def test_any_other_answer_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: object
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        delete_route = _deletes(graph)

        with pytest.raises(ToolError) as raised:
            _ = await delete_event(client, uri=_URI, confirm=a_person_agrees(_context(answer)))

        assert str(raised.value).startswith("The event was not deleted.")
        assert delete_route.call_count == 0

    async def test_a_client_that_cannot_ask_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)
        confirm = a_person_agrees(_context(MCPError(METHOD_NOT_FOUND, "Method not found")))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await delete_event(client, uri=_URI, confirm=confirm)

        assert delete_route.call_count == 0


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(subject="Weekly sync", attendees=[_attendee(_ADA)]))
        delete_route = _deletes(graph)

        answer = await delete_event(client, uri=_URI, confirm=a_person_agrees(_modern_context()))

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == _STATE
        requests = answer.input_requests or {}
        request = requests[next(iter(requests))]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        assert "Weekly sync" in params.message
        assert _ADA in params.message
        assert delete_route.call_count == 0

    async def test_the_second_round_deletes_under_the_id_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _event(attendees=[_attendee(_ADA)]))
        delete_route = _deletes(graph)
        key = await self._the_key(client)

        answer = await delete_event(
            client,
            uri=_URI,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "delete"})},
                    state=_STATE,
                )
            ),
        )

        assert isinstance(answer, DeletedEvent)
        assert delete_route.call_count == 1

    async def test_an_answer_bound_to_another_request_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)
        key = await self._the_key(client)

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await delete_event(
                client,
                uri=_URI,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "delete"})},
                        state="synthetic-other-state",
                    )
                ),
            )

        assert delete_route.call_count == 0

    async def test_a_declined_second_round_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)
        key = await self._the_key(client)

        with pytest.raises(ToolError, match="The event was not deleted"):
            _ = await delete_event(
                client,
                uri=_URI,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=_STATE)
                ),
            )

        assert delete_route.call_count == 0

    @staticmethod
    async def _the_key(client: GraphServiceClient) -> str:
        first = await delete_event(client, uri=_URI, confirm=a_person_agrees(_modern_context()))
        assert isinstance(first, InputRequiredResult)
        return next(iter(first.input_requests or {}))


class TestHowItDeclaresItself:
    def test_the_permission_is_calendars_readwrite(self) -> None:
        assert deleter.GRAPH_PERMISSIONS == ("Calendars.ReadWrite",)

    def test_the_call_example_is_an_event_handle_and_nothing_else(self) -> None:
        assert set(deleter.GRAPH_CALL_EXAMPLE) == {"uri"}
        assert event_handle(cast("str", deleter.GRAPH_CALL_EXAMPLE["uri"])) is not None

    async def test_it_takes_one_argument_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"uri"}

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_a_destructive_write_that_a_repeat_cannot_double(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"]

    async def test_the_description_says_what_happens_to_attendees_and_names_the_siblings(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "Microsoft sends each attendee a cancellation" in description
        assert "always asks the user to agree" in description
        assert "does not document whether a deleted event can be restored" in description
        assert "outlook_cancel_event" in description
        assert "Deleted Items" in description
        assert "outlook_respond_to_invite declines" in description
        assert "\n\nNotes:\n" in description

    async def test_the_description_says_what_the_uri_of_a_series_master_and_of_one_date_deletes(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "The `uri` of a series master deletes every occurrence of the series." in description
        assert "The `uri` of one occurrence deletes only that date." in description
        assert "`series_master` true when the delete reached the whole series" in description

    async def test_the_description_says_a_repeat_after_a_timeout_finds_no_event(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        note = (
            "This call is safe to repeat after a timeout. A second call finds no event and "
            + "reports that."
        )
        assert note in (tool.description or "")

    def test_not_found_advice_points_at_the_lister(self) -> None:
        assert "outlook_list_events" in deleter.GRAPH_NOT_FOUND

    def test_the_series_master_field_has_the_one_description_of_the_series_fact(self) -> None:
        assert DeletedEvent.model_fields["series_master"].description == SERIES_MASTER_FIELD

    def test_the_not_found_advice_ends_with_the_canonical_retry_sentence(self) -> None:
        assert deleter.GRAPH_NOT_FOUND.endswith(_SAME_FAILURE)
