import json
from collections.abc import AsyncIterator, Mapping
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
from mcp.types import TextContent
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig
from office_365_mcp.graph_client import (
    GraphForbidden,
    GraphNotFound,
    GraphSettings,
    GraphUnavailable,
)
from office_365_mcp.shared import identity
from office_365_mcp.shared.handles import MailMessageHandle
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT
from office_365_mcp.tools.outlook_mark_mail import (
    GRAPH_PERMISSIONS,
    MAX_MESSAGES,
    TOOL_NAME,
    MailImportance,
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
) -> dict[str, object]:
    return {
        "id": message_id,
        "isRead": is_read,
        "importance": importance,
        "flag": None if flag_status is None else {"flagStatus": flag_status},
    }


def _writes(
    graph: respx.MockRouter,
    index: int = 0,
    *,
    is_read: bool | None = True,
    flag_status: str | None = "notFlagged",
    importance: str | None = "normal",
) -> respx.Route:
    return graph.patch(_PATHS[index]).mock(
        return_value=httpx.Response(
            200,
            json=_updated(
                message_id=_IDS[index],
                is_read=is_read,
                flag_status=flag_status,
                importance=importance,
            ),
        )
    )


def _refuses(graph: respx.MockRouter, index: int, status: int) -> respx.Route:
    body = _ACCESS_DENIED if status == 403 else _NOT_FOUND
    return graph.patch(_PATHS[index]).mock(
        return_value=httpx.Response(status, headers={"request-id": _REQUEST_ID}, json=body)
    )


def _every_write(graph: respx.MockRouter) -> respx.Route:
    return graph.route(method="PATCH").mock(return_value=httpx.Response(200, json=_updated()))


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


async def _marked(
    client: GraphServiceClient,
    *,
    refs: int = 1,
    is_read: bool | None = None,
    flagged: bool | None = None,
    importance: MailImportance | None = None,
) -> MarkedMail:
    return await mark_mail(
        client,
        message_refs=_REFS[:refs],
        change=MarkChange(is_read=is_read, flagged=flagged, importance=importance),
    )


class TestTheBulkCap:
    async def test_a_batch_over_the_cap_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _every_write(graph)
        too_many = [MailMessageHandle(f"SYNTHETIC-{number}").uri for number in range(21)]

        with pytest.raises(AssertionError):
            _ = await mark_mail(client, message_refs=too_many, change=MarkChange(is_read=True))

        assert route.call_count == 0

    async def test_a_batch_of_nothing_is_refused_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _every_write(graph)

        with pytest.raises(AssertionError):
            _ = await mark_mail(client, message_refs=[], change=MarkChange(is_read=True))

        assert route.call_count == 0

    async def test_a_batch_exactly_at_the_cap_is_written(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _every_write(graph)
        full = [MailMessageHandle(f"SYNTHETIC-{number}").uri for number in range(MAX_MESSAGES)]

        answer = await mark_mail(client, message_refs=full, change=MarkChange(is_read=True))

        assert route.call_count == MAX_MESSAGES
        assert len(answer.messages) == MAX_MESSAGES

    async def test_the_schema_publishes_the_cap_a_client_is_held_to(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        refs = _arguments(tool)["message_refs"]
        assert refs["maxItems"] == MAX_MESSAGES
        assert refs["minItems"] == 1


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
            _ = await mark_mail(client, message_refs=_REFS[:1], change=MarkChange())

        assert route.call_count == 0

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
            )

        assert "2, 4" in str(refused.value)


class TestMailboxTargeting:
    async def test_no_mailbox_writes_the_signed_in_users_own_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _writes(graph, 0)

        _ = await mark_mail(client, message_refs=_REFS[:1], change=MarkChange(is_read=True))

        assert route.called

    async def test_a_mailbox_writes_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.patch(
            "/users/alex@example.invalid/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"
        ).mock(return_value=httpx.Response(200, json=_updated()))

        answer = await mark_mail(
            client,
            message_refs=_REFS[:1],
            change=MarkChange(is_read=True),
            mailbox="alex@example.invalid",
        )

        assert route.called
        assert answer.messages[0].changed is True


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
