from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.attachments import ATTACHMENT_FIELDS
from office_365_mcp.shared.handles import (
    EventAttachmentHandle,
    MailAttachmentHandle,
    MailFolderHandle,
    mail_attachment_handle,
    mail_message_handle,
)
from office_365_mcp.tools import outlook_list_attachments as lister

_MESSAGE_ID = "AAMkAGI2SYNTHETIC-immutable-0001="
_FILE_ID = "AAMkAGI2SYNTHETIC-attachment-0001="
_ITEM_ID = "AAMkAGI2SYNTHETIC-attachment-0002="
_LINK_ID = "AAMkAGI2SYNTHETIC-attachment-0003="

_PATH = "/me/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/attachments"

_MESSAGE_URI = "outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"


def _file(attachment_id: str = _FILE_ID, *, name: str = "Invoice-4471.pdf") -> dict[str, object]:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "id": attachment_id,
        "name": name,
        "contentType": "application/pdf",
        "size": 13068,
        "isInline": False,
        "lastModifiedDateTime": "2026-03-04T09:15:00Z",
    }


def _item() -> dict[str, object]:
    return {
        "@odata.type": "#microsoft.graph.itemAttachment",
        "id": _ITEM_ID,
        "name": "Reminder - please bring laptop",
        "contentType": None,
        "size": 32005,
        "isInline": False,
        "lastModifiedDateTime": "2026-03-04T09:16:00Z",
    }


def _link() -> dict[str, object]:
    return {
        "@odata.type": "#microsoft.graph.referenceAttachment",
        "id": _LINK_ID,
        "name": "Sales Invoice Template.docx",
        "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size": 1060,
        "isInline": True,
        "lastModifiedDateTime": "2026-03-04T09:17:00Z",
    }


def _page(
    attachments: Sequence[Mapping[str, object]], *, next_link: str | None = None
) -> dict[str, object]:
    page: dict[str, object] = {"value": [dict(attachment) for attachment in attachments]}
    if next_link is not None:
        page["@odata.nextLink"] = next_link
    return page


@pytest.fixture
def attachments(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_PATH).mock(return_value=httpx.Response(200, json=_page([_file()])))


class TestWhatItAsksGraphFor:
    async def test_it_selects_the_shared_attachment_fields_and_never_the_bytes(
        self, client: GraphServiceClient, attachments: respx.Route
    ) -> None:
        _ = await lister.list_attachments(client, uri=_MESSAGE_URI)

        url = attachments.calls.last.request.url
        assert url.params["$select"].split(",") == list(ATTACHMENT_FIELDS)
        assert "contentBytes" not in str(url), "a listing that carried every file would be huge"
        assert "$expand" not in url.params

    async def test_it_declares_the_immutable_id_space(
        self, client: GraphServiceClient, attachments: respx.Route
    ) -> None:
        _ = await lister.list_attachments(client, uri=_MESSAGE_URI)

        assert 'IdType="ImmutableId"' in attachments.calls.last.request.headers["prefer"]

    async def test_a_short_list_costs_one_request(
        self, client: GraphServiceClient, attachments: respx.Route
    ) -> None:
        _ = await lister.list_attachments(client, uri=_MESSAGE_URI)

        assert attachments.call_count == 1


class TestWhatItAnswers:
    async def test_each_row_carries_the_handle_that_reads_the_attachment(
        self, client: GraphServiceClient, attachments: respx.Route
    ) -> None:
        _ = attachments

        answer = await lister.list_attachments(client, uri=_MESSAGE_URI)

        assert [mail_attachment_handle(row.uri) for row in answer.attachments] == [
            MailAttachmentHandle(_MESSAGE_ID, _FILE_ID)
        ]

    async def test_a_row_carries_the_size_the_media_type_and_the_inline_flag_graph_reported(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, json=_page([_link()])))

        answer = await lister.list_attachments(client, uri=_MESSAGE_URI)

        (row,) = answer.attachments
        assert (row.size, row.content_type, row.is_inline) == (
            1060,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            True,
        )
        assert row.last_modified_at == "2026-03-04T09:17:00+00:00"

    async def test_the_three_kinds_come_back_in_the_order_graph_sent_them(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(200, json=_page([_file(), _item(), _link()]))
        )

        answer = await lister.list_attachments(client, uri=_MESSAGE_URI)

        assert [(row.kind, row.name) for row in answer.attachments] == [
            ("file", "Invoice-4471.pdf"),
            ("item", "Reminder - please bring laptop"),
            ("reference", "Sales Invoice Template.docx"),
        ]
        assert answer.capped is False

    async def test_a_message_with_no_attachment_answers_an_empty_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, json=_page([])))

        answer = await lister.list_attachments(client, uri=_MESSAGE_URI)

        assert answer.attachments == []
        assert answer.capped is False

    async def test_it_follows_the_next_link_to_the_end_of_the_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        more = f"https://graph.microsoft.com/v1.0{_PATH}?%24skip=1"
        route = graph.get(_PATH).mock(
            side_effect=[
                httpx.Response(200, json=_page([_file()], next_link=more)),
                httpx.Response(200, json=_page([_item()])),
            ]
        )

        answer = await lister.list_attachments(client, uri=_MESSAGE_URI)

        assert [row.kind for row in answer.attachments] == ["file", "item"]
        assert answer.capped is False
        assert route.call_count == 2
        assert 'IdType="ImmutableId"' in route.calls.last.request.headers["prefer"]

    async def test_a_list_longer_than_the_scan_limit_says_it_is_capped(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_SCANNED_ITEMS", 2)
        more = f"https://graph.microsoft.com/v1.0{_PATH}?%24skip=3"
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                200, json=_page([_file(), _item(), _link()], next_link=more)
            )
        )

        answer = await lister.list_attachments(client, uri=_MESSAGE_URI)

        assert len(answer.attachments) == 2
        assert answer.capped is True


class TestMailboxTargeting:
    async def test_no_mailbox_lists_the_signed_in_users_own_one(
        self, client: GraphServiceClient, attachments: respx.Route
    ) -> None:
        _ = await lister.list_attachments(client, uri=_MESSAGE_URI)

        assert attachments.called

    async def test_a_mailbox_lists_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        shared = graph.get(
            "/users/alex@example.invalid/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/attachments"
        ).mock(return_value=httpx.Response(200, json=_page([_file()])))
        mine = graph.get(_PATH)

        answer = await lister.list_attachments(
            client, uri=_MESSAGE_URI, mailbox="alex@example.invalid"
        )

        assert shared.called
        assert mine.call_count == 0
        assert [row.name for row in answer.attachments] == ["Invoice-4471.pdf"]


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "uri",
        [
            MailAttachmentHandle(_MESSAGE_ID, _FILE_ID).uri,
            EventAttachmentHandle("AAMkSYNTHETIC-cal-0001=", _MESSAGE_ID, _FILE_ID).uri,
            "outlook:///events/AAMkSYNTHETIC-cal-0001%3D/AAMkAGI2SYNTHETIC-immutable-0001%3D",
            MailFolderHandle("AQMkADAwSYNTHETIC-folder").uri,
            "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D",
            "AAMkAGI2SYNTHETIC-immutable-0001=",
            "https://outlook.office365.invalid/owa/?ItemID=synthetic",
            "Invoice 4471",
        ],
    )
    async def test_a_value_that_is_not_a_message_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, uri: str
    ) -> None:
        with pytest.raises(ToolError, match="takes the `uri` of a message") as refused:
            _ = await lister.list_attachments(client, uri=uri)

        assert graph.calls.call_count == 0
        assert "outlook_read_attachment" in str(refused.value)
        assert "again with this value, the call will fail the same way" in str(refused.value)

    async def test_a_message_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await lister.list_attachments(client, uri=_MESSAGE_URI)

    async def test_a_refused_read_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await lister.list_attachments(client, uri=_MESSAGE_URI)


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_microsoft_documents_for_a_shared_mailbox(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Mail.Read", "Mail.Read.Shared")

    def test_the_example_call_is_a_message_handle_this_tool_accepts(self) -> None:
        assert set(lister.GRAPH_CALL_EXAMPLE) == {"uri"}
        example = cast("str", lister.GRAPH_CALL_EXAMPLE["uri"])
        assert mail_message_handle(example) is not None

    def test_a_404_says_the_handle_is_well_formed_and_sends_the_caller_back_to_the_search(
        self,
    ) -> None:
        assert "The handle is well formed" in lister.GRAPH_NOT_FOUND
        assert "outlook_search_mail" in lister.GRAPH_NOT_FOUND
        assert "list its attachments again" in lister.GRAPH_NOT_FOUND.lower()
        assert "again with this handle, the call will fail the same way" in lister.GRAPH_NOT_FOUND

    async def test_it_announces_itself_as_reading_and_changing_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.title == "List Mail Attachments"

    async def test_it_takes_the_handle_and_a_mailbox_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(properties) == {"uri", "mailbox"}
        assert tool.parameters["required"] == ["uri"]

    async def test_the_parameters_and_the_answer_are_plain_objects_at_their_root(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        refused_at_root = {"anyOf", "oneOf", "allOf", "not", "enum", "const"}
        for schema in (tool.parameters, tool.output_schema):
            assert schema is not None
            assert schema["type"] == "object"
            assert refused_at_root & set(schema) == set()

    async def test_the_description_names_the_reader_and_the_kinds_it_refuses(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        described = tool.description or ""
        assert "outlook_read_attachment" in described
        assert "outlook_search_mail" in described
        assert "This tool returns no bytes" in described
        assert "inline images" in described
        assert "It refuses the kinds `item` and `reference`" in described
        assert "Notes:" in described


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    lister.register(mcp, transport)
    tool = await mcp.get_tool(lister.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool
