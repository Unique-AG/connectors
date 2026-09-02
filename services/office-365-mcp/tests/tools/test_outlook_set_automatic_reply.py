"""`outlook_set_automatic_reply`: what it refuses, what whole object it sends, and whose answer it
reports.

Every response body here is synthesised. No mailbox was written to. The converted window in
`TestItAnswersWithWhatMicrosoftStored` is Microsoft's own worked example — a start sent as
`18:00:00` in UTC and returned as `02:00:00` in UTC — because a tool that echoed its arguments
would pass every other test in this file.
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

from office_365_mcp.graph_client import GraphFailure, GraphSettings
from office_365_mcp.shared.seam import WRITE_IDEMPOTENT
from office_365_mcp.tools.outlook_set_automatic_reply import (
    GRAPH_PERMISSIONS,
    TOOL_NAME,
    AutomaticReplyReport,
    ExternalAudience,
    ReplyChange,
    register,
    set_automatic_reply,
)

_SETTINGS = "/me/mailboxSettings"

# What the mailbox already holds in most of these tests: an audience and two messages nobody in the
# call under test names, which is exactly what a merge could lose.
_STORED_INTERNAL = "<p>Back on the 14th.</p>"
_STORED_EXTERNAL = "<p>Away until the 14th. Reach Grace at grace@example.invalid.</p>"


def _setting(
    *,
    status: str | None = "disabled",
    external_audience: str | None = "all",
    internal: str | None = _STORED_INTERNAL,
    external: str | None = _STORED_EXTERNAL,
    start: str | None = "2026-03-20T18:00:00.0000000",
    end: str | None = "2026-03-28T18:00:00.0000000",
    time_zone: str = "UTC",
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if status is not None:
        payload["status"] = status
    if external_audience is not None:
        payload["externalAudience"] = external_audience
    if internal is not None:
        payload["internalReplyMessage"] = internal
    if external is not None:
        payload["externalReplyMessage"] = external
    if start is not None:
        payload["scheduledStartDateTime"] = {"dateTime": start, "timeZone": time_zone}
    if end is not None:
        payload["scheduledEndDateTime"] = {"dateTime": end, "timeZone": time_zone}
    return payload


def _settings_response(reply: dict[str, object] | None) -> httpx.Response:
    """`reply=None` is a mailbox Microsoft answered with no `automaticRepliesSetting` on it."""
    body: dict[str, object] = {} if reply is None else {"automaticRepliesSetting": reply}
    return httpx.Response(200, json=body)


@pytest.fixture
def reads(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_SETTINGS).mock(return_value=_settings_response(_setting()))


@pytest.fixture
def writes(graph: respx.MockRouter) -> respx.Route:
    return graph.patch(_SETTINGS).mock(return_value=_settings_response(_setting()))


def _sent(route: respx.Route) -> Mapping[str, object]:
    """The `automaticRepliesSetting` this tool actually put on the wire."""
    body = cast("dict[str, object]", json.loads(route.calls.last.request.content))
    return cast("Mapping[str, object]", body["automaticRepliesSetting"])


def _status_values(tool: Tool) -> list[str]:
    """The values a client may send as `status`, followed through the `$ref` pydantic emits for a
    named Literal alias."""
    schemas = cast("Mapping[str, Mapping[str, object]]", tool.parameters["$defs"])
    named = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])["status"]
    definition = cast("str", named["$ref"]).removeprefix("#/$defs/")
    return cast("list[str]", schemas[definition]["enum"])


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP[None] = FastMCP("Automatic Reply Under Test")
    register(mcp, transport)
    tool = await mcp.get_tool(TOOL_NAME)
    assert tool is not None, f"register declared no {TOOL_NAME}"
    return tool


async def _scheduled(
    client: GraphServiceClient,
    *,
    start: str | None = "2026-09-01T08:00:00",
    end: str | None = "2026-09-14T18:00:00",
    time_zone: str = "UTC",
    internal_message: str | None = None,
    external_message: str | None = None,
    external_audience: ExternalAudience | None = None,
) -> AutomaticReplyReport:
    return await set_automatic_reply(
        client,
        change=ReplyChange(
            status="scheduled",
            start=start,
            end=end,
            time_zone=time_zone,
            internal_message=internal_message,
            external_message=external_message,
            external_audience=external_audience,
        ),
    )


class TestTheReplyItWillNotSet:
    @pytest.mark.parametrize(
        ("start", "end"),
        [(None, "2026-09-14T18:00:00"), ("2026-09-01T08:00:00", None), (None, None)],
    )
    async def test_scheduling_without_both_ends_of_the_window_never_reaches_graph(
        self,
        client: GraphServiceClient,
        reads: respx.Route,
        writes: respx.Route,
        start: str | None,
        end: str | None,
    ) -> None:
        """An open-ended reply is what this refusal is really about, so it has to happen before the
        mailbox is touched rather than after the read."""
        with pytest.raises(ToolError):
            _ = await _scheduled(client, start=start, end=end)

        assert reads.call_count == 0
        assert writes.call_count == 0

    async def test_the_refusal_says_the_open_ended_reply_is_absent_and_not_merely_refused(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _scheduled(client, end=None)

        message = str(refused.value)
        assert "alwaysEnabled" in message
        assert "no end date" in message

    async def test_the_schema_offers_no_status_that_never_ends(
        self, transport: httpx.AsyncClient
    ) -> None:
        """The argument is the control. A caller cannot ask for an unbounded reply here at all,
        which is a stronger promise than refusing one at runtime."""
        tool = await _registered(transport)

        assert _status_values(tool) == ["scheduled", "disabled"]


class TestItSendsTheWholeSetting:
    async def test_it_reads_the_setting_before_it_writes_one(
        self, client: GraphServiceClient, reads: respx.Route, writes: respx.Route
    ) -> None:
        _ = await _scheduled(client)

        assert reads.call_count == 1
        assert writes.call_count == 1

    @pytest.mark.parametrize(
        ("property_name", "stored"),
        [
            ("externalAudience", "all"),
            ("internalReplyMessage", _STORED_INTERNAL),
            ("externalReplyMessage", _STORED_EXTERNAL),
        ],
    )
    @pytest.mark.usefixtures("reads")
    async def test_a_property_the_call_never_named_is_sent_from_the_mailbox_anyway(
        self,
        client: GraphServiceClient,
        writes: respx.Route,
        property_name: str,
        stored: str,
    ) -> None:
        """Microsoft's two PATCH pages demonstrate opposite merge semantics for a nested object —
        `user-update-mailboxsettings` keeps what was left out, `messagerule-update` drops it — so
        every property goes on the wire and the question never has to be answered."""
        _ = await _scheduled(client)

        assert _sent(writes)[property_name] == stored

    @pytest.mark.usefixtures("reads")
    async def test_an_argument_that_was_given_replaces_what_the_mailbox_held(
        self, client: GraphServiceClient, writes: respx.Route
    ) -> None:
        _ = await _scheduled(
            client, internal_message="Out until Monday.", external_audience="contactsOnly"
        )

        sent = _sent(writes)
        assert sent["internalReplyMessage"] == "Out until Monday."
        assert sent["externalAudience"] == "contactsOnly"
        assert sent["externalReplyMessage"] == _STORED_EXTERNAL

    async def test_an_audience_neither_the_call_nor_the_mailbox_names_discloses_the_least(
        self, client: GraphServiceClient, graph: respx.MockRouter, writes: respx.Route
    ) -> None:
        """`none` answers colleagues only. Inventing `all` here would publish the reply text to
        every stranger who writes, on the strength of an argument nobody passed."""
        _ = graph.get(_SETTINGS).mock(
            return_value=_settings_response(_setting(external_audience=None))
        )

        _ = await _scheduled(client)

        assert _sent(writes)["externalAudience"] == "none"

    @pytest.mark.usefixtures("reads")
    async def test_the_status_is_written_in_microsofts_own_spelling(
        self, client: GraphServiceClient, writes: respx.Route
    ) -> None:
        _ = await _scheduled(client)

        assert _sent(writes)["status"] == "scheduled"

    @pytest.mark.usefixtures("reads")
    async def test_turning_it_off_writes_the_disabled_status(
        self, client: GraphServiceClient, writes: respx.Route
    ) -> None:
        _ = await set_automatic_reply(client, change=ReplyChange(status="disabled"))

        assert _sent(writes)["status"] == "disabled"

    @pytest.mark.usefixtures("reads")
    async def test_the_window_carries_the_zone_the_call_named(
        self, client: GraphServiceClient, writes: respx.Route
    ) -> None:
        _ = await _scheduled(client, time_zone="W. Europe Standard Time")

        sent = _sent(writes)
        assert sent["scheduledStartDateTime"] == {
            "dateTime": "2026-09-01T08:00:00",
            "timeZone": "W. Europe Standard Time",
        }
        assert sent["scheduledEndDateTime"] == {
            "dateTime": "2026-09-14T18:00:00",
            "timeZone": "W. Europe Standard Time",
        }

    @pytest.mark.usefixtures("reads")
    async def test_a_window_the_call_omits_is_sent_as_the_mailbox_had_it(
        self, client: GraphServiceClient, writes: respx.Route
    ) -> None:
        """Switching the reply off leaves the dates behind rather than dropping them, so a mailbox
        that is turned off and on again keeps the window its owner set."""
        _ = await set_automatic_reply(client, change=ReplyChange(status="disabled"))

        sent = _sent(writes)
        assert sent["scheduledStartDateTime"] == {
            "dateTime": "2026-03-20T18:00:00.0000000",
            "timeZone": "UTC",
        }

    async def test_a_mailbox_with_no_setting_at_all_is_written_without_inventing_one(
        self, client: GraphServiceClient, graph: respx.MockRouter, writes: respx.Route
    ) -> None:
        """kiota drops a property whose value is None, so there is nothing to send for a property
        Microsoft never reported and no null is put on the wire in its place."""
        _ = graph.get(_SETTINGS).mock(return_value=_settings_response(None))

        _ = await _scheduled(client)

        sent = _sent(writes)
        assert "internalReplyMessage" not in sent
        assert "externalReplyMessage" not in sent
        assert sent["status"] == "scheduled"


class TestItAnswersWithWhatMicrosoftStored:
    @pytest.mark.usefixtures("reads")
    async def test_the_window_reported_is_the_one_microsoft_converted_it_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft's own example sends an 18:00 UTC start and answers with a 02:00 UTC one. A
        tool reporting its arguments would tell the user they are away at hours the mailbox does
        not have."""
        _ = graph.patch(_SETTINGS).mock(
            return_value=_settings_response(
                _setting(status="scheduled", start="2026-03-20T02:00:00.0000000")
            )
        )

        answer = await _scheduled(client, start="2026-03-20T18:00:00")

        assert answer.scheduled_start is not None
        assert answer.scheduled_start.date_time == "2026-03-20T02:00:00.0000000"
        assert answer.scheduled_start.time_zone == "UTC"

    @pytest.mark.usefixtures("reads")
    async def test_a_status_microsoft_disagrees_about_is_the_answer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.patch(_SETTINGS).mock(
            return_value=_settings_response(_setting(status="alwaysEnabled"))
        )

        answer = await _scheduled(client)

        assert answer.status == "alwaysEnabled"

    @pytest.mark.usefixtures("reads")
    async def test_the_audience_reported_is_microsofts_and_not_the_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.patch(_SETTINGS).mock(
            return_value=_settings_response(_setting(external_audience="all"))
        )

        answer = await _scheduled(client, external_audience="none")

        assert answer.external_audience == "all"

    @pytest.mark.usefixtures("reads", "writes")
    async def test_text_the_call_never_sent_is_reported_rather_than_answered_as_none(
        self, client: GraphServiceClient
    ) -> None:
        """The failure this exists to prevent: an omitted `external_message` re-broadcasting the
        mailbox's old text while the answer says there is none."""
        answer = await _scheduled(client)

        assert answer.external_message == _STORED_EXTERNAL
        assert answer.internal_message == _STORED_INTERNAL

    async def test_a_write_microsoft_answered_with_no_setting_is_read_back_rather_than_assumed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = graph.get(_SETTINGS).mock(
            side_effect=[
                _settings_response(_setting()),
                _settings_response(_setting(status="scheduled", external_audience="none")),
            ]
        )
        _ = graph.patch(_SETTINGS).mock(return_value=_settings_response(None))

        answer = await _scheduled(client)

        assert read.call_count == 2
        assert answer.status == "scheduled"
        assert answer.external_audience == "none"

    async def test_a_mailbox_microsoft_reports_nothing_for_answers_null_and_not_off(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Null is "Microsoft told us nothing", which is a different claim from "the reply is
        disabled" — and the second one would be a reassurance nobody checked."""
        _ = graph.get(_SETTINGS).mock(return_value=_settings_response(None))
        _ = graph.patch(_SETTINGS).mock(return_value=_settings_response(None))

        answer = await _scheduled(client)

        assert answer.status is None
        assert answer.external_audience is None
        assert answer.internal_message is None
        assert answer.scheduled_start is None


class TestTheWriteIsNotRetried:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_patch_microsoft_answered_503_to_is_sent_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Without `no_retry` the SDK sends this `GraphSettings().max_retries` more times, and the
        answer would describe whichever response came back last rather than the one applied."""
        _ = graph.get(_SETTINGS).mock(return_value=_settings_response(_setting()))
        route = graph.patch(_SETTINGS).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphFailure):
            _ = await _scheduled(client)

        assert route.call_count == 1
        assert GraphSettings().max_retries > 0, "no retries are configured, so this proves nothing"


class TestHowItDeclaresItself:
    async def test_it_says_it_writes_and_that_writing_the_same_thing_twice_is_safe(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
        assert WRITE_IDEMPOTENT["idempotentHint"] is True

    def test_it_asks_for_the_permission_that_can_write_mailbox_settings(self) -> None:
        assert GRAPH_PERMISSIONS == ("MailboxSettings.ReadWrite",)

    async def test_it_tells_a_caller_the_text_is_sent_to_other_people(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        described = tool.description or ""
        assert "CHANGES THE MAILBOX" in described
        assert "everyone who emails this user gets `internal_message` back" in described
        assert "outside the organization get `external_message`" in described

    async def test_it_tells_a_caller_how_to_turn_an_automatic_reply_off(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert '`status: "disabled"` to turn' in (tool.description or "")
