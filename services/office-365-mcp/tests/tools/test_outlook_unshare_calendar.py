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
from office_365_mcp.shared.handles import (
    CalendarHandle,
    CalendarPermissionHandle,
    EventHandle,
    calendar_permission_handle,
)
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm
from office_365_mcp.tools import outlook_unshare_calendar as unsharer
from office_365_mcp.tools.outlook_unshare_calendar import (
    UnsharedCalendar,
    a_person_agrees,
    unshare_calendar,
)

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0002="
_SHARE_ID = "RXhjaGFuZ2VQdWJsaXNoZWRVc2VyLmRhbmE="
_ORGANIZATION_SHARE = "RGVmYXVsdA=="

_URI = CalendarPermissionHandle(_CALENDAR_ID, _SHARE_ID).uri
_CALENDAR_URI = CalendarHandle(_CALENDAR_ID).uri

_CALENDAR_PATH = f"/me/calendars/{quote(_CALENDAR_ID, safe='')}"
_SHARE_PATH = f"{_CALENDAR_PATH}/calendarPermissions/{quote(_SHARE_ID, safe='')}"

_STATE = confirmation_id_for(_URI, unsharer.TOOL_NAME)

_DANA = "dana@example.invalid"

_NOTHING_REMOVED = "The share was not removed."

_NOT_FOUND = {"error": {"code": "ErrorItemNotFound", "message": "not found"}}
_DENIED = {"error": {"code": "ErrorAccessDenied", "message": "denied"}}


def _permission(
    *,
    name: str | None = "Dana Swope",
    address: str | None = _DANA,
    role: str | None = "read",
    removable: bool | None = True,
) -> dict[str, object]:
    person: dict[str, object] = {}
    if name is not None:
        person["name"] = name
    if address is not None:
        person["address"] = address
    return {
        "id": _SHARE_ID,
        "isRemovable": removable,
        "isInsideOrganization": True,
        "role": role,
        "allowedRoles": ["freeBusyRead", "limitedRead", "read", "write"],
        "emailAddress": person,
    }


def _organization() -> dict[str, object]:
    return {
        "id": _ORGANIZATION_SHARE,
        "isRemovable": False,
        "isInsideOrganization": True,
        "role": "freeBusyRead",
        "allowedRoles": ["none", "freeBusyRead", "limitedRead", "read", "write"],
        "emailAddress": {"name": "My Organization"},
    }


def _calendar(*, name: str | None = "Project Apollo") -> dict[str, object]:
    return {"id": _CALENDAR_ID, "name": name}


def _reads(
    graph: respx.MockRouter,
    *,
    permission: Mapping[str, object] | None = None,
    calendar: Mapping[str, object] | None = None,
) -> tuple[respx.Route, respx.Route]:
    permission_route = graph.get(_SHARE_PATH).mock(
        return_value=httpx.Response(200, json=dict(permission or _permission()))
    )
    calendar_route = graph.get(_CALENDAR_PATH).mock(
        return_value=httpx.Response(200, json=dict(calendar or _calendar()))
    )
    return permission_route, calendar_route


def _removes(graph: respx.MockRouter, *, status: int = 204) -> respx.Route:
    return graph.delete(_SHARE_PATH).mock(return_value=httpx.Response(status))


def _ready(graph: respx.MockRouter) -> respx.Route:
    _ = _reads(graph)
    return _removes(graph)


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return _NOTHING_REMOVED


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"a refused share was put to a person: {question!r} ({about})")


async def _unshare(
    client: GraphServiceClient, *, share_ref: str = _URI, confirm: Confirm = _agrees
) -> UnsharedCalendar:
    answer = await unshare_calendar(client, share_ref=share_ref, confirm=confirm)
    assert isinstance(answer, UnsharedCalendar), "this call was answered with a question"
    return answer


def _made(route: respx.Route) -> Sequence[Call]:
    return cast("Sequence[Call]", route.calls)


def _capturing() -> tuple[list[str], list[str], Confirm]:
    asked: list[str] = []
    bound: list[str] = []

    async def capture(question: str, about: str) -> str | None:
        asked.append(question)
        bound.append(about)
        return None

    return asked, bound, capture


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
    first = await unshare_calendar(
        client, share_ref=_URI, confirm=a_person_agrees(_modern_context())
    )
    assert isinstance(first, InputRequiredResult)
    return next(iter(first.input_requests or {}))


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    unsharer.register(mcp, transport)
    tool = await mcp.get_tool(unsharer.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_reads_the_share_and_the_calendar_then_removes_the_share(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        _ = await _unshare(client)

        made = cast("Sequence[Call]", graph.calls)
        calendar = f"/v1.0/me/calendars/{_CALENDAR_ID}"
        share = f"{calendar}/calendarPermissions/{_SHARE_ID}"
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", share),
            ("GET", calendar),
            ("DELETE", share),
        ]

    async def test_the_calendar_read_asks_for_the_name_and_nothing_more(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _, calendar_route = _reads(graph)
        _ = _removes(graph)

        _ = await _unshare(client)

        assert _made(calendar_route)[0].request.url.params["$select"] == "id,name"

    async def test_the_removal_carries_no_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        removal = _ready(graph)

        _ = await _unshare(client)

        assert removal.calls.last.request.content == b""

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_removal_graph_declines_is_retried_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        removal = graph.delete(_SHARE_PATH).mock(
            side_effect=[httpx.Response(503), httpx.Response(204)]
        )

        _ = await _unshare(client)

        assert removal.call_count == 2, "a removal is idempotent, so the SDK's retry runs"


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            _CALENDAR_URI,
            EventHandle(_CALENDAR_ID, "AAMkSYNTHETIC-event-0001=").uri,
            _DANA,
            _SHARE_ID,
            "",
            f"outlook:///calendarpermissions/{quote(_CALENDAR_ID, safe='')}",
            f"outlook:///calendarpermissions/%20/{quote(_SHARE_ID, safe='')}",
        ],
    )
    async def test_a_value_that_is_not_a_share_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook_list_calendar_shares") as raised:
            _ = await _unshare(client, share_ref=value, confirm=_never_asked)

        assert "Nothing was removed." in str(raised.value)
        assert len(graph.calls) == 0

    async def test_the_organization_row_is_refused_before_the_calendar_is_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _, calendar_route = _reads(graph, permission=_organization())
        removal = _removes(graph)

        with pytest.raises(ToolError, match="marks this share as not removable") as raised:
            _ = await _unshare(client, confirm=_never_asked)

        assert "The `My Organization` row is always like this" in str(raised.value)
        assert "Nothing was removed." in str(raised.value)
        assert calendar_route.call_count == 0
        assert removal.call_count == 0

    async def test_an_unknown_removable_flag_lets_microsoft_decide(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, permission=_permission(removable=None))
        removal = _removes(graph)

        _ = await _unshare(client)

        assert removal.call_count == 1


class TestThePersonBetweenTheRequestAndTheRemoval:
    async def test_every_removal_is_asked_about_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        removal = _ready(graph)
        asked, _bound, capture = _capturing()

        _ = await _unshare(client, confirm=capture)

        assert len(asked) == 1, "a removal must always be put to the user"
        assert removal.call_count == 1

    async def test_the_question_is_asked_after_the_reads_and_before_the_removal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        permission_route, calendar_route = _reads(graph)
        removal = _removes(graph)
        made_when_asked: list[tuple[int, int, int]] = []

        async def watching(question: str, about: str) -> str | None:
            assert question
            assert about
            made_when_asked.append(
                (permission_route.call_count, calendar_route.call_count, removal.call_count)
            )
            return None

        _ = await _unshare(client, confirm=watching)

        assert made_when_asked == [(1, 1, 0)]

    async def test_a_refusal_removes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        removal = _ready(graph)

        with pytest.raises(ToolError, match=_NOTHING_REMOVED):
            _ = await unshare_calendar(client, share_ref=_URI, confirm=_refuses)

        assert removal.call_count == 0

    async def test_the_question_names_the_calendar_the_person_and_the_role(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, permission=_permission(role="write"))
        _ = _removes(graph)
        asked, bound, capture = _capturing()

        _ = await _unshare(client, confirm=capture)

        assert asked == [
            f"Stop sharing the calendar 'Project Apollo' with {_DANA}? This person has the role "
            + "write on it now. This person then loses the access that the share gives."
        ]
        assert bound == [_STATE]

    async def test_a_person_with_no_address_is_named_by_the_name_microsoft_reports(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, permission=_permission(address=None))
        _ = _removes(graph)
        asked, _bound, capture = _capturing()

        _ = await _unshare(client, confirm=capture)

        assert "with Dana Swope?" in asked[0]

    async def test_a_person_microsoft_reports_nothing_about_is_still_put_to_the_user(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, permission=_permission(name=None, address=None, role=None))
        _ = _removes(graph)
        asked, _bound, capture = _capturing()

        _ = await _unshare(client, confirm=capture)

        assert "with a person whose address Microsoft did not report?" in asked[0]
        assert "Microsoft did not report the role of this person." in asked[0]
        assert "loses the access that the share gives" in asked[0]

    async def test_a_calendar_with_no_name_is_named_by_its_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, calendar=_calendar(name=None))
        _ = _removes(graph)
        asked, _bound, capture = _capturing()

        _ = await _unshare(client, confirm=capture)

        assert _CALENDAR_URI in asked[0]

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="keep the share"),
            MCPError(METHOD_NOT_FOUND, "Method not found"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_every_answer_but_agreement_removes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: object
    ) -> None:
        removal = _ready(graph)

        with pytest.raises(ToolError):
            _ = await unshare_calendar(
                client, share_ref=_URI, confirm=a_person_agrees(_context(answer))
            )

        assert removal.call_count == 0

    async def test_a_decline_opens_by_saying_the_share_was_not_removed(self) -> None:
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        refusal = await confirm("Stop sharing the calendar 'Project Apollo'?", _STATE)

        assert isinstance(refusal, str)
        assert refusal.startswith(_NOTHING_REMOVED)

    async def test_agreement_over_the_back_channel_removes_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        removal = _ready(graph)

        answer = await unshare_calendar(
            client,
            share_ref=_URI,
            confirm=a_person_agrees(_context(AcceptedElicitation(data="stop sharing"))),
        )

        assert isinstance(answer, UnsharedCalendar)
        assert removal.call_count == 1


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_removal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        removal = _ready(graph)

        answer = await unshare_calendar(
            client, share_ref=_URI, confirm=a_person_agrees(_modern_context())
        )

        assert isinstance(answer, InputRequiredResult)
        assert answer.request_state == _STATE
        requests = answer.input_requests or {}
        request = requests[next(iter(requests))]
        assert isinstance(request, ElicitRequest)
        params = request.params
        assert isinstance(params, ElicitRequestFormParams)
        assert "Project Apollo" in params.message
        assert _DANA in params.message
        assert removal.call_count == 0

    async def test_the_second_round_removes_under_the_state_it_was_agreed_to_by(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        removal = _ready(graph)
        key = await _first_round(client)

        answer = await unshare_calendar(
            client,
            share_ref=_URI,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "stop sharing"})},
                    state=_STATE,
                )
            ),
        )

        assert isinstance(answer, UnsharedCalendar)
        assert removal.call_count == 1

    async def test_a_second_round_that_declines_removes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        removal = _ready(graph)
        key = await _first_round(client)

        with pytest.raises(ToolError, match=_NOTHING_REMOVED):
            _ = await unshare_calendar(
                client,
                share_ref=_URI,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=_STATE)
                ),
            )

        assert removal.call_count == 0

    async def test_an_answer_bound_to_another_request_removes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        removal = _ready(graph)
        key = await _first_round(client)

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await unshare_calendar(
                client,
                share_ref=_URI,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": "stop sharing"})
                        },
                        state="synthetic-other-state",
                    )
                ),
            )

        assert removal.call_count == 0

    async def test_a_refused_share_is_never_put_to_a_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, permission=_organization())
        removal = _removes(graph)

        with pytest.raises(ToolError, match="not removable"):
            _ = await unshare_calendar(
                client, share_ref=_URI, confirm=a_person_agrees(_modern_context())
            )

        assert removal.call_count == 0


class TestGraphFailures:
    async def test_a_share_graph_does_not_return_asks_nobody_and_removes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_SHARE_PATH).mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        removal = _removes(graph)

        with pytest.raises(GraphNotFound):
            _ = await _unshare(client, confirm=_never_asked)

        assert removal.call_count == 0

    async def test_a_404_on_the_removal_after_the_read_found_the_share_answers_removed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        removal = graph.delete(_SHARE_PATH).mock(return_value=httpx.Response(404, json=_NOT_FOUND))

        answer = await _unshare(client)

        assert removal.call_count == 1
        assert answer.removed is True

    async def test_a_403_on_the_removal_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = graph.delete(_SHARE_PATH).mock(return_value=httpx.Response(403, json=_DENIED))

        with pytest.raises(GraphForbidden):
            _ = await _unshare(client)

    async def test_the_call_example_reaches_graph_and_the_first_read_is_what_a_403_refuses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", unsharer.GRAPH_CALL_EXAMPLE)
        handle = calendar_permission_handle(example["share_ref"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own value is not a share handle"
        refused = graph.get(
            f"/me/calendars/{quote(handle.calendar_id, safe='')}"
            + f"/calendarPermissions/{quote(handle.permission_id, safe='')}"
        ).mock(return_value=httpx.Response(403, json=_DENIED))

        with pytest.raises(GraphForbidden):
            _ = await _unshare(client, share_ref=example["share_ref"], confirm=_never_asked)

        assert refused.call_count == 1


class TestWhatItAnswers:
    async def test_the_answer_echoes_the_handle_and_names_the_calendar_and_the_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        answer = await _unshare(client)

        assert answer.uri == _URI
        assert answer.calendar_uri == _CALENDAR_URI
        assert answer.address == _DANA
        assert answer.removed is True

    async def test_a_person_with_no_address_answers_a_null_address(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, permission=_permission(address=None))
        _ = _removes(graph)

        answer = await _unshare(client)

        assert answer.address is None


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_the_removal_needs(self) -> None:
        assert unsharer.GRAPH_PERMISSIONS == ("Calendars.ReadWrite",)

    def test_the_call_example_is_a_share_handle_and_nothing_else(self) -> None:
        assert set(unsharer.GRAPH_CALL_EXAMPLE) == {"share_ref"}
        assert calendar_permission_handle(cast("str", unsharer.GRAPH_CALL_EXAMPLE["share_ref"]))

    def test_the_not_found_advice_says_nothing_was_removed(self) -> None:
        assert "nothing was removed" in unsharer.GRAPH_NOT_FOUND
        assert "outlook_list_calendar_shares" in unsharer.GRAPH_NOT_FOUND

    async def test_it_takes_one_share_handle_that_cannot_be_empty(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        assert set(properties) == {"share_ref"}
        assert parameters["required"] == ["share_ref"]
        assert properties["share_ref"]["minLength"] == 1

    async def test_the_input_schema_is_a_plain_object_at_its_root(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert parameters["type"] == "object"
        assert not {"anyOf", "oneOf", "allOf", "not", "enum", "const"} & set(parameters)

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

    async def test_the_description_is_a_lead_and_a_few_notes_of_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lead, separator, notes = description.partition("\n\nNotes:\n")
        assert separator, "the description has no Notes section"
        assert lead.strip() != ""
        assert 1 <= len([line for line in notes.splitlines() if line.startswith("- ")]) <= 4
        assert 45 <= len(description.split()) <= 210

    async def test_the_description_says_it_always_asks_what_it_refuses_and_that_a_repeat_is_safe(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "This tool always asks the user to agree, and the question names the calendar, the "
            + "person and the role."
        ) in description
        assert "This tool refuses the `My Organization` row" in description
        assert "This call is safe to repeat after a timeout." in description
        assert "outlook_list_calendar_shares lists the shares of a calendar" in description
        assert "outlook_share_calendar" in description

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        properties = cast("Mapping[str, Mapping[str, object]]", answer["properties"])
        assert set(properties) == {"uri", "calendar_uri", "address", "removed"}
        undescribed = sorted(
            name for name, field in properties.items() if not field.get("description")
        )
        assert undescribed == []
