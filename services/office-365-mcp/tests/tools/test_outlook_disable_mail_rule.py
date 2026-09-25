import json
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphFailure, GraphSettings
from office_365_mcp.shared.handles import MailRuleHandle
from office_365_mcp.shared.seam import WRITE_IDEMPOTENT
from office_365_mcp.tools.outlook_disable_mail_rule import (
    GRAPH_PERMISSIONS,
    TOOL_NAME,
    disable_mail_rule,
    register,
)

_RULE_ID = "AQAAAJ5dZqSYNTHETIC="

_RULE_REF = MailRuleHandle(_RULE_ID).uri

_RULE_PATH = "/me/mailFolders/inbox/messageRules/AQAAAJ5dZqSYNTHETIC%3D"

_OUTSIDE = "collector@elsewhere.invalid"
_ARCHIVE_FOLDER_ID = "AQMkADAwSYNTHETIC-archive"

_UNWRITABLE: tuple[str, ...] = ("actions", "conditions", "exceptions", "displayName", "sequence")


def _recipient(address: str | None, *, name: str | None = None) -> dict[str, object]:
    return {"emailAddress": {"address": address, "name": name}}


def _forwarding_actions() -> dict[str, object]:
    return {
        "forwardTo": [_recipient(_OUTSIDE, name="Partner Archive")],
        "stopProcessingRules": True,
    }


def _rule(
    *,
    display_name: str | None = "Newsletters",
    is_enabled: bool | None = True,
    is_read_only: bool | None = False,
    actions: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": _RULE_ID,
        "displayName": display_name,
        "isEnabled": is_enabled,
        "isReadOnly": is_read_only,
    }
    if actions is not None:
        payload["actions"] = actions
    return payload


@pytest.fixture
def reads(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_RULE_PATH).mock(
        return_value=httpx.Response(200, json=_rule(actions=_forwarding_actions()))
    )


@pytest.fixture
def writes(graph: respx.MockRouter) -> respx.Route:
    return graph.patch(_RULE_PATH).mock(
        return_value=httpx.Response(
            200, json=_rule(is_enabled=False, actions=_forwarding_actions())
        )
    )


def _sent(route: respx.Route) -> Mapping[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _arguments(tool: Tool) -> Mapping[str, Mapping[str, object]]:
    return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP[None] = FastMCP("Disable Mail Rule Under Test")
    register(mcp, transport)
    tool = await mcp.get_tool(TOOL_NAME)
    assert tool is not None, f"register declared no {TOOL_NAME}"
    return tool


class TestWhatCannotBeAskedForAtAll:
    async def test_the_schema_admits_no_way_to_switch_a_rule_on(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert _arguments(tool)["enabled"]["const"] is False

    @pytest.mark.parametrize("unwritable", _UNWRITABLE)
    async def test_nothing_a_rule_does_can_be_named_in_a_call(
        self, transport: httpx.AsyncClient, unwritable: str
    ) -> None:
        tool = await _registered(transport)

        assert unwritable not in _arguments(tool)

    @pytest.mark.usefixtures("reads")
    async def test_the_only_property_on_the_wire_is_the_one_being_turned_off(
        self, client: GraphServiceClient, writes: respx.Route
    ) -> None:
        _ = await disable_mail_rule(client, rule_ref=_RULE_REF)

        assert _sent(writes) == {"isEnabled": False}


class TestItRecordsWhatItTurnedOff:
    async def test_it_reads_the_rule_before_it_writes_to_it(
        self, client: GraphServiceClient, reads: respx.Route, writes: respx.Route
    ) -> None:
        _ = await disable_mail_rule(client, rule_ref=_RULE_REF)

        assert reads.call_count == 1
        assert writes.call_count == 1

    @pytest.mark.usefixtures("reads", "writes")
    async def test_the_answer_names_the_outside_address_the_rule_was_forwarding_to(
        self, client: GraphServiceClient
    ) -> None:
        answer = await disable_mail_rule(client, rule_ref=_RULE_REF)

        assert answer.forwarded_to == [_OUTSIDE]
        assert answer.display_name == "Newsletters"
        assert answer.uri == _RULE_REF

    @pytest.mark.usefixtures("writes")
    async def test_the_answer_names_the_redirect_attachment_move_and_delete_actions(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_RULE_PATH).mock(
            return_value=httpx.Response(
                200,
                json=_rule(
                    actions={
                        "redirectTo": [_recipient("deputy@example.invalid")],
                        "forwardAsAttachmentTo": [_recipient(_OUTSIDE)],
                        "moveToFolder": _ARCHIVE_FOLDER_ID,
                        "permanentDelete": True,
                    }
                ),
            )
        )

        answer = await disable_mail_rule(client, rule_ref=_RULE_REF)

        assert answer.redirected_to == ["deputy@example.invalid"]
        assert answer.forwarded_as_attachment_to == [_OUTSIDE]
        assert answer.moved_to_folder == _ARCHIVE_FOLDER_ID
        assert answer.deleted is True

    @pytest.mark.usefixtures("writes")
    async def test_a_recipient_microsoft_recorded_no_address_for_is_named_rather_than_dropped(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_RULE_PATH).mock(
            return_value=httpx.Response(
                200,
                json=_rule(actions={"forwardTo": [_recipient(None, name="Partner Archive")]}),
            )
        )

        answer = await disable_mail_rule(client, rule_ref=_RULE_REF)

        assert answer.forwarded_to == ["Partner Archive"]

    @pytest.mark.usefixtures("writes")
    async def test_a_rule_with_no_actions_reports_none_rather_than_inventing_them(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_RULE_PATH).mock(return_value=httpx.Response(200, json=_rule()))

        answer = await disable_mail_rule(client, rule_ref=_RULE_REF)

        assert answer.forwarded_to == []
        assert answer.redirected_to == []
        assert answer.moved_to_folder is None
        assert answer.deleted is None

    @pytest.mark.usefixtures("writes")
    async def test_a_rule_that_was_already_off_says_so(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_RULE_PATH).mock(
            return_value=httpx.Response(
                200, json=_rule(is_enabled=False, actions=_forwarding_actions())
            )
        )

        answer = await disable_mail_rule(client, rule_ref=_RULE_REF)

        assert answer.was_enabled is False

    @pytest.mark.usefixtures("writes")
    async def test_it_asks_microsoft_for_the_actions_it_reports(
        self, client: GraphServiceClient, reads: respx.Route
    ) -> None:
        _ = await disable_mail_rule(client, rule_ref=_RULE_REF)

        selected = reads.calls.last.request.url.params["$select"]
        assert "actions" in selected
        assert "isReadOnly" in selected


class TestItAnswersWithMicrosoftsOwnWord:
    @pytest.mark.usefixtures("reads")
    async def test_a_rule_microsoft_still_reports_as_running_is_the_answer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.patch(_RULE_PATH).mock(
            return_value=httpx.Response(200, json=_rule(is_enabled=True))
        )

        answer = await disable_mail_rule(client, rule_ref=_RULE_REF)

        assert answer.is_enabled is True

    @pytest.mark.usefixtures("reads")
    async def test_a_write_microsoft_returned_no_rule_for_reports_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.patch(_RULE_PATH).mock(return_value=httpx.Response(204))

        answer = await disable_mail_rule(client, rule_ref=_RULE_REF)

        assert answer.is_enabled is None
        assert answer.was_enabled is True


class TestWhatItRefusesBeforeWritingAnything:
    async def test_a_read_only_rule_is_refused_and_never_written_to(
        self, client: GraphServiceClient, graph: respx.MockRouter, writes: respx.Route
    ) -> None:
        _ = graph.get(_RULE_PATH).mock(
            return_value=httpx.Response(
                200, json=_rule(is_read_only=True, actions=_forwarding_actions())
            )
        )

        with pytest.raises(ToolError) as refused:
            _ = await disable_mail_rule(client, rule_ref=_RULE_REF)

        assert writes.call_count == 0
        assert "read-only" in str(refused.value)
        assert "Outlook" in str(refused.value)

    @pytest.mark.parametrize(
        "not_a_rule",
        [
            "outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D",
            "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D",
            "outlook:///folders/AQMkADAwSYNTHETIC-folder",
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            "outlook:///rules/",
            "AQAAAJ5dZqSYNTHETIC=",
            "Newsletters",
        ],
    )
    async def test_a_ref_that_is_not_a_rule_handle_never_reaches_graph(
        self,
        client: GraphServiceClient,
        reads: respx.Route,
        writes: respx.Route,
        not_a_rule: str,
    ) -> None:
        with pytest.raises(ToolError):
            _ = await disable_mail_rule(client, rule_ref=not_a_rule)

        assert reads.call_count == 0
        assert writes.call_count == 0

    async def test_the_refusal_says_where_a_rule_handle_comes_from(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await disable_mail_rule(client, rule_ref="Newsletters")

        assert "outlook_get_mailbox_settings" in str(refused.value)


class TestTheWriteIsNotRetried:
    @pytest.mark.usefixtures("retry_sleeps")
    @pytest.mark.usefixtures("reads")
    async def test_a_patch_microsoft_answered_503_to_is_sent_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.patch(_RULE_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphFailure):
            _ = await disable_mail_rule(client, rule_ref=_RULE_REF)

        assert route.call_count == 1
        assert GraphSettings().max_retries > 0, "no retries are configured, so this proves nothing"


class TestHowItDeclaresItself:
    async def test_it_says_it_writes_and_that_writing_the_same_thing_twice_is_safe(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert WRITE_IDEMPOTENT["idempotentHint"] is True

    def test_it_asks_for_the_permission_that_can_write_mailbox_settings(self) -> None:
        assert GRAPH_PERMISSIONS == ("MailboxSettings.ReadWrite",)

    async def test_it_names_the_tool_a_rule_handle_comes_from(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert "outlook_get_mailbox_settings reports" in (tool.description or "")

    async def test_it_says_re_enabling_is_a_click_in_outlook_and_not_offered_here(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        described = tool.description or ""
        assert "cannot enable a rule" in described
        assert "clicks once in Outlook" in described
