from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.handles import message_handle
from office_365_mcp.shared.seam import READ_ONLY
from office_365_mcp.tools import teams_list_chat_messages as lister

from .conftest import GRAPH_V1, message_payload

_CHAT_ID = "19:release@thread.v2"
_MESSAGES_PATH = "/chats/19%3Arelease%40thread.v2/messages"
_NEXT_PAGE = f"{GRAPH_V1}{_MESSAGES_PATH}?$skiptoken=synthetic"

_NEWER_ID = "1770000000002"
_OLDER_ID = "1770000000001"

_RENAMED: dict[str, object] = message_payload(
    message_id="1770000009999",
    content="<systemEventMessage/>",
    sender=None,
    message_type="systemEventMessage",
    event_detail={
        "@odata.type": "#microsoft.graph.chatRenamedEventMessageDetail",
        "chatDisplayName": "Release",
    },
)


def _page(*messages: Mapping[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": [dict(message) for message in messages]}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _lists(graph: respx.MockRouter, response: httpx.Response | None = None) -> respx.Route:
    return graph.get(_MESSAGES_PATH).mock(
        return_value=response if response is not None else _page(message_payload())
    )


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    lister.register(mcp, transport)
    tool = await mcp.get_tool(lister.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _property(parameters: Mapping[str, object], name: str) -> Mapping[str, object]:
    return cast(
        "Mapping[str, object]", cast("Mapping[str, object]", parameters["properties"])[name]
    )


class TestTheQueryItSends:
    async def test_no_bound_asks_for_the_newest_messages_by_send_time_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _lists(graph)

        _ = await lister.list_chat_messages(client, chat_id=_CHAT_ID, limit=7)

        assert dict(route.calls.last.request.url.params) == {
            "$top": "7",
            "$orderby": "createdDateTime desc",
        }

    async def test_a_date_bound_admits_that_whole_day(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _lists(graph)

        _ = await lister.list_chat_messages(
            client, chat_id=_CHAT_ID, limit=20, sent_before=date(2026, 3, 4)
        )

        assert dict(route.calls.last.request.url.params) == {
            "$top": "20",
            "$orderby": "createdDateTime desc",
            "$filter": "createdDateTime lt 2026-03-05T00:00:00Z",
        }

    @pytest.mark.parametrize(
        "moment",
        [
            datetime(2026, 3, 4, 17, 0, 0, tzinfo=UTC),
            datetime(2026, 3, 4, 17, 0, 0, 750000, tzinfo=UTC),
            datetime(2026, 3, 4, 17, 0, 0, 750000),
            datetime(2026, 3, 4, 19, 0, 0, 750000, tzinfo=timezone(timedelta(hours=2))),
        ],
        ids=["whole-second", "fractional-second", "no-zone", "east-of-utc"],
    )
    async def test_a_moment_bound_admits_the_whole_second_it_names(
        self, client: GraphServiceClient, graph: respx.MockRouter, moment: datetime
    ) -> None:
        route = _lists(graph)

        _ = await lister.list_chat_messages(client, chat_id=_CHAT_ID, limit=20, sent_before=moment)

        assert dict(route.calls.last.request.url.params) == {
            "$top": "20",
            "$orderby": "createdDateTime desc",
            "$filter": "createdDateTime lt 2026-03-04T17:00:01Z",
        }

    async def test_it_asks_for_the_message_types_graph_hides_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _lists(graph)

        _ = await lister.list_chat_messages(client, chat_id=_CHAT_ID, limit=20)

        assert route.calls.last.request.headers["prefer"] == "include-unknown-enum-members"

    async def test_a_limit_above_graphs_ceiling_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await lister.list_chat_messages(
                client, chat_id=_CHAT_ID, limit=lister.MAX_MESSAGES + 1
            )


class TestOneCallIsOneRequest:
    async def test_microsofts_cursor_is_read_and_never_followed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        second_page = graph.get(_MESSAGES_PATH, params={"$skiptoken": "synthetic"}).mock(
            return_value=_page(message_payload(message_id="1760000000000"))
        )
        _ = _lists(graph, _page(message_payload(), next_link=_NEXT_PAGE))

        listed = await lister.list_chat_messages(client, chat_id=_CHAT_ID, limit=20)

        assert len(graph.calls) == 1
        assert not second_page.called
        assert listed.more_messages is True

    async def test_a_page_with_no_cursor_says_the_chat_holds_nothing_older(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(graph)

        listed = await lister.list_chat_messages(client, chat_id=_CHAT_ID, limit=20)

        assert listed.more_messages is False


class TestWhatItAnswers:
    async def test_the_rows_keep_the_order_graph_sent_them_in(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(
            graph,
            _page(message_payload(message_id=_NEWER_ID), message_payload(message_id=_OLDER_ID)),
        )

        listed = await lister.list_chat_messages(client, chat_id=_CHAT_ID, limit=20)

        assert [row.message_id for row in listed.messages] == [_NEWER_ID, _OLDER_ID]

    async def test_every_row_carries_a_handle_that_names_the_chat(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(graph, _page(message_payload(message_id=_NEWER_ID)))

        listed = await lister.list_chat_messages(client, chat_id=_CHAT_ID, limit=20)

        row = listed.messages[0]
        assert row.uri == f"teams:///chats/19%3Arelease%40thread.v2/messages/{_NEWER_ID}"
        resolved = message_handle(row.uri)
        assert resolved is not None
        assert (resolved.chat_id, resolved.message_id) == (_CHAT_ID, _NEWER_ID)
        assert (row.chat_id, row.team_id, row.channel_id) == (_CHAT_ID, None, None)

    async def test_a_row_carries_the_message_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(graph, _page(message_payload(content="<div><p>ship it&nbsp;Friday</p></div>")))

        listed = await lister.list_chat_messages(client, chat_id=_CHAT_ID, limit=20)

        assert listed.messages[0].text == "ship it Friday"

    async def test_a_system_event_stays_in_the_list_and_says_what_happened(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(graph, _page(message_payload(message_id=_NEWER_ID), _RENAMED))

        listed = await lister.list_chat_messages(client, chat_id=_CHAT_ID, limit=2)

        assert [row.message_id for row in listed.messages] == [_NEWER_ID, "1770000009999"]
        event = listed.messages[1]
        assert event.event == "chat renamed"
        assert event.sender is None
        assert listed.messages[0].event is None

    async def test_a_chat_nobody_wrote_in_is_an_empty_list_not_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(graph, _page())

        listed = await lister.list_chat_messages(client, chat_id=_CHAT_ID, limit=20)

        assert listed.messages == []
        assert listed.more_messages is False


class TestGraphFailures:
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists(
            graph,
            httpx.Response(403, json={"error": {"code": "Forbidden", "message": "denied"}}),
        )

        with pytest.raises(GraphForbidden):
            _ = await lister.list_chat_messages(client, chat_id=_CHAT_ID, limit=20)


class TestHowItDeclaresItself:
    def test_the_permission_is_chat_read_and_nothing_wider(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Chat.Read",)

    async def test_it_announces_itself_as_read_only(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is READ_ONLY["readOnlyHint"]
        assert annotations.open_world_hint is READ_ONLY["openWorldHint"]

    async def test_the_arguments_are_chat_id_limit_and_sent_before(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert set(cast("Mapping[str, object]", parameters["properties"])) == {
            "chat_id",
            "limit",
            "sent_before",
        }
        assert list(cast("Sequence[str]", parameters["required"])) == ["chat_id"]
        assert _property(parameters, "chat_id")["minLength"] == 1

    async def test_limit_runs_from_one_to_graphs_ceiling_of_fifty_and_defaults_to_twenty(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        limit = _property(parameters, "limit")
        assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 50, 20)

    async def test_sent_before_takes_a_date_or_a_moment(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        shapes = cast(
            "Sequence[Mapping[str, object]]", _property(parameters, "sent_before")["anyOf"]
        )
        assert {shape.get("format") for shape in shapes} == {"date", "date-time", None}

    async def test_the_description_says_how_to_read_further_back_in_one_request_a_call(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "pass the oldest `created_at` as `sent_before`" in description
        assert "One call is one request" in description
        assert "teams_list_chats" in description
