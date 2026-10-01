import pathlib
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
from fastmcp.tools import Tool
from mcp.shared.exceptions import MCPError
from mcp.types import (
    METHOD_NOT_FOUND,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.calendar import confirmation_id_for
from office_365_mcp.shared.handles import CalendarHandle, EventHandle, calendar_handle
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm
from office_365_mcp.tools import outlook_delete_calendar as deleter
from office_365_mcp.tools.outlook_delete_calendar import (
    DeletedCalendar,
    a_person_agrees,
    delete_calendar,
)

from .conftest import ME

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0002="

_URI = CalendarHandle(_CALENDAR_ID).uri

_CALENDAR_PATH = f"/me/calendars/{quote(_CALENDAR_ID, safe='')}"
_EVENTS_PATH = f"{_CALENDAR_PATH}/events"

_STATE = confirmation_id_for(_URI, deleter.TOOL_NAME)

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"

_NOT_FOUND = {"error": {"code": "ErrorItemNotFound", "message": "not found"}}


def _calendar(
    *,
    name: str | None = "Project Apollo",
    owner: str | None = _ADA,
    is_default: bool | None = False,
    is_removable: bool | None = True,
) -> dict[str, object]:
    return {
        "id": _CALENDAR_ID,
        "name": name,
        "owner": None if owner is None else {"name": "Ada Lovelace", "address": owner},
        "isDefaultCalendar": is_default,
        "isRemovable": is_removable,
    }


def _events(*ids: str, next_link: str | None = None) -> dict[str, object]:
    page: dict[str, object] = {"value": [{"id": one} for one in ids]}
    if next_link is not None:
        page["@odata.nextLink"] = next_link
    return page


def _reads(
    graph: respx.MockRouter,
    calendar: Mapping[str, object] | None = None,
    events: Mapping[str, object] | None = None,
) -> tuple[respx.Route, respx.Route, respx.Route]:
    calendar_route = graph.get(_CALENDAR_PATH).mock(
        return_value=httpx.Response(200, json=dict(calendar or _calendar()))
    )
    me_route = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))
    events_route = graph.get(_EVENTS_PATH).mock(
        return_value=httpx.Response(200, json=dict(events or _events()))
    )
    return calendar_route, me_route, events_route


def _deletes(graph: respx.MockRouter, *, status: int = 204) -> respx.Route:
    return graph.delete(_CALENDAR_PATH).mock(return_value=httpx.Response(status))


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return "The calendar was not deleted."


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"a refused calendar was put to a person: {question!r} ({about})")


async def _delete(
    client: GraphServiceClient, *, calendar_ref: str = _URI, confirm: Confirm = _agrees
) -> DeletedCalendar:
    answer = await delete_calendar(client, calendar_ref=calendar_ref, confirm=confirm)
    assert isinstance(answer, DeletedCalendar), "this call was answered with a question"
    return answer


def _made(route: respx.Route) -> Sequence[Call]:
    return cast("Sequence[Call]", route.calls)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    deleter.register(mcp, transport)
    tool = await mcp.get_tool(deleter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_reads_the_calendar_the_user_and_one_event_then_deletes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _deletes(graph)

        _ = await _delete(client)

        made = cast("Sequence[Call]", graph.calls)
        calendar = f"/v1.0/me/calendars/{_CALENDAR_ID}"
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", calendar),
            ("GET", "/v1.0/me"),
            ("GET", f"{calendar}/events"),
            ("DELETE", calendar),
        ]

    async def test_the_calendar_read_asks_for_what_the_refusals_need(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        calendar_route, _, _ = _reads(graph)
        _ = _deletes(graph)

        _ = await _delete(client)

        query = _made(calendar_route)[0].request.url.params
        assert query["$select"] == "id,name,owner,isDefaultCalendar,isRemovable"

    async def test_the_event_read_asks_for_one_id_and_nothing_more(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _, _, events_route = _reads(graph)
        _ = _deletes(graph)

        _ = await _delete(client)

        query = _made(events_route)[0].request.url.params
        assert query["$top"] == "1"
        assert query["$select"] == "id"

    async def test_the_delete_carries_no_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)

        _ = await _delete(client)

        assert delete_route.calls.last.request.content == b""

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_delete_graph_declines_is_retried_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = graph.delete(_CALENDAR_PATH).mock(
            side_effect=[httpx.Response(503), httpx.Response(204)]
        )

        _ = await _delete(client)

        assert delete_route.call_count == 2, "a delete is idempotent, so the SDK's retry runs"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            EventHandle(_CALENDAR_ID, "AAMkSYNTHETIC-event-0001=").uri,
            "outlook:///folders/AQMkADAwSYNTHETIC-folder-0001",
            "Project Apollo",
            _CALENDAR_ID,
            "",
            "outlook:///calendars/",
            "outlook:///calendars/%20",
        ],
    )
    async def test_a_value_that_is_not_a_calendar_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook_list_calendars"):
            _ = await _delete(client, calendar_ref=value, confirm=_never_asked)

        assert len(graph.calls) == 0, "a refused handle deletes nothing"

    async def test_the_default_calendar_is_refused_before_any_event_is_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _, _, events_route = _reads(graph, _calendar(is_default=True))
        delete_route = _deletes(graph)

        with pytest.raises(ToolError, match="default calendar"):
            _ = await _delete(client, confirm=_never_asked)

        assert events_route.call_count == 0
        assert delete_route.call_count == 0

    async def test_a_calendar_microsoft_marks_as_not_removable_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _calendar(is_removable=False))
        delete_route = _deletes(graph)

        with pytest.raises(ToolError, match="not removable"):
            _ = await _delete(client, confirm=_never_asked)

        assert delete_route.call_count == 0

    @pytest.mark.parametrize("owner", [_GRACE, None], ids=["another-person", "no-owner"])
    async def test_a_calendar_the_user_does_not_own_is_refused_before_any_event_is_read(
        self, client: GraphServiceClient, graph: respx.MockRouter, owner: str | None
    ) -> None:
        _, _, events_route = _reads(graph, _calendar(owner=owner))
        delete_route = _deletes(graph)

        with pytest.raises(ToolError, match="deletes only a calendar that the signed-in user owns"):
            _ = await _delete(client, confirm=_never_asked)

        assert events_route.call_count == 0
        assert delete_route.call_count == 0

    async def test_the_owner_is_matched_on_the_user_principal_name_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _calendar(owner="ADA@corp.example.invalid"))
        delete_route = _deletes(graph)

        _ = await _delete(client)

        assert delete_route.call_count == 1

    async def test_a_calendar_that_holds_an_event_is_refused_and_the_user_told_to_move_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, events=_events("AAMkSYNTHETIC-event-0001="))
        delete_route = _deletes(graph)

        with pytest.raises(ToolError) as raised:
            _ = await _delete(client, confirm=_never_asked)

        message = str(raised.value)
        assert "holds at least one event" in message
        assert "move or cancel the events" in message
        assert "Nothing was deleted." in message
        assert delete_route.call_count == 0

    async def test_an_empty_page_that_names_a_next_page_is_refused_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            events=_events(next_link=f"https://graph.microsoft.com/v1.0{_EVENTS_PATH}?$skip=1"),
        )
        delete_route = _deletes(graph)

        with pytest.raises(ToolError, match="holds at least one event"):
            _ = await _delete(client, confirm=_never_asked)

        assert delete_route.call_count == 0


class TestWhatItAnswers:
    async def test_the_answer_echoes_the_handle_and_names_the_calendar_it_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _calendar(name="Project Apollo"))
        _ = _deletes(graph)

        answer = await _delete(client)

        assert answer.uri == _URI
        assert answer.name == "Project Apollo"
        assert answer.deleted is True

    async def test_a_calendar_with_no_name_answers_a_null_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _calendar(name=None))
        _ = _deletes(graph)

        answer = await _delete(client)

        assert answer.name is None


class TestGraphFailures:
    async def test_a_404_on_the_calendar_read_is_a_not_found_and_nothing_is_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CALENDAR_PATH).mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        delete_route = _deletes(graph)

        with pytest.raises(GraphNotFound):
            _ = await _delete(client, confirm=_never_asked)

        assert delete_route.call_count == 0

    async def test_a_404_on_the_delete_after_the_read_found_the_calendar_answers_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = graph.delete(_CALENDAR_PATH).mock(
            return_value=httpx.Response(404, json=_NOT_FOUND)
        )

        answer = await _delete(client)

        assert delete_route.call_count == 1
        assert answer.deleted is True

    async def test_a_403_on_the_delete_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = graph.delete(_CALENDAR_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _delete(client)

    async def test_the_call_example_reaches_graph_and_the_first_read_is_what_a_403_refuses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", deleter.GRAPH_CALL_EXAMPLE)
        handle = calendar_handle(example["calendar_ref"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own value is not a calendar handle"
        refused = graph.get(f"/me/calendars/{quote(handle.calendar_id, safe='')}").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _delete(client, calendar_ref=example["calendar_ref"], confirm=_never_asked)

        assert refused.call_count == 1


class TestConfirmationIsAlwaysAsked:
    async def test_an_empty_calendar_of_the_user_is_still_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)
        asked: list[str] = []

        async def counting(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _delete(client, confirm=counting)

        assert len(asked) == 1, "a delete must always be put to the user"
        assert delete_route.call_count == 1

    async def test_a_refusal_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)

        with pytest.raises(ToolError, match="The calendar was not deleted"):
            _ = await delete_calendar(client, calendar_ref=_URI, confirm=_refuses)

        assert delete_route.call_count == 0

    async def test_the_question_names_the_calendar_and_what_microsoft_does_not_document(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _calendar(name="Project Apollo"))
        _ = _deletes(graph)
        asked: list[str] = []
        bound: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            asked.append(question)
            bound.append(about)
            return None

        _ = await _delete(client, confirm=capturing)

        assert len(asked) == 1
        assert "'Project Apollo'" in asked[0]
        assert "holds no event" in asked[0]
        assert "does not document whether a deleted calendar can be restored" in asked[0]
        assert bound == [_STATE]

    async def test_a_calendar_with_no_name_is_named_by_its_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _calendar(name=None))
        _ = _deletes(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> str | None:
            assert about
            asked.append(question)
            return None

        _ = await _delete(client, confirm=capturing)

        assert _URI in asked[0]

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="keep the calendar"),
            MCPError(METHOD_NOT_FOUND, "Method not found"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_every_answer_but_agreement_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: object
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)

        with pytest.raises(ToolError):
            _ = await delete_calendar(
                client, calendar_ref=_URI, confirm=a_person_agrees(_context(answer))
            )

        assert delete_route.call_count == 0

    async def test_a_decline_opens_by_saying_the_calendar_was_not_deleted(self) -> None:
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        refusal = await confirm("Delete the calendar 'Project Apollo'?", _STATE)

        assert isinstance(refusal, str)
        assert refusal.startswith("The calendar was not deleted.")

    async def test_agreement_over_the_back_channel_deletes_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)

        answer = await delete_calendar(
            client,
            calendar_ref=_URI,
            confirm=a_person_agrees(_context(AcceptedElicitation(data="delete"))),
        )

        assert isinstance(answer, DeletedCalendar)
        assert delete_route.call_count == 1


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


async def _first_round(client: GraphServiceClient) -> str:
    first = await delete_calendar(
        client, calendar_ref=_URI, confirm=a_person_agrees(_modern_context())
    )
    assert isinstance(first, InputRequiredResult)
    return next(iter(first.input_requests or {}))


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _calendar(name="Project Apollo"))
        delete_route = _deletes(graph)

        answer = await delete_calendar(
            client, calendar_ref=_URI, confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == _STATE
        requests = answer.input_requests or {}
        request = requests[next(iter(requests))]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        assert "Project Apollo" in params.message
        assert delete_route.call_count == 0

    async def test_the_second_round_deletes_under_the_state_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)
        key = await _first_round(client)

        answer = await delete_calendar(
            client,
            calendar_ref=_URI,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "delete"})},
                    state=_STATE,
                )
            ),
        )

        assert isinstance(answer, DeletedCalendar)
        assert delete_route.call_count == 1

    async def test_a_second_round_that_declines_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)
        key = await _first_round(client)

        with pytest.raises(ToolError, match="The calendar was not deleted"):
            _ = await delete_calendar(
                client,
                calendar_ref=_URI,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=_STATE)
                ),
            )

        assert delete_route.call_count == 0

    async def test_an_answer_bound_to_another_request_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete_route = _deletes(graph)
        key = await _first_round(client)

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await delete_calendar(
                client,
                calendar_ref=_URI,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "delete"})},
                        state="synthetic-other-state",
                    )
                ),
            )

        assert delete_route.call_count == 0

    async def test_a_refused_calendar_is_never_put_to_a_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, events=_events("AAMkSYNTHETIC-event-0001="))
        delete_route = _deletes(graph)

        with pytest.raises(ToolError, match="holds at least one event"):
            _ = await delete_calendar(
                client, calendar_ref=_URI, confirm=a_person_agrees(_modern_context())
            )

        assert delete_route.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permissions_are_calendars_readwrite_and_user_read(self) -> None:
        assert deleter.GRAPH_PERMISSIONS == ("Calendars.ReadWrite", "User.Read")

    def test_the_call_example_is_a_calendar_handle_and_nothing_else(self) -> None:
        assert set(deleter.GRAPH_CALL_EXAMPLE) == {"calendar_ref"}
        assert calendar_handle(cast("str", deleter.GRAPH_CALL_EXAMPLE["calendar_ref"]))

    async def test_it_takes_one_argument_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"calendar_ref"}

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)
        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_announces_itself_as_a_destructive_idempotent_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"]

    async def test_the_description_says_what_happens_to_the_events_and_to_a_restore(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "This tool always asks the user to agree" in description
        assert "No event is lost, because this tool refuses a calendar that holds an event" in (
            description
        )
        assert "the default calendar" in description
        assert "another person owns" in description
        assert "Microsoft does not document whether a deleted calendar can be restored" in (
            description
        )
        assert "outlook_list_calendars" in description
        assert "Notes:" in description

    def test_not_found_advice_points_at_the_lister(self) -> None:
        assert "outlook_list_calendars" in deleter.GRAPH_NOT_FOUND
        assert "nothing was deleted" in deleter.GRAPH_NOT_FOUND

    def test_it_never_reaches_for_a_permanent_delete(self) -> None:
        assert "permanent_delete" not in pathlib.Path(deleter.__file__).read_text()
