import json
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
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphUnavailable,
)
from office_365_mcp.shared.calendar import confirmation_id_for
from office_365_mcp.shared.handles import (
    CalendarHandle,
    CalendarPermissionHandle,
    EventHandle,
    calendar_handle,
)
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm
from office_365_mcp.tools import outlook_share_calendar as sharer
from office_365_mcp.tools.outlook_share_calendar import (
    SharedCalendar,
    ShareRole,
    a_person_agrees,
    share_calendar,
)

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0002="
_SHARE_ID = "RXhjaGFuZ2VQdWJsaXNoZWRVc2VyLmRhbmE="

_URI = CalendarHandle(_CALENDAR_ID).uri

_CALENDAR_PATH = f"/me/calendars/{quote(_CALENDAR_ID, safe='')}"
_PERMISSIONS_PATH = f"{_CALENDAR_PATH}/calendarPermissions"

_DANA = "dana@example.invalid"

_NOTHING_SHARED = "The calendar was not shared."

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

_EVERY_OFFERED_ROLE = ["freeBusyRead", "limitedRead", "read", "write"]


def _calendar(
    *, name: str | None = "Project Apollo", can_share: bool | None = True
) -> dict[str, object]:
    return {"id": _CALENDAR_ID, "name": name, "canShare": can_share}


def _created(
    *, role: str | None = "read", name: str | None = "Dana Swope", share_id: str = _SHARE_ID
) -> dict[str, object]:
    return {
        "id": share_id,
        "isRemovable": True,
        "isInsideOrganization": True,
        "role": role,
        "allowedRoles": _EVERY_OFFERED_ROLE,
        "emailAddress": {"name": name, "address": _DANA},
    }


def _reads(graph: respx.MockRouter, *, calendar: Mapping[str, object] | None = None) -> respx.Route:
    return graph.get(_CALENDAR_PATH).mock(
        return_value=httpx.Response(200, json=dict(calendar or _calendar()))
    )


def _shares(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.post(_PERMISSIONS_PATH).mock(
        return_value=httpx.Response(200, json=dict(payload or _created()))
    )


def _ready(graph: respx.MockRouter) -> respx.Route:
    _ = _reads(graph)
    return _shares(graph)


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return _NOTHING_SHARED


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"a refused share was put to a person: {question!r} ({about})")


async def _round(
    client: GraphServiceClient,
    *,
    calendar_ref: str = _URI,
    address: str = _DANA,
    role: ShareRole = "read",
    confirm: Confirm = _agrees,
) -> SharedCalendar | InputRequiredResult:
    return await share_calendar(
        client, calendar_ref=calendar_ref, address=address, role=role, confirm=confirm
    )


async def _share(
    client: GraphServiceClient,
    *,
    calendar_ref: str = _URI,
    address: str = _DANA,
    role: ShareRole = "read",
    confirm: Confirm = _agrees,
) -> SharedCalendar:
    answer = await _round(
        client, calendar_ref=calendar_ref, address=address, role=role, confirm=confirm
    )
    assert isinstance(answer, SharedCalendar), "this call was answered with a question"
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


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
    *, answers: Mapping[str, object] | None = None, state: str | None = None
) -> Context:
    class _Client:
        request_context: _ModernRequest = _ModernRequest()
        input_responses: Mapping[str, object] | None = answers
        request_state: str | None = state

        async def elicit(self, message: str, response_type: object = None) -> object:
            raise AssertionError(
                f"a connection with no back-channel was asked {message!r} over it, "
                + f"expecting {response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


def _the_question(answer: SharedCalendar | InputRequiredResult) -> tuple[str, str, str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams)
    properties = cast(
        "Mapping[str, Mapping[str, object]]",
        cast("Mapping[str, object]", params.requested_schema)["properties"],
    )
    agree = cast("Sequence[str]", properties["value"]["enum"])[0]
    assert answer.request_state is not None
    return key, answer.request_state, agree, params.message


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    sharer.register(mcp, transport)
    tool = await mcp.get_tool(sharer.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _property(parameters: Mapping[str, object], name: str) -> Mapping[str, object]:
    properties = cast("Mapping[str, object]", parameters["properties"])
    return cast("Mapping[str, object]", properties[name])


class TestWhatItSendsToGraph:
    async def test_it_reads_the_calendar_then_shares(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        _ = await _share(client)

        made = cast("Sequence[Call]", graph.calls)
        calendar = f"/v1.0/me/calendars/{_CALENDAR_ID}"
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", calendar),
            ("POST", f"{calendar}/calendarPermissions"),
        ]

    @pytest.mark.parametrize("role", _EVERY_OFFERED_ROLE)
    async def test_no_request_goes_to_allowed_calendar_sharing_roles(
        self, client: GraphServiceClient, graph: respx.MockRouter, role: ShareRole
    ) -> None:
        share = _ready(graph)

        _ = await _share(client, role=role)

        assert not [
            call
            for call in cast("Sequence[Call]", graph.calls)
            if "allowedCalendarSharingRoles" in str(call.request.url)
        ]
        assert _sent(share)["role"] == role

    async def test_the_calendar_read_asks_for_the_name_and_the_share_flag(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        calendar_route = _reads(graph)
        _ = _shares(graph)

        _ = await _share(client)

        assert _made(calendar_route)[0].request.url.params["$select"] == "id,name,canShare"

    async def test_the_body_carries_the_address_and_the_role_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        share = _ready(graph)

        _ = await _share(client, role="limitedRead")

        assert _sent(share) == {"emailAddress": {"address": _DANA}, "role": "limitedRead"}

    async def test_the_address_reaches_graph_without_the_whitespace_around_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        share = _ready(graph)

        _ = await _share(client, address=f"  {_DANA} ")

        assert _sent(share)["emailAddress"] == {"address": _DANA}


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_share_graph_answers_503_is_never_posted_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        share = graph.post(_PERMISSIONS_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _share(client)

        assert share.call_count == 1


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            EventHandle(_CALENDAR_ID, "AAMkSYNTHETIC-event-0001=").uri,
            CalendarPermissionHandle(_CALENDAR_ID, _SHARE_ID).uri,
            "Project Apollo",
            _CALENDAR_ID,
            "outlook:///calendars/%20",
        ],
    )
    async def test_a_value_that_is_not_a_calendar_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook_list_calendars") as raised:
            _ = await _share(client, calendar_ref=value, confirm=_never_asked)

        assert "Nothing was shared." in str(raised.value)
        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        "address",
        [
            "Dana Swope <dana@example.invalid>",
            "dana@example.invalid, erin@example.invalid",
            "Dana Swope",
            "",
        ],
        ids=["display-name", "two-in-one", "name-only", "empty"],
    )
    async def test_a_value_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, address: str
    ) -> None:
        with pytest.raises(ToolError, match="one SMTP address") as raised:
            _ = await _share(client, address=address, confirm=_never_asked)

        assert "Nothing was shared." in str(raised.value)
        assert len(graph.calls) == 0

    async def test_the_address_refusal_looks_for_outlook_find_recipient_only_where_it_exists(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError) as raised:
            _ = await _share(client, address="Dana Swope", confirm=_never_asked)

        message = str(raised.value)
        assert len(graph.calls) == 0
        assert (
            "If this deployment exposes outlook_find_recipient, use it to turn a name that the "
            "user gave into an address. If it does not, ask the user for the address."
        ) in message
        assert message.endswith(_AGAIN)

    async def test_a_calendar_the_user_cannot_share_is_refused_before_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        calendar_route = _reads(graph, calendar=_calendar(can_share=False))
        share = _shares(graph)

        with pytest.raises(ToolError, match="cannot share this calendar") as raised:
            _ = await _share(client, confirm=_never_asked)

        message = str(raised.value)
        assert "Only the person who created a calendar can share it." in message
        assert message.endswith(_AGAIN)
        assert calendar_route.call_count == 1
        assert share.call_count == 0

    async def test_an_unknown_share_flag_lets_microsoft_decide(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, calendar=_calendar(can_share=None))
        share = _shares(graph)

        _ = await _share(client)

        assert share.call_count == 1


class TestThePersonBetweenTheRequestAndTheShare:
    async def test_a_refusal_shares_nothing_after_the_read_that_precedes_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        calendar_route = _reads(graph)
        share = _shares(graph)

        with pytest.raises(ToolError, match=_NOTHING_SHARED):
            _ = await _share(client, confirm=_refuses)

        assert calendar_route.call_count == 1
        assert share.call_count == 0

    async def test_the_question_is_asked_after_the_read_and_before_the_share(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        calendar_route = _reads(graph)
        share = _shares(graph)
        made_when_asked: list[tuple[int, int]] = []

        async def watching(question: str, about: str) -> str | None:
            assert question
            assert about
            made_when_asked.append((calendar_route.call_count, share.call_count))
            return None

        _ = await _share(client, confirm=watching)

        assert made_when_asked == [(1, 0)]

    @pytest.mark.parametrize(
        ("role", "words"),
        [
            ("freeBusyRead", "see only when the owner is free or busy"),
            ("limitedRead", "and the subject and location of each event"),
            ("read", "see all the details of each event, except private events."),
            ("write", "and create, change and delete events that are not private"),
        ],
    )
    async def test_the_question_names_the_calendar_the_address_and_the_role_in_words(
        self, client: GraphServiceClient, graph: respx.MockRouter, role: ShareRole, words: str
    ) -> None:
        _ = _ready(graph)
        asked, _bound, capture = _capturing()

        _ = await _share(client, role=role, confirm=capture)

        assert len(asked) == 1
        question = asked[0]
        assert f"Share the calendar 'Project Apollo' with {_DANA}, with the role {role}?" in (
            question
        )
        assert words in question

    async def test_a_calendar_with_no_name_is_named_by_its_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, calendar=_calendar(name=None))
        _ = _shares(graph)
        asked, _bound, capture = _capturing()

        _ = await _share(client, confirm=capture)

        assert _URI in asked[0]

    async def test_the_agreement_is_bound_to_the_calendar_the_address_and_the_role(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        _asked, bound, capture = _capturing()

        _ = await _share(client, confirm=capture)
        _ = await _share(client, address=_DANA.upper(), confirm=capture)
        _ = await _share(client, address="erin@example.invalid", confirm=capture)
        _ = await _share(client, role="write", confirm=capture)

        assert bound[0] == bound[1], "a change of case does not make another address"
        assert bound[0] == confirmation_id_for(_URI, sharer.TOOL_NAME, _DANA, "read")
        assert len({bound[0], bound[2], bound[3]}) == 3


class TestTheEraWithAHandshake:
    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not share"),
            MCPError(METHOD_NOT_FOUND, "Method not found"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask"],
    )
    async def test_no_answer_but_agreement_shares_anything(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: object
    ) -> None:
        share = _ready(graph)

        with pytest.raises(ToolError) as raised:
            _ = await _share(client, confirm=a_person_agrees(_context(answer)))

        assert str(raised.value).startswith(_NOTHING_SHARED)
        assert share.call_count == 0

    async def test_agreement_shares_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        share = _ready(graph)

        _ = await _share(
            client, confirm=a_person_agrees(_context(AcceptedElicitation(data="share")))
        )

        assert share.call_count == 1


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_share(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        share = _ready(graph)

        answer = await _round(client, confirm=a_person_agrees(_modern_context()))

        _key, _state, _agree, message = _the_question(answer)
        assert _DANA in message
        assert "Project Apollo" in message
        assert share.call_count == 0

    async def test_the_second_round_shares_once_under_the_agreed_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        share = _ready(graph)
        key, state, agree, _message = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )

        answer = await _round(
            client,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agree})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, SharedCalendar)
        assert share.call_count == 1

    async def test_an_answer_bound_to_another_role_shares_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        share = _ready(graph)
        key, state, agree, _message = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _round(
                client,
                role="write",
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": agree})},
                        state=state,
                    )
                ),
            )

        assert share.call_count == 0

    async def test_a_second_round_the_person_declined_shares_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        share = _ready(graph)
        key, state, _agree, _message = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="did not agree") as raised:
            _ = await _round(
                client,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
            )

        assert str(raised.value).startswith(_NOTHING_SHARED)
        assert share.call_count == 0


class TestGraphFailures:
    async def test_a_calendar_graph_does_not_return_asks_nobody_and_shares_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CALENDAR_PATH).mock(return_value=httpx.Response(404))
        share = _shares(graph)
        asked, _bound, capture = _capturing()

        with pytest.raises(GraphNotFound):
            _ = await _share(client, confirm=capture)

        assert asked == []
        assert share.call_count == 0

    async def test_a_role_microsoft_refuses_on_the_share_claims_no_share(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        share = graph.post(_PERMISSIONS_PATH).mock(
            return_value=httpx.Response(
                400, json={"error": {"code": "invalidRequest", "message": "role not allowed"}}
            )
        )
        asked, _bound, capture = _capturing()

        with pytest.raises(GraphFailure) as raised:
            _ = await _share(client, role="write", confirm=capture)

        assert raised.value.status == 400
        assert len(asked) == 1
        assert share.call_count == 1
        assert [call.request.method for call in cast("Sequence[Call]", graph.calls)] == [
            "GET",
            "POST",
        ]

    async def test_the_call_example_reaches_graph_and_the_first_read_is_what_a_403_refuses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", sharer.GRAPH_CALL_EXAMPLE)
        handle = calendar_handle(example["calendar_ref"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own value is not a calendar handle"
        refused = graph.get(f"/me/calendars/{quote(handle.calendar_id, safe='')}").mock(
            return_value=httpx.Response(403)
        )

        with pytest.raises(GraphForbidden):
            _ = await _share(
                client,
                calendar_ref=example["calendar_ref"],
                address=example["address"],
                role=cast("ShareRole", example["role"]),
                confirm=_never_asked,
            )

        assert refused.call_count == 1


class TestWhatItAnswers:
    async def test_the_answer_is_built_from_the_new_share_and_the_arguments(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shares(graph, _created(role="read", name="Dana Swope"))

        answer = await _share(client, address=f" {_DANA}")

        assert answer.uri == CalendarPermissionHandle(_CALENDAR_ID, _SHARE_ID).uri
        assert answer.calendar_uri == _URI
        assert answer.address == _DANA
        assert answer.name == "Dana Swope"
        assert answer.role == "read"

    async def test_a_share_with_no_stored_name_or_role_answers_nulls(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shares(graph, _created(role=None, name=None))

        answer = await _share(client)

        assert answer.name is None
        assert answer.role is None


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_the_write_needs(self) -> None:
        assert sharer.GRAPH_PERMISSIONS == ("Calendars.ReadWrite",)

    def test_the_share_list_shows_the_change(self) -> None:
        assert sharer.CHANGE_SHOWN_BY == ("outlook_list_calendar_shares",)

    def test_the_not_found_advice_says_nothing_was_shared(self) -> None:
        assert "nothing was shared" in sharer.GRAPH_NOT_FOUND
        assert "outlook_list_calendars" in sharer.GRAPH_NOT_FOUND

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(sharer.GRAPH_CALL_EXAMPLE) == {"calendar_ref", "address", "role"}
        assert set(sharer.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_a_calendar_an_address_and_a_role(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"calendar_ref", "address", "role"}
        assert parameters["required"] == ["calendar_ref", "address", "role"]
        assert _property(parameters, "calendar_ref")["minLength"] == 1
        assert _property(parameters, "address")["minLength"] == 1

    async def test_the_roles_on_offer_are_the_four_share_roles_and_no_delegate_role(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        reference = cast("str", _property(parameters, "role")["$ref"])
        definitions = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
        assert definitions[reference.rpartition("/")[2]]["enum"] == _EVERY_OFFERED_ROLE

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

    async def test_it_announces_itself_as_an_additive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

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

    async def test_the_description_says_it_always_asks_and_where_the_address_comes_from(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "This tool asks the user to agree before it shares anything, every time." in description
        )
        assert "This tool shares nothing unless the user agrees." in description
        assert "The address must come from the user." in description
        assert "It cannot make a delegate." in description
        assert "outlook_list_calendars lists the calendars and their handles" in description

    async def test_the_description_says_microsoft_can_refuse_a_role_after_the_user_agrees(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "After the user agrees, Microsoft can refuse a role for that address on that "
            "calendar. Then this tool shares nothing."
        ) in description
        assert "refuses a role" not in description
        assert "does not allow" not in description

    async def test_the_description_says_a_share_takes_effect_only_after_an_outlook_step(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "This tool adds the share immediately after the user agrees." in description
        assert (
            "Microsoft documents that a share takes effect only after the person accepts an "
            "invitation or adds the calendar in an Outlook client. "
            "So do not tell the user that the person can see the calendar now."
        ) in description
        assert "Microsoft does not document whether the person gets a message about the share." in (
            description
        )

    async def test_the_share_handle_points_to_the_description_for_when_the_person_can_see_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        properties = cast("Mapping[str, Mapping[str, str]]", answer["properties"])
        uri = properties["uri"]["description"]
        assert (
            "The person can see the calendar only after the Outlook step that the tool "
            "description names."
        ) in uri
        assert "invitation" not in uri
        assert 15 <= len(uri.split()) <= 60

    async def test_the_description_says_a_timeout_is_not_a_reason_to_share_again(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "If a call times out, do not call this tool again first." in description
        assert "make sure that outlook_list_calendar_shares does not show `address`" in (
            description
        )

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        properties = cast("Mapping[str, Mapping[str, object]]", answer["properties"])
        assert set(properties) == {"uri", "calendar_uri", "address", "name", "role"}
        undescribed = sorted(
            name for name, field in properties.items() if not field.get("description")
        )
        assert undescribed == []
