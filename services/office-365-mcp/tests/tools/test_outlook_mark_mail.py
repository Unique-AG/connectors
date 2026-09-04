"""Every response body here is synthesised. No mailbox was written to.

The four rules that make a write tool safe are what this file is about: the batch is bounded, every
message is its own request and its own row, what is reported comes off Microsoft's answer rather
than off the arguments, and no retry turns one row into several.
"""

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

from office_365_mcp.graph_client import GraphSettings
from office_365_mcp.shared import identity
from office_365_mcp.shared.handles import MailMessageHandle
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE
from office_365_mcp.tools.outlook_mark_mail import (
    CHANGES,
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

# Spelled by the one module allowed to spell them, so a change to the grammar reaches this file.
_REFS: tuple[str, ...] = tuple(MailMessageHandle(message_id).uri for message_id in _IDS)

# The SDK re-encodes each id for the URL, so this is what the decoded handle comes back as.
_PATHS: tuple[str, ...] = tuple(
    f"/me/messages/AAMkAGI2SYNTHETIC-immutable-000{number}%3D" for number in (1, 2, 3)
)

_NOT_FOUND: dict[str, object] = {
    "error": {"code": "ErrorItemNotFound", "message": "The specified object was not found."}
}

_DRAFT_ONLY: tuple[str, ...] = ("subject", "body", "toRecipients", "ccRecipients")


def _updated(
    *,
    message_id: str = _IDS[0],
    is_read: bool | None = True,
    flag_status: str | None = "notFlagged",
    importance: str | None = "normal",
) -> dict[str, object]:
    """What Graph answers a message PATCH with: the message as it now stands."""
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
    """One route for one message, so a test can tell which of them was written."""
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


def _every_write(graph: respx.MockRouter) -> respx.Route:
    """A catch-all for the tests that care how many writes happened, not which."""
    return graph.route(method="PATCH").mock(return_value=httpx.Response(200, json=_updated()))


def _sent(route: respx.Route) -> Mapping[str, object]:
    """The JSON this tool actually put on the wire for the last write on `route`."""
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _arguments(tool: Tool) -> Mapping[str, Mapping[str, object]]:
    return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])


def _constraint(tool: Tool, keyword: str) -> object:
    return cast("Mapping[str, object]", tool.parameters)[keyword]


async def _registered(transport: httpx.AsyncClient) -> Tool:
    """The tool as `register` declares it, schema patch and all."""
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
        """The point of the cap is that one call cannot touch a whole mailbox, so it has to be
        refused before the first write and not after the twentieth."""
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
        """The assertion in the worker is the backstop; this is what stops a client sending five
        hundred handles in the first place."""
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
        """The failure this tool exists to make visible: nineteen writes and one 404 is neither
        'it worked' nor 'it failed'."""
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
        _ = graph.patch(_PATHS[0]).mock(
            return_value=httpx.Response(
                404, headers={"request-id": "synthetic-request-id"}, json=_NOT_FOUND
            )
        )

        answer = await _marked(client, is_read=True)

        row = answer.messages[0]
        assert row.changed is False
        assert row.failure is not None
        assert "404" in row.failure
        assert "synthetic-request-id" in row.failure

    async def test_a_refused_row_reports_no_state_it_could_not_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.patch(_PATHS[0]).mock(return_value=httpx.Response(404, json=_NOT_FOUND))

        answer = await _marked(client, is_read=True, flagged=True, importance="high")

        row = answer.messages[0]
        assert (row.is_read, row.flag_status, row.importance) == (None, None, None)


class TestItEchoesGraphAndNotItsArguments:
    async def test_the_read_state_reported_is_the_one_microsoft_answered_with(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A tool echoing its own arguments cannot tell a caller that a write did nothing."""
        _ = _writes(graph, 0, is_read=False)

        answer = await _marked(client, is_read=True)

        assert answer.messages[0].changed is True
        assert answer.messages[0].is_read is False

    async def test_the_flag_status_reported_is_the_one_microsoft_answered_with(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`complete` is neither of the two values `flagged` takes, which is why the status is
        reported as Microsoft's own three-valued property."""
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
        """An unset property is absent from the payload, so a PATCH cannot null the rest of the
        message on its way past."""
        route = _writes(graph, 0)

        _ = await _marked(client, is_read=True)

        assert _sent(route) == {"@odata.type": "#microsoft.graph.message", "isRead": True}

    @pytest.mark.parametrize("draft_only", _DRAFT_ONLY)
    async def test_no_draft_only_property_is_ever_in_the_payload(
        self, client: GraphServiceClient, graph: respx.MockRouter, draft_only: str
    ) -> None:
        """Microsoft makes these writable only while `isDraft` is true, and a PATCH of one against
        a sent message is documented nowhere."""
        route = _writes(graph, 0)

        _ = await _marked(client, is_read=True, flagged=True, importance="high")

        assert draft_only not in _sent(route)

    @pytest.mark.parametrize("draft_only", _DRAFT_ONLY)
    async def test_no_draft_only_property_is_addressable_in_the_schema_either(
        self, transport: httpx.AsyncClient, draft_only: str
    ) -> None:
        """Their absence from the signature is the control: nothing downstream filters them out,
        because nothing upstream can name them."""
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
        """Without the preference Graph reads the handle's immutable id as a `RestId` and answers
        404, so every row of a perfectly good batch would fail."""
        routes = [_writes(graph, index) for index in range(3)]

        _ = await _marked(client, refs=3, is_read=True)

        for route in routes:
            assert 'IdType="ImmutableId"' in route.calls.last.request.headers["prefer"]

    async def test_the_preference_is_not_added_to_every_other_graph_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """kiota's `RequestConfiguration.headers` defaults to one `HeadersCollection` shared by
        every configuration in the process, so a header added to the default leaks everywhere."""
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
        """The middleware default is what makes this worth asserting: without `no_retry` the SDK
        sends this `GraphSettings().max_retries` more times, and the row's one line would stand for
        an unknown number of attempts."""
        route = graph.patch(_PATHS[0]).mock(return_value=httpx.Response(503))

        answer = await _marked(client, is_read=True)

        assert route.call_count == 1
        assert GraphSettings().max_retries > 0, "no retries are configured, so this proves nothing"
        assert answer.messages[0].changed is False


class TestWhatItRefusesBeforeWritingAnything:
    async def test_a_call_that_changes_nothing_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """An empty update would be written to every message named and reported as a change."""
        route = _every_write(graph)

        with pytest.raises(ToolError):
            _ = await mark_mail(client, message_refs=_REFS[:1], change=MarkChange())

        assert route.call_count == 0

    async def test_the_schema_asks_for_at_least_one_of_the_three(
        self, transport: httpx.AsyncClient
    ) -> None:
        """FastMCP validates against the signature rather than against this, which is why the
        runtime refusal above exists as well."""
        tool = await _registered(transport)

        assert _constraint(tool, "anyOf") == [{"required": [name]} for name in CHANGES]
        assert set(CHANGES) == {"is_read", "flagged", "importance"}

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
        """Dropping the bad entries and writing the rest would leave a call that half happened and
        reported neither half."""
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


class TestHowItDeclaresItself:
    async def test_it_says_it_writes_and_that_the_write_can_destroy(
        self, transport: httpx.AsyncClient
    ) -> None:
        """Clearing a follow-up flag drops the start, due and completed dates this tool never read,
        so `destructiveHint: false` — MCP's "performs only additive updates" — would be untrue."""
        tool = await _registered(transport)

        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is True
        assert WRITE_DESTRUCTIVE["destructiveHint"] is True

    def test_it_asks_for_the_permission_that_can_write(self) -> None:
        assert GRAPH_PERMISSIONS == ("Mail.ReadWrite",)

    async def test_it_tells_a_caller_the_mailbox_changes_and_that_nothing_here_undoes_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        described = tool.description or ""
        assert "CHANGES THE MAILBOX" in described
        assert "cannot undo it" in described
        assert "Outlook" in described
