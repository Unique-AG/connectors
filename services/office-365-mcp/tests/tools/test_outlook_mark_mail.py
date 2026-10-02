import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from azure.core.credentials import AccessToken as GraphAccessToken
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from fastmcp.tools import Tool
from mcp.types import InputRequiredResult, TextContent
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig
from office_365_mcp.graph_client import (
    GraphForbidden,
    GraphNotFound,
    GraphSettings,
    GraphUnavailable,
)
from office_365_mcp.shared import identity
from office_365_mcp.shared.calendar import ZONE_NAME
from office_365_mcp.shared.categories import LIST_CATEGORIES_GUARD
from office_365_mcp.shared.handles import MailMessageHandle
from office_365_mcp.shared.mail import FlagMoment, MailImportance
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm, Confirmed
from office_365_mcp.tools.outlook_mark_mail import (
    GRAPH_PERMISSIONS,
    TOOL_NAME,
    FlagStatus,
    MarkChange,
    MarkedMail,
    mark_mail,
    register,
)

from .conftest import ME

_IDS: tuple[str, ...] = (
    "AAMkAGI2SYNTHETIC-immutable-0001=",
    "AAMkAGI2SYNTHETIC-immutable-0002=",
    "AAMkAGI2SYNTHETIC-immutable-0003=",
)

_REFS: tuple[str, ...] = tuple(MailMessageHandle(message_id).uri for message_id in _IDS)

_PATHS: tuple[str, ...] = tuple(
    f"/me/messages/AAMkAGI2SYNTHETIC-immutable-000{number}%3D" for number in (1, 2, 3)
)

_NOT_FOUND: dict[str, object] = {
    "error": {"code": "ErrorItemNotFound", "message": "The specified object was not found."}
}

_ACCESS_DENIED: dict[str, object] = {
    "error": {"code": "ErrorAccessDenied", "message": "Access is denied."}
}

_REQUEST_ID = "synthetic-request-id"

_DRAFT_ONLY: tuple[str, ...] = ("subject", "body", "toRecipients", "ccRecipients")

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"

_MAILBOX = "alex@example.invalid"

_NOT_CHANGED = "No message was changed."

_RETRY_SENTENCE = (
    "If you call this tool again with the same arguments, the call will fail the same way."
)

_START = "2026-03-02T09:00"
_DUE = "2026-03-06T17:00"
_ZONE = "Europe/Berlin"

_DATED = MarkChange(flag_starts_at=_START, flag_due_at=_DUE, flag_time_zone=_ZONE)


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _declines(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOT_CHANGED


async def _never_asked(question: str, about: str) -> Confirmed:
    raise AssertionError(f"a person was asked {question!r} about {about!r}")


class _StubOboCredential:
    async def get_token(self, *scopes: str) -> GraphAccessToken:
        _ = scopes
        return GraphAccessToken(token="synthetic-obo-graph-token", expires_on=0)


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
async def server_client() -> AsyncIterator[Client[FastMCPTransport]]:
    app = create_app(
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
        surface_config=SurfaceConfig.model_validate({"tools_enabled": TOOL_NAME}),
    )
    server = cast("FastMCP[None]", app.state.fastmcp_server)
    async with Client(FastMCPTransport(server)) as client:
        yield client


def _updated(
    *,
    message_id: str = _IDS[0],
    is_read: bool | None = True,
    flag_status: str | None = "notFlagged",
    importance: str | None = "normal",
    flag: Mapping[str, object] | None = None,
    categories: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": message_id,
        "isRead": is_read,
        "importance": importance,
        "flag": flag or (None if flag_status is None else {"flagStatus": flag_status}),
        "categories": categories,
    }


def _writes(
    graph: respx.MockRouter,
    index: int = 0,
    *,
    is_read: bool | None = True,
    flag_status: str | None = "notFlagged",
    importance: str | None = "normal",
    flag: Mapping[str, object] | None = None,
    categories: list[str] | None = None,
) -> respx.Route:
    return graph.patch(_PATHS[index]).mock(
        return_value=httpx.Response(
            200,
            json=_updated(
                message_id=_IDS[index],
                is_read=is_read,
                flag_status=flag_status,
                importance=importance,
                flag=flag,
                categories=categories,
            ),
        )
    )


def _reads(graph: respx.MockRouter, index: int, categories: list[str]) -> respx.Route:
    return graph.get(_PATHS[index]).mock(
        return_value=httpx.Response(200, json={"id": _IDS[index], "categories": categories})
    )


def _every_read(graph: respx.MockRouter) -> respx.Route:
    return graph.route(method="GET").mock(
        return_value=httpx.Response(200, json={"id": _IDS[0], "categories": []})
    )


def _refuses(graph: respx.MockRouter, index: int, status: int) -> respx.Route:
    body = _ACCESS_DENIED if status == 403 else _NOT_FOUND
    return graph.patch(_PATHS[index]).mock(
        return_value=httpx.Response(status, headers={"request-id": _REQUEST_ID}, json=body)
    )


def _every_write(graph: respx.MockRouter) -> respx.Route:
    return graph.route(method="PATCH").mock(return_value=httpx.Response(200, json=_updated()))


def _paths(route: respx.Route) -> list[str]:
    return [call.request.url.path for call in cast("Sequence[Call]", route.calls)]


def _sent(route: respx.Route) -> Mapping[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _text(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


async def _call(client: Client[FastMCPTransport]) -> CallToolResult:
    return await client.call_tool(
        TOOL_NAME, {"message_refs": list(_REFS[:2]), "is_read": True}, raise_on_error=False
    )


def _answered(result: CallToolResult) -> MarkedMail:
    return MarkedMail.model_validate(cast("dict[str, object]", result.structured_content))


def _arguments(tool: Tool) -> Mapping[str, Mapping[str, object]]:
    return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP[None] = FastMCP("Mark Mail Under Test")
    register(mcp, transport)
    tool = await mcp.get_tool(TOOL_NAME)
    assert tool is not None, f"register declared no {TOOL_NAME}"
    return tool


def _narrowed(answer: MarkedMail | InputRequiredResult) -> MarkedMail:
    assert isinstance(answer, MarkedMail), "the confirmation asked instead of answering"
    return answer


async def _changed(
    client: GraphServiceClient,
    change: MarkChange,
    *,
    refs: int = 1,
    mailbox: str | None = None,
    confirm: Confirm = _never_asked,
) -> MarkedMail:
    return _narrowed(
        await mark_mail(
            client, message_refs=_REFS[:refs], change=change, confirm=confirm, mailbox=mailbox
        )
    )


async def _marked(
    client: GraphServiceClient,
    *,
    refs: int = 1,
    is_read: bool | None = None,
    flagged: bool | None = None,
    importance: MailImportance | None = None,
    mailbox: str | None = None,
    confirm: Confirm = _never_asked,
) -> MarkedMail:
    return await _changed(
        client,
        MarkChange(is_read=is_read, flagged=flagged, importance=importance),
        refs=refs,
        mailbox=mailbox,
        confirm=confirm,
    )


async def _asked(client: GraphServiceClient, change: MarkChange) -> tuple[str, str]:
    asked: list[tuple[str, str]] = []

    async def capturing(question: str, about: str) -> Confirmed:
        asked.append((question, about))
        return _NOT_CHANGED

    with pytest.raises(ToolError, match=_NOT_CHANGED):
        _ = await _changed(client, change, refs=2, mailbox=_MAILBOX, confirm=capturing)

    (only,) = asked
    return only


class TestTheBatchSize:
    async def test_a_batch_of_nothing_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _every_write(graph)

        with pytest.raises(AssertionError):
            _ = await mark_mail(
                client, message_refs=[], change=MarkChange(is_read=True), confirm=_never_asked
            )

        assert route.call_count == 0

    async def test_twenty_one_messages_are_all_written(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _every_write(graph)
        many = [MailMessageHandle(f"SYNTHETIC-{number}").uri for number in range(21)]

        answer = _narrowed(
            await mark_mail(
                client, message_refs=many, change=MarkChange(is_read=True), confirm=_never_asked
            )
        )

        assert route.call_count == 21
        assert len(answer.messages) == 21

    async def test_the_schema_needs_one_message_and_has_no_upper_size(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        refs = _arguments(tool)["message_refs"]
        assert refs["minItems"] == 1
        assert "maxItems" not in refs


class TestEveryWriteIsItsOwnRequest:
    async def test_each_handle_becomes_one_patch_of_its_own(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = [_writes(graph, index) for index in range(3)]

        answer = await _marked(client, refs=3, is_read=True)

        assert [route.call_count for route in routes] == [1, 1, 1]
        assert len(answer.messages) == 3

    async def test_every_row_carries_the_handle_it_was_given_in_the_order_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        for index in range(3):
            _ = _writes(graph, index)

        answer = await _marked(client, refs=3, is_read=True)

        assert [row.uri for row in answer.messages] == list(_REFS)

    async def test_one_refused_message_neither_hides_nor_becomes_the_whole_batch(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _writes(graph, 0)
        _ = graph.patch(_PATHS[1]).mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        _ = _writes(graph, 2)

        answer = await _marked(client, refs=3, is_read=True)

        assert [row.changed for row in answer.messages] == [True, False, True]
        assert answer.changed_count == 2
        assert answer.failed_count == 1

    async def test_a_refusal_does_not_stop_the_messages_after_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.patch(_PATHS[0]).mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        _ = _writes(graph, 1)
        last = _writes(graph, 2)

        answer = await _marked(client, refs=3, is_read=True)

        assert last.call_count == 1
        assert answer.messages[2].changed is True

    async def test_a_refused_row_says_what_microsoft_answered(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _refuses(graph, 0, 404)
        _ = _writes(graph, 1)

        answer = await _marked(client, refs=2, is_read=True)

        row = answer.messages[0]
        assert row.changed is False
        assert row.failure is not None
        assert "404" in row.failure
        assert "ErrorItemNotFound" in row.failure
        assert _REQUEST_ID in row.failure

    async def test_a_refused_row_reports_no_state_it_could_not_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _refuses(graph, 0, 404)
        _ = _writes(graph, 1)

        answer = await _marked(client, refs=2, is_read=True, flagged=True, importance="high")

        row = answer.messages[0]
        assert (row.is_read, row.flag_status, row.importance) == (None, None, None)


class TestWhenNoMessageChanged:
    @pytest.mark.parametrize(("status", "raised"), [(403, GraphForbidden), (404, GraphNotFound)])
    async def test_a_batch_where_every_write_is_refused_raises_instead_of_answering(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        status: int,
        raised: type[Exception],
    ) -> None:
        _ = _refuses(graph, 0, status)
        _ = _refuses(graph, 1, status)

        with pytest.raises(raised):
            _ = await _marked(client, refs=2, is_read=True)

    async def test_every_message_is_still_tried_before_it_raises(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = [_refuses(graph, index, 404) for index in range(3)]

        with pytest.raises(GraphNotFound):
            _ = await _marked(client, refs=3, is_read=True)

        assert [route.call_count for route in routes] == [1, 1, 1]


@pytest.mark.usefixtures("obo")
class TestWhatTheModelIsTold:
    async def test_a_permission_refused_on_every_message_names_the_permission_to_grant(
        self, server_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        _ = _refuses(graph, 0, 403)
        _ = _refuses(graph, 1, 403)

        result = await _call(server_client)

        told = _text(result)
        assert result.is_error, told
        assert "administrator" in told
        assert "Mail.ReadWrite and Mail.ReadWrite.Shared" in told
        assert f"Graph error code ErrorAccessDenied, Graph request id {_REQUEST_ID}" in told

    async def test_no_message_found_says_where_a_handle_must_come_from(
        self, server_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        _ = _refuses(graph, 0, 404)
        _ = _refuses(graph, 1, 404)

        result = await _call(server_client)

        told = _text(result)
        assert result.is_error, told
        assert "tool response verbatim" in told
        assert f"Graph error code ErrorItemNotFound, Graph request id {_REQUEST_ID}" in told

    async def test_one_refusal_of_two_still_answers_row_by_row(
        self, server_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        _ = _writes(graph, 0)
        _ = _refuses(graph, 1, 403)

        result = await _call(server_client)

        assert not result.is_error, _text(result)
        answer = _answered(result)
        assert [row.changed for row in answer.messages] == [True, False]
        assert (answer.changed_count, answer.failed_count) == (1, 1)

    async def test_a_zone_with_a_character_no_zone_name_has_is_refused_before_graph(
        self, server_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        route = graph.route().mock(return_value=httpx.Response(200, json=_updated()))

        result = await server_client.call_tool(
            TOOL_NAME,
            {
                "message_refs": list(_REFS[:1]),
                "flag_starts_at": _START,
                "flag_time_zone": "Europe/Berlin; DROP",
            },
            raise_on_error=False,
        )

        assert result.is_error, _text(result)
        assert route.call_count == 0

    async def test_the_new_arguments_reach_graph_through_the_published_schema(
        self, server_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, 0, ["Red"])
        write = _writes(graph, 0)

        result = await server_client.call_tool(
            TOOL_NAME,
            {
                "message_refs": list(_REFS[:1]),
                "flag_starts_at": _START,
                "flag_due_at": _DUE,
                "flag_time_zone": _ZONE,
                "add_categories": ["Blue"],
                "remove_categories": ["red"],
            },
            raise_on_error=False,
        )

        assert not result.is_error, _text(result)
        assert _sent(write) == {
            "@odata.type": "#microsoft.graph.message",
            "flag": {
                "flagStatus": "flagged",
                "startDateTime": {"dateTime": _START, "timeZone": _ZONE},
                "dueDateTime": {"dateTime": _DUE, "timeZone": _ZONE},
            },
            "categories": ["Blue"],
        }

    async def test_every_write_accepted_answers_row_by_row(
        self, server_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        _ = _writes(graph, 0)
        _ = _writes(graph, 1)

        result = await _call(server_client)

        assert not result.is_error, _text(result)
        answer = _answered(result)
        assert [row.changed for row in answer.messages] == [True, True]
        assert (answer.changed_count, answer.failed_count) == (2, 0)


class TestItEchoesGraphAndNotItsArguments:
    async def test_the_read_state_reported_is_the_one_microsoft_answered_with(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _writes(graph, 0, is_read=False)

        answer = await _marked(client, is_read=True)

        assert answer.messages[0].changed is True
        assert answer.messages[0].is_read is False

    async def test_the_flag_status_reported_is_the_one_microsoft_answered_with(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _writes(graph, 0, flag_status="complete")

        answer = await _marked(client, flagged=True)

        assert answer.messages[0].flag_status == "complete"

    async def test_the_importance_reported_is_the_one_microsoft_answered_with(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _writes(graph, 0, importance="low")

        answer = await _marked(client, importance="high")

        assert answer.messages[0].importance == "low"

    async def test_state_microsoft_did_not_report_back_is_null_rather_than_assumed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _writes(graph, 0, flag_status=None, importance=None, is_read=None)

        answer = await _marked(client, is_read=True, flagged=True, importance="high")

        row = answer.messages[0]
        assert row.changed is True
        assert (row.is_read, row.flag_status, row.importance) == (None, None, None)


class TestWhatItSendsToGraph:
    async def test_only_the_properties_the_call_named_are_written(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _writes(graph, 0)

        _ = await _marked(client, is_read=True)

        assert _sent(route) == {"@odata.type": "#microsoft.graph.message", "isRead": True}

    @pytest.mark.parametrize("draft_only", _DRAFT_ONLY)
    async def test_no_draft_only_property_is_ever_in_the_payload(
        self, client: GraphServiceClient, graph: respx.MockRouter, draft_only: str
    ) -> None:
        route = _writes(graph, 0)

        _ = await _marked(client, is_read=True, flagged=True, importance="high")

        assert draft_only not in _sent(route)

    @pytest.mark.parametrize("draft_only", _DRAFT_ONLY)
    async def test_no_draft_only_property_is_addressable_in_the_schema_either(
        self, transport: httpx.AsyncClient, draft_only: str
    ) -> None:
        tool = await _registered(transport)

        assert draft_only not in _arguments(tool)

    @pytest.mark.parametrize(("flagged", "status"), [(True, "flagged"), (False, "notFlagged")])
    async def test_the_flag_argument_is_written_as_a_followup_flag(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        flagged: bool,
        status: str,
    ) -> None:
        route = _writes(graph, 0)

        _ = await _marked(client, flagged=flagged)

        assert _sent(route)["flag"] == {"flagStatus": status}

    async def test_the_importance_argument_is_written_as_microsoft_spells_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _writes(graph, 0)

        _ = await _marked(client, importance="high")

        assert _sent(route)["importance"] == "high"

    async def test_it_declares_the_immutable_id_space_on_every_write(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = [_writes(graph, index) for index in range(3)]

        _ = await _marked(client, refs=3, is_read=True)

        for route in routes:
            assert 'IdType="ImmutableId"' in route.calls.last.request.headers["prefer"]

    async def test_the_preference_is_not_added_to_every_other_graph_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _writes(graph, 0)
        profile = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))

        _ = await _marked(client, is_read=True)
        _ = await identity.signed_in_user(client)

        assert "prefer" not in profile.calls.last.request.headers


class TestTheFollowUpFlag:
    async def test_the_flagged_argument_alone_writes_only_the_status(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _writes(graph, 0)

        _ = await _marked(client, flagged=True)

        assert _sent(route) == {
            "@odata.type": "#microsoft.graph.message",
            "flag": {"flagStatus": "flagged"},
        }

    @pytest.mark.parametrize("status", ["flagged", "complete", "notFlagged"])
    async def test_the_status_argument_is_written_as_a_followup_flag(
        self, client: GraphServiceClient, graph: respx.MockRouter, status: FlagStatus
    ) -> None:
        route = _writes(graph, 0)

        _ = await _changed(client, MarkChange(flag_status=status))

        assert _sent(route)["flag"] == {"flagStatus": status}

    async def test_a_start_and_a_due_date_are_written_in_the_zone_named(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _writes(graph, 0)

        _ = await _changed(client, _DATED)

        assert _sent(route)["flag"] == {
            "flagStatus": "flagged",
            "startDateTime": {"dateTime": _START, "timeZone": _ZONE},
            "dueDateTime": {"dateTime": _DUE, "timeZone": _ZONE},
        }

    async def test_a_start_date_alone_is_written_with_no_due_date(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _writes(graph, 0)

        _ = await _changed(client, MarkChange(flag_starts_at=_START, flag_time_zone=_ZONE))

        assert _sent(route)["flag"] == {
            "flagStatus": "flagged",
            "startDateTime": {"dateTime": _START, "timeZone": _ZONE},
        }

    @pytest.mark.parametrize(
        "status",
        [
            pytest.param(MarkChange(flagged=True), id="flagged"),
            pytest.param(MarkChange(flag_status="flagged"), id="flag_status"),
        ],
    )
    async def test_dates_go_with_a_status_that_flags_the_message(
        self, client: GraphServiceClient, graph: respx.MockRouter, status: MarkChange
    ) -> None:
        route = _writes(graph, 0)
        change = MarkChange(
            flagged=status.flagged,
            flag_status=status.flag_status,
            flag_starts_at=_START,
            flag_due_at=_START,
            flag_time_zone="UTC",
        )

        _ = await _changed(client, change)

        assert _sent(route)["flag"] == {
            "flagStatus": "flagged",
            "startDateTime": {"dateTime": _START, "timeZone": "UTC"},
            "dueDateTime": {"dateTime": _START, "timeZone": "UTC"},
        }

    async def test_the_dates_reported_are_the_ones_microsoft_answered_with(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _writes(
            graph,
            0,
            flag={
                "flagStatus": "flagged",
                "startDateTime": {"dateTime": "2026-03-02T08:00:00.0000000", "timeZone": "UTC"},
                "dueDateTime": {"dateTime": "2026-03-06T16:00:00.0000000", "timeZone": "UTC"},
            },
        )

        answer = await _changed(client, _DATED)

        row = answer.messages[0]
        assert row.flag_status == "flagged"
        assert row.flag_start == FlagMoment(
            date_time="2026-03-02T08:00:00.0000000", time_zone="UTC"
        )
        assert row.flag_due == FlagMoment(date_time="2026-03-06T16:00:00.0000000", time_zone="UTC")

    async def test_a_flag_with_no_dates_reports_no_dates(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _writes(graph, 0, flag_status="complete")

        answer = await _changed(client, MarkChange(flag_status="complete"))

        row = answer.messages[0]
        assert (row.flag_status, row.flag_start, row.flag_due) == ("complete", None, None)


class TestTheCategories:
    async def test_it_reads_the_categories_before_it_writes_the_merged_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, 0, ["Red", "Blue"])
        write = _writes(graph, 0)

        _ = await _changed(client, MarkChange(add_categories=("Green",)))

        assert read.call_count == 1
        assert _sent(write) == {
            "@odata.type": "#microsoft.graph.message",
            "categories": ["Red", "Blue", "Green"],
        }

    async def test_the_read_asks_only_for_the_categories_in_the_immutable_id_space(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, 0, [])
        _ = _writes(graph, 0)

        _ = await _changed(client, MarkChange(remove_categories=("Red",)))

        request = read.calls.last.request
        assert request.url.params["$select"] == "categories"
        assert 'IdType="ImmutableId"' in request.headers["prefer"]

    @pytest.mark.parametrize(
        ("current", "add", "remove", "written"),
        [
            pytest.param(["Red", "Blue"], ("Green",), (), ["Red", "Blue", "Green"], id="append"),
            pytest.param(["Red", "Blue"], ("red", "Green"), (), ["Red", "Blue", "Green"], id="had"),
            pytest.param([], ("Green", "GREEN"), (), ["Green"], id="added-twice"),
            pytest.param(["Red", "Blue"], (), ("BLUE",), ["Red"], id="remove-any-case"),
            pytest.param(["Red"], (), ("Red",), [], id="remove-the-last"),
            pytest.param(["Red"], (), ("Yellow",), ["Red"], id="remove-absent"),
            pytest.param(["Red", "Blue"], ("Green",), ("Red",), ["Blue", "Green"], id="both"),
        ],
    )
    async def test_the_merged_list_keeps_the_order_and_ignores_case(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        current: list[str],
        add: tuple[str, ...],
        remove: tuple[str, ...],
        written: list[str],
    ) -> None:
        _ = _reads(graph, 0, current)
        write = _writes(graph, 0)

        _ = await _changed(client, MarkChange(add_categories=add, remove_categories=remove))

        assert _sent(write)["categories"] == written

    async def test_no_category_argument_reads_nothing_and_writes_no_categories(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _every_read(graph)
        write = _writes(graph, 0)

        _ = await _marked(client, is_read=True)

        assert read.call_count == 0
        assert "categories" not in _sent(write)

    async def test_each_message_is_read_and_merged_on_its_own(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, 0, ["Red"])
        _ = _reads(graph, 1, ["Blue"])
        writes = [_writes(graph, index) for index in range(2)]

        _ = await _changed(client, MarkChange(add_categories=("Green",)), refs=2)

        assert [_sent(write)["categories"] for write in writes] == [
            ["Red", "Green"],
            ["Blue", "Green"],
        ]

    async def test_every_other_change_goes_in_the_same_patch(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, 0, ["Red"])
        write = _writes(graph, 0)

        _ = await _changed(
            client,
            MarkChange(
                is_read=True, flag_status="complete", importance="low", add_categories=("Blue",)
            ),
        )

        assert write.call_count == 1
        assert _sent(write) == {
            "@odata.type": "#microsoft.graph.message",
            "isRead": True,
            "flag": {"flagStatus": "complete"},
            "importance": "low",
            "categories": ["Red", "Blue"],
        }

    async def test_a_failed_read_fails_that_row_and_writes_nothing_to_that_message(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATHS[0]).mock(
            return_value=httpx.Response(404, headers={"request-id": _REQUEST_ID}, json=_NOT_FOUND)
        )
        refused = _writes(graph, 0)
        _ = _reads(graph, 1, [])
        _ = _writes(graph, 1)

        answer = await _changed(client, MarkChange(add_categories=("Green",)), refs=2)

        assert refused.call_count == 0
        assert [row.changed for row in answer.messages] == [False, True]
        failure = answer.messages[0].failure
        assert failure is not None
        assert "ErrorItemNotFound" in failure
        assert _REQUEST_ID in failure

    async def test_a_failed_write_after_the_read_fails_that_row(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, 0, ["Red"])
        _ = _refuses(graph, 0, 403)
        _ = _reads(graph, 1, [])
        _ = _writes(graph, 1)

        answer = await _changed(client, MarkChange(add_categories=("Green",)), refs=2)

        assert [row.changed for row in answer.messages] == [False, True]
        assert answer.messages[0].categories is None

    async def test_a_read_refused_on_every_message_raises_instead_of_answering(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.route(method="GET").mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        write = _every_write(graph)

        with pytest.raises(GraphNotFound):
            _ = await _changed(client, MarkChange(add_categories=("Green",)), refs=2)

        assert write.call_count == 0

    async def test_the_categories_reported_are_the_ones_microsoft_answered_with(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, 0, [])
        _ = _writes(graph, 0, categories=["Purple"])

        answer = await _changed(client, MarkChange(add_categories=("Green",)))

        assert answer.messages[0].categories == ["Purple"]

    async def test_a_mailbox_reads_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        path = f"/users/{_MAILBOX}/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"
        read = graph.get(path).mock(
            return_value=httpx.Response(200, json={"id": _IDS[0], "categories": ["Red"]})
        )
        write = graph.patch(path).mock(return_value=httpx.Response(200, json=_updated()))

        _ = await _changed(
            client, MarkChange(add_categories=("Blue",)), mailbox=_MAILBOX, confirm=_agrees
        )

        assert read.call_count == 1
        assert _sent(write)["categories"] == ["Red", "Blue"]


class TestAWriteIsNotRetried:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_patch_microsoft_answered_503_to_is_sent_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.patch(_PATHS[0]).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _marked(client, is_read=True)

        assert route.call_count == 1
        assert GraphSettings().max_retries > 0, "no retries are configured, so this proves nothing"


class TestWhatItRefusesBeforeWritingAnything:
    async def test_a_call_that_changes_nothing_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _every_write(graph)

        with pytest.raises(ToolError):
            _ = await mark_mail(
                client, message_refs=_REFS[:1], change=MarkChange(), confirm=_never_asked
            )

        assert route.call_count == 0

    @pytest.mark.parametrize(
        ("change", "named"),
        [
            pytest.param(
                MarkChange(add_categories=(), remove_categories=()), "`is_read`", id="none"
            ),
            pytest.param(
                MarkChange(flagged=True, flag_status="complete"), "`flag_status`", id="two-forms"
            ),
            pytest.param(MarkChange(flag_due_at=_DUE), "`flag_starts_at`", id="due-alone"),
            pytest.param(MarkChange(flag_starts_at=_START), "`flag_time_zone`", id="no-zone"),
            pytest.param(
                MarkChange(flag_starts_at=_START, flag_due_at=_DUE),
                "`flag_time_zone`",
                id="dates-with-no-zone",
            ),
            pytest.param(MarkChange(flag_time_zone=_ZONE), "`flag_starts_at`", id="zone-alone"),
            pytest.param(
                MarkChange(flag_starts_at=_DUE, flag_due_at=_START, flag_time_zone=_ZONE),
                "`flag_due_at`",
                id="due-before-start",
            ),
            pytest.param(
                MarkChange(flagged=False, flag_starts_at=_START, flag_time_zone=_ZONE),
                "`flag_status`",
                id="dates-with-flag-cleared",
            ),
            pytest.param(
                MarkChange(flag_status="complete", flag_starts_at=_START, flag_time_zone=_ZONE),
                "`flag_status`",
                id="dates-with-complete",
            ),
            pytest.param(
                MarkChange(flag_status="notFlagged", flag_starts_at=_START, flag_time_zone=_ZONE),
                "`flag_status`",
                id="dates-with-not-flagged",
            ),
            pytest.param(
                MarkChange(flag_starts_at="tomorrow at 9", flag_time_zone=_ZONE),
                "'tomorrow at 9' in `flag_starts_at`",
                id="start-not-a-time",
            ),
            pytest.param(
                MarkChange(flag_starts_at="2026-03-02T09:00Z", flag_time_zone=_ZONE),
                "`flag_starts_at`",
                id="start-with-an-offset",
            ),
            pytest.param(
                MarkChange(flag_starts_at=_START, flag_due_at="2026-03-06", flag_time_zone=_ZONE),
                "'2026-03-06' in `flag_due_at`",
                id="due-with-no-time",
            ),
            pytest.param(
                MarkChange(add_categories=("Red", "Blue"), remove_categories=("BLUE",)),
                "'Blue' is in both `add_categories` and `remove_categories`",
                id="category-in-both-lists",
            ),
        ],
    )
    async def test_a_refused_change_says_what_to_change_and_asks_nobody_and_writes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, change: MarkChange, named: str
    ) -> None:
        route = graph.route().mock(return_value=httpx.Response(200, json=_updated()))

        with pytest.raises(ToolError) as refused:
            _ = await mark_mail(
                client,
                message_refs=_REFS[:1],
                change=change,
                confirm=_never_asked,
                mailbox=_MAILBOX,
            )

        assert route.call_count == 0
        assert named in str(refused.value)
        assert _NOT_CHANGED in str(refused.value)

    @pytest.mark.parametrize(
        "change",
        [
            pytest.param(MarkChange(flagged=True, flag_status="complete"), id="two-forms"),
            pytest.param(
                MarkChange(flag_starts_at="tomorrow at 9", flag_time_zone=_ZONE),
                id="start-not-a-time",
            ),
            pytest.param(
                MarkChange(add_categories=("Red",), remove_categories=("RED",)),
                id="category-in-both-lists",
            ),
        ],
    )
    async def test_a_value_refusal_ends_with_the_one_sentence_for_a_repeat_that_fails_again(
        self, client: GraphServiceClient, change: MarkChange
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await mark_mail(client, message_refs=_REFS[:1], change=change, confirm=_never_asked)

        assert str(refused.value).endswith(_RETRY_SENTENCE)
        assert "identically" not in str(refused.value)

    async def test_a_due_date_equal_to_the_start_date_is_accepted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _writes(graph, 0)

        _ = await _changed(
            client, MarkChange(flag_starts_at=_START, flag_due_at=_START, flag_time_zone=_ZONE)
        )

        assert route.call_count == 1

    @pytest.mark.parametrize(
        "not_a_message",
        [
            "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D",
            "outlook:///folders/AQMkADAwSYNTHETIC-folder",
            "outlook:///rules/SYNTHETIC-rule-0001",
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            "AAMkAGI2SYNTHETIC-immutable-0001=",
            "https://outlook.office365.invalid/owa/?ItemID=synthetic",
            "Invoice 4471",
        ],
    )
    async def test_one_bad_handle_refuses_the_whole_call_and_writes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, not_a_message: str
    ) -> None:
        route = _every_write(graph)

        with pytest.raises(ToolError):
            _ = await mark_mail(
                client,
                message_refs=[_REFS[0], not_a_message, _REFS[1]],
                change=MarkChange(is_read=True),
                confirm=_never_asked,
            )

        assert route.call_count == 0

    async def test_the_refusal_names_which_entries_were_not_handles(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _every_write(graph)

        with pytest.raises(ToolError) as refused:
            _ = await mark_mail(
                client,
                message_refs=[_REFS[0], "Invoice 4471", _REFS[1], "not a handle either"],
                change=MarkChange(is_read=True),
                confirm=_never_asked,
            )

        assert "2, 4" in str(refused.value)


class TestMailboxTargeting:
    async def test_no_mailbox_writes_the_signed_in_users_own_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _writes(graph, 0)

        _ = await _marked(client, is_read=True)

        assert route.called

    async def test_a_mailbox_writes_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.patch(f"/users/{_MAILBOX}/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D").mock(
            return_value=httpx.Response(200, json=_updated())
        )

        answer = await _marked(client, is_read=True, mailbox=_MAILBOX, confirm=_agrees)

        assert route.called
        assert answer.messages[0].changed is True


class TestThePersonBeforeAnotherMailboxChanges:
    async def test_the_own_mailbox_asks_nobody_and_writes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _every_write(graph)

        _ = await _marked(client, refs=3, is_read=True, confirm=_never_asked)

        assert route.call_count == 3

    async def test_a_delegated_mailbox_asks_once_for_the_whole_batch(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _every_write(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about
            return None

        _ = await _marked(client, refs=3, is_read=True, mailbox=_MAILBOX, confirm=capturing)

        assert len(asked) == 1
        assert route.call_count == 3
        assert all(path.startswith(f"/v1.0/users/{_MAILBOX}/messages/") for path in _paths(route))

    async def test_a_refusal_writes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _every_write(graph)

        with pytest.raises(ToolError, match=_NOT_CHANGED):
            _ = await _marked(client, refs=3, is_read=True, mailbox=_MAILBOX, confirm=_declines)

        assert route.call_count == 0

    async def test_the_question_names_the_mailbox_the_count_and_every_change(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _every_write(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about
            return None

        _ = await _marked(
            client,
            refs=3,
            is_read=True,
            flagged=True,
            importance="high",
            mailbox=_MAILBOX,
            confirm=capturing,
        )

        assert f"Change 3 messages in the mailbox '{_MAILBOX}'?" in asked[0]
        assert (
            "mark them as read, flag them for follow-up and set their importance to high"
            in (asked[0])
        )
        assert "belongs to someone else" in asked[0]

    @pytest.mark.parametrize(
        ("refs", "is_read", "flagged", "importance", "spoken"),
        [
            (1, False, None, None, "Change 1 message in the mailbox"),
            (2, False, False, None, "mark them as unread and clear their follow-up flag"),
            (2, None, None, "low", "This tool will set their importance to low."),
        ],
    )
    async def test_the_question_speaks_of_the_change_that_was_asked_for(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        refs: int,
        is_read: bool | None,
        flagged: bool | None,
        importance: MailImportance | None,
        spoken: str,
    ) -> None:
        _ = _every_write(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about
            return None

        _ = await _marked(
            client,
            refs=refs,
            is_read=is_read,
            flagged=flagged,
            importance=importance,
            mailbox=_MAILBOX,
            confirm=capturing,
        )

        assert spoken in asked[0]

    @pytest.mark.parametrize(
        ("change", "spoken"),
        [
            pytest.param(
                MarkChange(flag_status="complete"),
                "This tool will mark their follow-up complete.",
                id="complete",
            ),
            pytest.param(
                MarkChange(flag_status="notFlagged"),
                "This tool will clear their follow-up flag.",
                id="not-flagged",
            ),
            pytest.param(
                _DATED,
                f"This tool will flag them for follow-up from {_START} to {_DUE} in {_ZONE}.",
                id="start-and-due",
            ),
            pytest.param(
                MarkChange(flag_starts_at=_START, flag_time_zone=_ZONE),
                f"This tool will flag them for follow-up from {_START} in {_ZONE}.",
                id="start-alone",
            ),
            pytest.param(
                MarkChange(add_categories=("Red", "Blue")),
                "This tool will add the categories 'Red, Blue'.",
                id="add",
            ),
            pytest.param(
                MarkChange(is_read=True, add_categories=("Red",), remove_categories=("Blue",)),
                "mark them as read, add the category 'Red' and remove the category 'Blue'.",
                id="read-add-and-remove",
            ),
        ],
    )
    @pytest.mark.usefixtures("graph")
    async def test_the_question_speaks_of_the_flag_and_the_categories(
        self, client: GraphServiceClient, change: MarkChange, spoken: str
    ) -> None:
        question, _ = await _asked(client, change)

        assert spoken in question

    @pytest.mark.usefixtures("graph")
    async def test_every_kind_of_change_binds_an_agreement_of_its_own(
        self, client: GraphServiceClient
    ) -> None:
        changes = (
            MarkChange(flagged=True),
            MarkChange(flag_status="flagged"),
            MarkChange(flag_status="complete"),
            MarkChange(flag_starts_at=_START, flag_time_zone=_ZONE),
            MarkChange(flag_starts_at=_START, flag_time_zone="UTC"),
            MarkChange(flag_starts_at=_DUE, flag_time_zone=_ZONE),
            _DATED,
            MarkChange(add_categories=("Red",)),
            MarkChange(add_categories=("Red", "Blue")),
            MarkChange(remove_categories=("Red",)),
        )

        bound = [(await _asked(client, change))[1] for change in changes]

        assert len(set(bound)) == len(changes)

    async def test_a_very_long_mailbox_is_cut_in_the_question(
        self, client: GraphServiceClient
    ) -> None:
        long_mailbox = "a" * 300 + "@example.invalid"
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about
            return _NOT_CHANGED

        with pytest.raises(ToolError):
            _ = await _marked(client, is_read=True, mailbox=long_mailbox, confirm=capturing)

        assert long_mailbox not in asked[0]
        assert "…" in asked[0]

    async def test_a_different_mailbox_message_or_change_binds_a_different_agreement(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _every_write(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert question
            bound.append(about)
            return None

        for mailbox, refs, is_read in (
            (_MAILBOX, 2, True),
            ("sam@example.invalid", 2, True),
            (_MAILBOX, 1, True),
            (_MAILBOX, 2, False),
        ):
            _ = await _marked(
                client, refs=refs, is_read=is_read, mailbox=mailbox, confirm=capturing
            )

        assert len(set(bound)) == 4

    async def test_the_same_request_binds_the_same_agreement(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _every_write(graph)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert question
            bound.append(about)
            return None

        for _ in range(2):
            _ = await _marked(client, refs=2, is_read=True, mailbox=_MAILBOX, confirm=capturing)

        assert bound[0] == bound[1]


class TestHowItDeclaresItself:
    async def test_it_says_it_writes_that_the_write_can_destroy_and_that_a_repeat_is_safe(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is True
        assert tool.annotations.idempotent_hint is True
        assert WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"] is True
        assert WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"] is True

    def test_it_asks_for_the_permission_that_can_write(self) -> None:
        assert GRAPH_PERMISSIONS == ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

    async def test_it_tells_a_caller_what_it_does_and_where(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        described = tool.description or ""
        assert "in the signed-in user's own mailbox" in described
        assert "flags them for follow-up" in described

    async def test_it_says_it_asks_before_it_changes_another_mailbox_and_not_its_own(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        described = tool.description or ""
        assert (
            "This tool asks the user to agree before it changes a shared or delegated mailbox. "
            "It changes the user's own mailbox without a question."
        ) in described

    async def test_it_names_the_tool_that_moves_mail_and_says_each_message_changes_alone(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        described = tool.description or ""
        assert "mark a follow-up complete, or give a flag a start date and a due date" in described
        assert "adds or removes their categories" in described
        assert "outlook_move_mail is the tool that moves messages to another folder." in described
        assert "This tool changes each message separately." in described

    async def test_the_category_arguments_name_the_tool_that_lists_the_names(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        arguments = _arguments(tool)
        described = str(arguments["add_categories"]["description"])
        assert LIST_CATEGORIES_GUARD in described
        assert "outlook_list_categories" not in described.replace(LIST_CATEGORIES_GUARD, "")
        assert arguments["add_categories"]["default"] == []
        assert arguments["remove_categories"]["default"] == []
        assert cast("list[str]", tool.parameters["required"]) == ["message_refs"]

    async def test_the_zone_is_held_to_the_zone_name_pattern(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert f'"pattern": "{ZONE_NAME}"' in json.dumps(_arguments(tool)["flag_time_zone"])

    @pytest.mark.parametrize("argument", ["flag_starts_at", "flag_due_at"])
    async def test_a_flag_date_is_a_plain_string_and_not_a_date_format(
        self, transport: httpx.AsyncClient, argument: str
    ) -> None:
        tool = await _registered(transport)

        assert '"format"' not in json.dumps(_arguments(tool)[argument])

    async def test_the_status_admits_exactly_the_three_that_microsoft_names(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        defined = cast("Mapping[str, Mapping[str, object]]", tool.parameters["$defs"])
        assert '"#/$defs/FlagStatus"' in json.dumps(_arguments(tool)["flag_status"])
        assert defined["FlagStatus"]["enum"] == ["flagged", "complete", "notFlagged"]

    async def test_the_confirmation_is_no_argument_of_the_published_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert "ctx" not in _arguments(tool)
        assert "confirm" not in _arguments(tool)
