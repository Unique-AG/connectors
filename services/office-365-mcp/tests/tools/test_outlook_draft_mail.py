import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphUnavailable
from office_365_mcp.shared.handles import mail_draft_handle, mail_message_handle
from office_365_mcp.shared.seam import WRITE_ADDITIVE
from office_365_mcp.tools import outlook_draft_mail as drafter
from office_365_mcp.tools.outlook_draft_mail import MailDraft

_DRAFT_ID = "AAMkAGI2SYNTHETIC-draft-0001="

_MESSAGES = "/me/messages"

_WEB_LINK = "https://outlook.office365.invalid/owa/?ItemID=synthetic-draft"

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"

_SUBJECT = "Invoice 4471"
_BODY = "Sending this over for review."


def _recipient(name: str | None, address: str) -> dict[str, object]:
    return {"emailAddress": {"name": name, "address": address}}


def _created(
    *,
    draft_id: str = _DRAFT_ID,
    to: Sequence[Mapping[str, object]] = (),
    cc: Sequence[Mapping[str, object]] = (),
    subject: str | None = _SUBJECT,
    body: Mapping[str, object] | None = None,
    web_link: str | None = _WEB_LINK,
) -> dict[str, object]:
    return {
        "id": draft_id,
        "isDraft": True,
        "subject": subject,
        "bodyPreview": _BODY,
        "toRecipients": [dict(one) for one in (to or [_recipient("Ada Lovelace", _ADA)])],
        "ccRecipients": [dict(one) for one in cc],
        "body": dict(body) if body is not None else {"contentType": "html", "content": _BODY},
        "webLink": web_link,
        "parentFolderId": "AQMkADAwSYNTHETIC-drafts",
        "hasAttachments": False,
    }


def _creates(graph: respx.MockRouter, payload: dict[str, object]) -> respx.Route:
    return graph.post(_MESSAGES).mock(return_value=httpx.Response(201, json=payload))


async def _draft(client: GraphServiceClient, **overrides: object) -> MailDraft:
    arguments: dict[str, object] = {"to": [_ADA], "subject": _SUBJECT, "body_html": _BODY}
    arguments.update(overrides)
    return await drafter.draft_mail(
        client,
        to=cast("Sequence[str]", arguments["to"]),
        subject=cast("str", arguments["subject"]),
        body_html=cast("str", arguments["body_html"]),
        cc=cast("Sequence[str]", arguments.get("cc", ())),
    )


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _addressed(sent: dict[str, object], field: str) -> list[str]:
    recipients = cast("list[dict[str, object]]", sent.get(field, []))
    return [
        cast("str", cast("dict[str, object]", recipient["emailAddress"])["address"])
        for recipient in recipients
    ]


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    drafter.register(mcp, transport)
    tool = await mcp.get_tool(drafter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_declares_the_immutable_id_space_the_handle_is_minted_in(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client)

        assert 'IdType="ImmutableId"' in route.calls.last.request.headers["Prefer"]

    async def test_it_creates_one_message_in_the_mailbox_collection(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client)

        assert route.call_count == 1, "one draft, one request"

    @pytest.mark.parametrize(
        "written",
        [
            "Read https://payments.invalid/pay before Friday.",
            "<p>Hello</p><p>Thanks</p>",
            "<a href='https://evil.invalid'>https://bank.invalid</a>",
            "<img src='https://tracker.invalid/p.gif'>",
            "<script>alert(1)</script>",
            "<div onclick='x'>x</div>",
            "a &lt; b &amp; c",
        ],
    )
    async def test_the_body_is_sent_as_html_exactly_as_written(
        self, client: GraphServiceClient, graph: respx.MockRouter, written: str
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, body_html=written)

        body = cast("dict[str, object]", _sent(route)["body"])
        assert body["contentType"] == "html"
        assert body["content"] == written

    async def test_it_sends_the_recipients_and_the_subject_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, to=[_ADA, _GRACE], cc=["pam@example.invalid"])

        sent = _sent(route)
        assert _addressed(sent, "toRecipients") == [_ADA, _GRACE]
        assert _addressed(sent, "ccRecipients") == ["pam@example.invalid"]
        assert sent["subject"] == _SUBJECT

    async def test_nothing_it_sends_carries_an_attachment_or_a_blind_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client)

        sent = _sent(route)
        assert "attachments" not in sent
        keys = [key.casefold() for key in sent]
        assert not [key for key in keys if "attach" in key]
        assert not [key for key in keys if "bcc" in key]

    async def test_it_asks_graph_for_nothing_but_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())
        send_mail = graph.post("/me/sendMail").mock(return_value=httpx.Response(202))

        _ = await _draft(client)

        assert route.call_count == 1
        assert send_mail.call_count == 0
        assert len(graph.calls) == 1, "the only request a draft costs is the one that creates it"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_MESSAGES).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _draft(client)

        assert route.call_count == 1


class TestTheAddressesItRefuses:
    @pytest.mark.parametrize(
        "address",
        [
            "Ada Lovelace <ada@example.invalid>",
            "ada@example.invalid, grace@example.invalid",
            "ada@example.invalid; grace@example.invalid",
            "Ada Lovelace",
            "ada@",
            "@example.invalid",
            "ada@ex ample.invalid",
            "ada@example@invalid",
            "   ",
        ],
    )
    async def test_an_entry_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, address: str
    ) -> None:
        route = _creates(graph, _created())

        with pytest.raises(ToolError):
            _ = await _draft(client, to=[address])

        assert route.call_count == 0, "a refused argument creates nothing in the mailbox"

    async def test_a_cc_entry_is_held_to_the_same_rule_and_names_its_argument(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        with pytest.raises(ToolError, match="`cc`"):
            _ = await _draft(client, cc=["Grace Hopper <grace@example.invalid>"])

        assert route.call_count == 0

    async def test_the_refusal_says_where_an_address_may_come_from(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="outlook_find_recipient"):
            _ = await _draft(client, to=["Ada Lovelace"])

    async def test_surrounding_whitespace_is_trimmed_rather_than_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, to=[f"  {_ADA}  "])

        assert _addressed(_sent(route), "toRecipients") == [_ADA]

    @pytest.mark.parametrize("count", [0, drafter.MAX_RECIPIENTS + 1])
    async def test_a_recipient_list_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, count: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _draft(client, to=[_ADA] * count)

    async def test_a_cc_list_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _draft(client, cc=[_ADA] * (drafter.MAX_RECIPIENTS + 1))


class TestTheSchemaItPublishes:
    async def test_it_takes_five_arguments_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"to", "subject", "body_html", "cc", "mailbox"}

    @pytest.mark.parametrize("word", ["bcc", "blind", "file", "upload", "drive", "url"])
    async def test_no_argument_offers_a_blind_copy_a_fetch_or_markup(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_publishes_no_attachments_argument_and_no_file_bytes(
        self, every_tool: Client[FastMCPTransport]
    ) -> None:
        listed = {tool.name: tool for tool in await every_tool.list_tools()}
        published = listed[drafter.TOOL_NAME].input_schema

        properties = cast("Mapping[str, object]", published["properties"])
        assert "attachments" not in properties
        assert not [name for name in properties if "attach" in name.casefold()]
        assert "content_bytes" not in json.dumps(published)

    async def test_at_least_one_recipient_is_required_and_ten_is_the_ceiling(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        to = cast("Mapping[str, object]", properties["to"])
        assert to["minItems"] == 1
        assert to["maxItems"] == drafter.MAX_RECIPIENTS
        assert cast("Sequence[str]", parameters["required"]) == ["to", "subject", "body_html"]

    async def test_cc_is_optional_and_bounded_the_same_way(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        cc = cast("Mapping[str, object]", properties["cc"])
        assert cc["default"] == []
        assert cc["maxItems"] == drafter.MAX_RECIPIENTS

    async def test_two_calls_do_not_share_one_cc_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, cc=["pam@example.invalid"])
        _ = await _draft(client)

        assert _addressed(_sent(route), "ccRecipients") == []


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_microsoft_documents_for_creating_a_message(self) -> None:
        assert drafter.GRAPH_PERMISSIONS == ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

    async def test_it_announces_itself_as_a_write_that_destroys_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_the_description_says_it_cannot_send_and_offers_no_bcc(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lowered = description.casefold()
        assert "cannot send" in lowered
        assert "bcc" in lowered
        assert "outlook_find_recipient" in description

    async def test_the_description_says_it_cannot_add_files_and_where_the_user_adds_one(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "It cannot add files to the draft." in description
        assert (
            "If the user asks to attach a file, tell them to add it in Outlook before they send "
            + "the draft."
        ) in description


class TestMailboxTargeting:
    async def test_no_mailbox_drafts_into_the_signed_in_users_own_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client)

        assert route.called

    async def test_a_mailbox_drafts_into_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post("/users/alex@example.invalid/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )

        answer = await drafter.draft_mail(
            client,
            to=[_ADA],
            subject=_SUBJECT,
            body_html=_BODY,
            mailbox="alex@example.invalid",
        )

        assert route.called
        handle = mail_draft_handle(answer.uri)
        assert handle is not None
        assert handle.draft_id == _DRAFT_ID


class TestWhatItAnswers:
    async def test_the_recipients_are_read_off_graph_and_never_echoed_from_the_arguments(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(
            graph,
            _created(
                to=[_recipient("Ada Lovelace", _ADA), _recipient("Grace Hopper", _GRACE)],
                cc=[_recipient("Pam Beesly", "pam@example.invalid")],
            ),
        )

        answer = await _draft(client, to=[_ADA])

        assert [address.address for address in answer.to] == [_ADA, _GRACE]
        assert [address.address for address in answer.cc] == ["pam@example.invalid"]

    async def test_the_subject_and_body_are_read_off_graph_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(
            graph,
            _created(
                subject="Invoice 4471 (stored)",
                body={"contentType": "text", "content": "Stored by Microsoft."},
            ),
        )

        answer = await _draft(client, subject=_SUBJECT, body_html=_BODY)

        assert answer.subject == "Invoice 4471 (stored)"
        assert answer.body == "Stored by Microsoft."

    async def test_it_answers_the_link_graph_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created())

        answer = await _draft(client)

        assert answer.web_link == _WEB_LINK

    async def test_a_draft_graph_gave_no_link_answers_null_rather_than_a_built_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created(web_link=None))

        answer = await _draft(client)

        assert answer.web_link is None

    async def test_the_handle_addresses_a_draft_and_cannot_be_read_as_a_message(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created())

        answer = await _draft(client)

        handle = mail_draft_handle(answer.uri)
        assert handle is not None
        assert handle.draft_id == _DRAFT_ID
        assert mail_message_handle(answer.uri) is None

    async def test_an_empty_cc_comes_back_empty_rather_than_absent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created(cc=[]))

        answer = await _draft(client)

        assert answer.cc == []

    def test_no_attachment_is_addressable_in_the_answer_at_all(self) -> None:
        assert not [name for name in MailDraft.model_fields if "attach" in name.casefold()]

    def test_no_blind_copy_is_addressable_in_the_answer_at_all(self) -> None:
        assert not [name for name in MailDraft.model_fields if "bcc" in name.casefold()]


class TestTheFailuresItPassesOn:
    async def test_a_refused_create_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_MESSAGES).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _draft(client)

    async def test_a_mailbox_that_rejects_the_write_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_MESSAGES).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _draft(client)

        assert route.call_count == 1, "a refused write is not retried into a duplicate draft"
