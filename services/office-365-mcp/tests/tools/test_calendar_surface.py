import json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from azure.core.credentials import AccessToken as GraphAccessToken
from fastmcp import Client, FastMCP
from fastmcp.client.elicitation import ElicitRequestParams, ElicitResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from mcp.types import (
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    InputRequest,
    InputRequiredResult,
    TextContent,
)
from mcp.types import ElicitResult as CarriedAnswer
from mcp.types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from respx.models import Call
from starlette.applications import Starlette

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_365_mcp.tools import (
    ALWAYS_ON,
    outlook_create_event,
    outlook_create_event_on_behalf,
    outlook_list_calendars,
    outlook_list_events,
    outlook_read_event,
)

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"
_OBO_TOKEN = "synthetic-obo-graph-token"

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0001="
_EVENT_ID = "AAMkAGI2SYNTHETIC-immutable-0001="

_CALENDAR = "AAMkSYNTHETIC-cal-0001%3D"
_EVENT = "AAMkAGI2SYNTHETIC-immutable-0001%3D"

_ONE_CALENDAR = f"/me/calendars/{_CALENDAR}"
_ONE_EVENT = f"{_ONE_CALENDAR}/events/{_EVENT}"

_ALLOWED = "get /me, get /me/calendar, get /me/calendars, one calendar view, two creates"

_AGREES = "create"

_ME = {
    "id": "00000000-0000-4000-8000-000000000001",
    "displayName": "Ada Lovelace",
    "mail": "ada@example.invalid",
    "userPrincipalName": "ada@corp.example.invalid",
}

_CALENDAR_ROW: Mapping[str, object] = {
    "id": _CALENDAR_ID,
    "name": "Alex Wilber",
    "owner": {"name": "Alex Wilber", "address": "alex@example.invalid"},
    "canEdit": True,
    "canShare": False,
    "canViewPrivateItems": False,
    "isDefaultCalendar": False,
}

_EVENT_ROW: Mapping[str, object] = {
    "id": _EVENT_ID,
    "subject": "Pricing review",
    "start": {"dateTime": "2026-03-02T14:00:00.0000000", "timeZone": "UTC"},
    "end": {"dateTime": "2026-03-02T15:00:00.0000000", "timeZone": "UTC"},
    "isAllDay": False,
    "attendees": [],
}

_FORBIDDEN_POSTS = (
    f"{_ONE_EVENT}/cancel",
    f"{_ONE_EVENT}/accept",
    f"{_ONE_EVENT}/decline",
    f"{_ONE_EVENT}/tentativelyAccept",
    f"{_ONE_EVENT}/forward",
    "/me/findMeetingTimes",
    "/me/calendar/getSchedule",
)


class _StubOboCredential:
    async def get_token(self, *scopes: str) -> GraphAccessToken:
        _ = scopes
        return GraphAccessToken(token=_OBO_TOKEN, expires_on=0)


@pytest.fixture
def obo(monkeypatch: pytest.MonkeyPatch) -> None:
    credential = _StubOboCredential()

    async def get_obo_credential(
        _self: AzureProvider, *, user_assertion: str
    ) -> _StubOboCredential:
        assert user_assertion == _CLIENT_TOKEN, "the client's own token is what gets exchanged"
        return credential

    monkeypatch.setattr(AzureProvider, "get_obo_credential", get_obo_credential)
    monkeypatch.setattr(
        "fastmcp.server.dependencies.get_access_token",
        lambda: AccessToken(token=_CLIENT_TOKEN, client_id=_CLIENT_ID, scopes=["access_as_user"]),
    )


@pytest.fixture
def graph() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        for path in _FORBIDDEN_POSTS:
            _ = router.post(path).mock(return_value=httpx.Response(202))
        _ = router.patch(_ONE_EVENT).mock(return_value=httpx.Response(200, json=dict(_EVENT_ROW)))
        _ = router.delete(_ONE_EVENT).mock(return_value=httpx.Response(204))

        _ = router.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        _ = router.get("/me/calendars").mock(
            return_value=httpx.Response(200, json={"value": [dict(_CALENDAR_ROW)]})
        )
        _ = router.get("/me/calendar").mock(
            return_value=httpx.Response(200, json=dict(_CALENDAR_ROW))
        )
        _ = router.get(_ONE_CALENDAR).mock(
            return_value=httpx.Response(200, json=dict(_CALENDAR_ROW))
        )
        _ = router.get(f"{_ONE_CALENDAR}/calendarView").mock(
            return_value=httpx.Response(200, json={"value": [dict(_EVENT_ROW)]})
        )
        _ = router.get(_ONE_EVENT).mock(return_value=httpx.Response(200, json=dict(_EVENT_ROW)))
        _ = router.post("/me/events").mock(return_value=httpx.Response(201, json=dict(_EVENT_ROW)))
        _ = router.post(f"{_ONE_CALENDAR}/events").mock(
            return_value=httpx.Response(201, json=dict(_EVENT_ROW))
        )
        yield router


def _made(router: respx.MockRouter) -> Sequence[Call]:
    return cast("Sequence[Call]", router.calls)


def _object(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value)


def _the_word_for_yes(asked: InputRequest) -> str:
    assert isinstance(asked, ElicitRequest), "the question is not one a person answers"
    params = asked.params
    assert isinstance(params, ElicitRequestFormParams), "the question is not one a client can fill"
    choices = _object(_object(_object(params.requested_schema)["properties"])["value"])["enum"]
    return cast("Sequence[str]", choices)[0]


async def _agree(
    _message: str,
    _response_type: type | None,
    _params: ElicitRequestParams,
    _context: object,
) -> str:
    return _AGREES


async def _decline(
    _message: str,
    _response_type: type | None,
    _params: ElicitRequestParams,
    _context: object,
) -> ElicitResult[str]:
    return ElicitResult(action="decline")


@pytest.fixture
def app() -> Starlette:
    return create_app(
        config=AppConfig.model_validate({"public_base_url": "https://office-365-mcp.example"}),
        database_config=DatabaseConfig.model_validate(
            {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
        ),
        entra_config=EntraConfig.model_validate(
            {
                "tenant_id": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
                "client_id": _CLIENT_ID,
                "client_secret": "s3cr3t",
            }
        ),
        surface_config=SurfaceConfig.model_validate(
            {"tools_preset": ToolsPreset.OUTLOOK_CALENDAR_DELEGATE}
        ),
    )


@pytest.fixture
async def every_calendar_tool(app: Starlette) -> AsyncIterator[Client[FastMCPTransport]]:
    server = cast("FastMCP[None]", app.state.fastmcp_server)
    async with Client(FastMCPTransport(server), elicitation_handler=_agree) as client:
        yield client


@pytest.fixture
async def a_declining_client(app: Starlette) -> AsyncIterator[Client[FastMCPTransport]]:
    server = cast("FastMCP[None]", app.state.fastmcp_server)
    async with Client(FastMCPTransport(server), elicitation_handler=_decline) as client:
        yield client


_CALENDAR_TOOLS: tuple[tuple[str, Mapping[str, object]], ...] = (
    (outlook_list_calendars.TOOL_NAME, outlook_list_calendars.GRAPH_CALL_EXAMPLE),
    (outlook_list_events.TOOL_NAME, outlook_list_events.GRAPH_CALL_EXAMPLE),
    (outlook_read_event.TOOL_NAME, outlook_read_event.GRAPH_CALL_EXAMPLE),
    (outlook_create_event.TOOL_NAME, outlook_create_event.GRAPH_CALL_EXAMPLE),
    (
        outlook_create_event_on_behalf.TOOL_NAME,
        outlook_create_event_on_behalf.GRAPH_CALL_EXAMPLE,
    ),
)

_ONE_ATTENDEE = "grace@example.invalid"

_INVITING: Mapping[str, object] = {
    **outlook_create_event.GRAPH_CALL_EXAMPLE,
    "attendees": [_ONE_ATTENDEE],
}

_NEWER_CALENDAR_TOOLS: frozenset[str] = frozenset(
    {
        "outlook_check_availability",
        "outlook_suggest_meeting_times",
        "outlook_update_event",
        "outlook_cancel_event",
        "outlook_respond_to_invite",
    }
)

_THE_TWO_CREATES: tuple[tuple[str, Mapping[str, object]], ...] = (
    (outlook_create_event.TOOL_NAME, _INVITING),
    (
        outlook_create_event_on_behalf.TOOL_NAME,
        outlook_create_event_on_behalf.GRAPH_CALL_EXAMPLE,
    ),
)


@pytest.mark.usefixtures("obo")
class TestTheWholeCalendarSurfaceStaysInsideIt:
    async def test_the_whole_calendar_surface_is_registered_together(
        self, every_calendar_tool: Client[FastMCPTransport]
    ) -> None:
        listed = {tool.name for tool in await every_calendar_tool.list_tools()}

        assert listed == (
            {ALWAYS_ON} | {name for name, _arguments in _CALENDAR_TOOLS} | _NEWER_CALENDAR_TOOLS
        )

    async def test_every_tool_answers_on_the_call_the_registry_publishes(
        self, every_calendar_tool: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        for name, arguments in _CALENDAR_TOOLS:
            result = await every_calendar_tool.call_tool(name, dict(arguments))
            answer = cast("dict[str, object] | None", result.structured_content)

            assert answer is not None, f"{name} answered nothing on {_ALLOWED}"

        posted = [call.request.url.path for call in _made(graph) if call.request.method == "POST"]

        assert len(_made(graph)) > len(_CALENDAR_TOOLS), (
            "the five tools together make more than one Graph call each, and this run made "
            + f"{len(_made(graph))}"
        )
        assert posted == [
            "/v1.0/me/events",
            f"/v1.0/me/calendars/{_CALENDAR_ID}/events",
        ], f"the two creates posted {posted}"

    async def test_a_person_who_says_no_leaves_both_calendars_untouched(
        self, a_declining_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        for name, arguments in _THE_TWO_CREATES:
            with pytest.raises(ToolError):
                _ = await a_declining_client.call_tool(name, dict(arguments))

        reached = {f"{call.request.method} {call.request.url.path}" for call in _made(graph)}
        posted = [call.request.url.path for call in _made(graph) if call.request.method == "POST"]

        assert posted == [], f"a declined create posted {posted}"
        assert f"GET /v1.0/me/calendars/{_CALENDAR_ID}" in reached, (
            "the delegated create never read the calendar the question names an owner off"
        )
        assert "GET /v1.0/me/calendar" in reached, "the own-calendar create never read anything"

    async def test_an_agreed_create_that_invites_somebody_posts_once_under_a_transaction_id(
        self, every_calendar_tool: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        assert every_calendar_tool.protocol_version == LATEST_MODERN_VERSION, (
            "this file's whole point is a connection whose era has no back-channel"
        )

        result = await every_calendar_tool.call_tool(
            outlook_create_event.TOOL_NAME, dict(_INVITING)
        )

        assert result.structured_content is not None, "the confirmed create answered nothing"
        posted = [call for call in _made(graph) if call.request.method == "POST"]
        sent = cast("Mapping[str, object]", json.loads(posted[0].request.content))

        assert [call.request.url.path for call in posted] == ["/v1.0/me/events"], (
            f"the agreed create posted {[call.request.url.path for call in posted]}"
        )
        assert sent["transactionId"], "nothing told Microsoft what to dedupe a retry on"
        assert _ONE_ATTENDEE in json.dumps(sent), "the address the call named never reached Graph"

    async def test_an_accept_that_omits_the_request_state_creates_nothing(
        self, every_calendar_tool: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        first = await every_calendar_tool.session.call_tool(
            outlook_create_event.TOOL_NAME, dict(_INVITING), allow_input_required=True
        )

        assert isinstance(first, InputRequiredResult), "the question was never put to anybody"
        requests = first.input_requests or {}
        (key,) = requests
        agrees = _the_word_for_yes(requests[key])

        second = await every_calendar_tool.session.call_tool(
            outlook_create_event.TOOL_NAME,
            dict(_INVITING),
            input_responses={key: CarriedAnswer(action="accept", content={"value": agrees})},
            allow_input_required=True,
        )

        assert isinstance(second, CallToolResult), "the unbound retry asked again instead"
        assert second.is_error, "an accept bound to nothing was read as agreement"
        refusal = " ".join(block.text for block in second.content if isinstance(block, TextContent))
        posted = [call.request.url.path for call in _made(graph) if call.request.method == "POST"]

        assert "given for a different request" in refusal, refusal
        assert posted == [], f"an accept nothing was bound to posted {posted}"

    async def test_a_client_pinned_to_the_handshake_era_still_asks_and_writes(
        self, app: Starlette, graph: respx.MockRouter
    ) -> None:
        server = cast("FastMCP[None]", app.state.fastmcp_server)

        async with Client(
            FastMCPTransport(server), mode="legacy", elicitation_handler=_agree
        ) as client:
            assert client.protocol_version == LATEST_HANDSHAKE_VERSION, (
                "this pin no longer reaches the era it exists to cover"
            )
            result = await client.call_tool(
                outlook_create_event_on_behalf.TOOL_NAME,
                dict(outlook_create_event_on_behalf.GRAPH_CALL_EXAMPLE),
            )

        posted = [call.request.url.path for call in _made(graph) if call.request.method == "POST"]

        assert result.structured_content is not None, "the confirmed create answered nothing"
        assert posted == [f"/v1.0/me/calendars/{_CALENDAR_ID}/events"], (
            f"a handshake-era create posted {posted}"
        )

    async def test_nothing_answers_cancels_forwards_updates_or_deletes_an_event(
        self, every_calendar_tool: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        for name, arguments in _CALENDAR_TOOLS:
            _ = await every_calendar_tool.call_tool(name, dict(arguments))

        reached = {
            f"{call.request.method} {call.request.url.path}"
            for call in _made(graph)
            if call.request.method in ("PATCH", "DELETE")
            or call.request.url.path.rsplit("/", 1)[-1]
            in ("cancel", "accept", "decline", "tentativelyAccept", "forward")
        }

        assert reached == set(), f"the calendar surface reached {sorted(reached)}"

    async def test_nothing_asks_exchange_who_is_free(
        self, every_calendar_tool: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        for name, arguments in _CALENDAR_TOOLS:
            _ = await every_calendar_tool.call_tool(name, dict(arguments))

        reached = [
            call.request.url.path
            for call in _made(graph)
            if call.request.url.path.endswith(("findMeetingTimes", "getSchedule"))
        ]

        assert reached == [], f"the calendar surface reached {reached}"

    async def test_every_forbidden_route_is_one_this_mock_would_have_counted(
        self, graph: respx.MockRouter
    ) -> None:
        async with httpx.AsyncClient() as caller:
            for path in _FORBIDDEN_POSTS:
                answered = await caller.post(f"{GRAPH_V1}{path}")

                assert answered.status_code == 202, f"{path} is not mounted"
            patched = await caller.patch(f"{GRAPH_V1}{_ONE_EVENT}")
            deleted = await caller.delete(f"{GRAPH_V1}{_ONE_EVENT}")

        assert (patched.status_code, deleted.status_code) == (200, 204)
        assert len(_made(graph)) == len(_FORBIDDEN_POSTS) + 2, (
            "a path this mock does not match raises rather than counting, so the sweeps above "
            + "would pass over a rule that checks nothing"
        )
