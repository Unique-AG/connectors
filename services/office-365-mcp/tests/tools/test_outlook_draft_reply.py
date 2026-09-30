import json
import re
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import MailMessageHandle, mail_draft_handle, mail_message_handle
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm, Confirmed
from office_365_mcp.tools import outlook_draft_reply as replier
from office_365_mcp.tools.outlook_draft_reply import MailReplyDraft, MailReplyMode

_MESSAGE_ID = "AAMkAGI2SYNTHETIC-immutable-0001="

_DRAFT_ID = "AAMkAGI2SYNTHETIC-reply-draft-0001="

_MESSAGE_REF = MailMessageHandle(_MESSAGE_ID).uri

_CREATE_REPLY = "/me/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/createReply"
_CREATE_FORWARD = "/me/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/createForward"
_FILL = "/me/messages/AAMkAGI2SYNTHETIC-reply-draft-0001%3D"

_WEB_LINK = "https://outlook.office365.invalid/owa/?ItemID=synthetic-reply-draft"

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"
_PAM = "pam@example.invalid"

_SUBJECT = "RE: Invoice 4471"
_BODY = "Friday works for me."

_SEEDED = "<div>From: Ada Lovelace<br>Sent: Monday<br>Can we meet Friday?</div>"

_REFUSED: dict[str, object] = {"error": {"code": "ErrorAccessDenied", "message": "denied"}}

_SHARED_MAILBOX = "alex@example.invalid"
_SHARED_MESSAGE = f"/users/{_SHARED_MAILBOX}/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"
_SHARED_CREATE_REPLY = f"{_SHARED_MESSAGE}/createReply"
_SHARED_CREATE_FORWARD = f"{_SHARED_MESSAGE}/createForward"
_SHARED_FILL = f"/users/{_SHARED_MAILBOX}/messages/AAMkAGI2SYNTHETIC-reply-draft-0001%3D"

_NOT_CREATED = "No draft was created."


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOT_CREATED


async def _never_asked(question: str, about: str) -> Confirmed:
    raise AssertionError(f"a person was asked {question!r} about {about!r}")


async def _asks_the_client(question: str, about: str) -> Confirmed:
    assert question and about
    return InputRequiredResult(input_requests={}, request_state=about)


def _recipient(name: str | None, address: str) -> dict[str, object]:
    return {"emailAddress": {"name": name, "address": address}}


def _draft(
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
        "toRecipients": [dict(one) for one in (to or [_recipient("Ada Lovelace", _ADA)])],
        "ccRecipients": [dict(one) for one in cc],
        "body": dict(body) if body is not None else {"contentType": "html", "content": _SEEDED},
        "webLink": web_link,
        "parentFolderId": "AQMkADAwSYNTHETIC-drafts",
        "hasAttachments": False,
    }


def _filled(
    *,
    to: Sequence[Mapping[str, object]] = (),
    cc: Sequence[Mapping[str, object]] = (),
    subject: str | None = _SUBJECT,
    content: str | None = _BODY,
    web_link: str | None = _WEB_LINK,
) -> dict[str, object]:
    return {
        "id": _DRAFT_ID,
        "isDraft": True,
        "subject": subject,
        "toRecipients": [dict(one) for one in (to or [_recipient("Ada Lovelace", _ADA)])],
        "ccRecipients": [dict(one) for one in cc],
        "body": None if content is None else {"contentType": "text", "content": content},
        "webLink": web_link,
    }


def _creates(
    graph: respx.MockRouter, path: str = _CREATE_REPLY, payload: dict[str, object] | None = None
) -> respx.Route:
    return graph.post(path).mock(
        return_value=httpx.Response(201, json=payload if payload is not None else _draft())
    )


def _fills(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    return graph.patch(_FILL).mock(
        return_value=httpx.Response(200, json=payload if payload is not None else _filled())
    )


def _original(
    *,
    subject: str | None = "Invoice 4471",
    sender: str | None = _ADA,
    reply_to: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "id": _MESSAGE_ID,
        "subject": subject,
        "from": None if sender is None else _recipient("Ada Lovelace", sender),
        "replyTo": [_recipient(None, address) for address in reply_to],
    }


def _reads(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    return graph.get(_SHARED_MESSAGE).mock(
        return_value=httpx.Response(200, json=payload if payload is not None else _original())
    )


def _shared_writes(graph: respx.MockRouter, create: str = _SHARED_CREATE_REPLY) -> respx.Route:
    _ = graph.patch(_SHARED_FILL).mock(return_value=httpx.Response(200, json=_filled()))
    return graph.post(create).mock(return_value=httpx.Response(201, json=_draft()))


def _methods(graph: respx.MockRouter) -> list[str]:
    return [call.request.method for call in cast("Sequence[Call]", graph.calls)]


def _written(graph: respx.MockRouter) -> list[str]:
    return [method for method in _methods(graph) if method != "GET"]


async def _reply(client: GraphServiceClient, **overrides: object) -> MailReplyDraft:
    arguments: dict[str, object] = {
        "message_ref": _MESSAGE_REF,
        "mode": "reply",
        "body_html": _BODY,
    }
    arguments.update(overrides)
    answer = await replier.draft_reply(
        client,
        message_ref=cast("str", arguments["message_ref"]),
        mode=cast("MailReplyMode", arguments["mode"]),
        body_html=cast("str", arguments["body_html"]),
        confirm=cast("Confirm", arguments.get("confirm", _never_asked)),
        to=cast("Sequence[str]", arguments.get("to", ())),
        mailbox=cast("str | None", arguments.get("mailbox")),
    )
    assert isinstance(answer, MailReplyDraft), "the confirmation asked instead of answering"
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


def _addressed(sent: Mapping[str, object], field: str) -> list[str]:
    recipients = cast("list[dict[str, object]]", sent.get(field, []))
    return [
        cast("str", cast("dict[str, object]", recipient["emailAddress"])["address"])
        for recipient in recipients
    ]


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    replier.register(mcp, transport)
    tool = await mcp.get_tool(replier.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _properties(parameters: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    return cast("Mapping[str, Mapping[str, object]]", parameters["properties"])


class TestWhatItSendsToGraph:
    async def test_a_reply_is_created_from_the_message_the_handle_names(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        _ = _fills(graph)

        _ = await _reply(client)

        assert create.call_count == 1

    async def test_a_forward_is_created_on_the_forward_route_and_carries_its_recipients(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph, _CREATE_FORWARD)
        _ = _fills(graph)

        _ = await _reply(client, mode="forward", to=[_GRACE, _PAM])

        assert create.call_count == 1
        assert _addressed(_sent(create), "ToRecipients") == [_GRACE, _PAM]

    async def test_the_create_carries_no_comment_because_graph_drops_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        _ = _fills(graph)

        _ = await _reply(client)

        assert not [key for key in _sent(create) if "comment" in key.casefold()]

    async def test_the_fill_is_a_second_write_and_not_optional(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)

        _ = await _reply(client)

        assert create.call_count == 1
        assert fill.call_count == 1
        assert len(graph.calls) == 2, "a draft with text in it costs exactly two requests"

    async def test_the_body_reaches_the_mailbox_as_html(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        fill = _fills(graph)

        _ = await _reply(client, body_html="Read https://payments.invalid/pay before Friday.")

        body = cast("dict[str, object]", _sent(fill)["body"])
        assert body["contentType"] == "html"
        assert body["content"] == "Read https://payments.invalid/pay before Friday."

    async def test_the_fill_names_the_body_and_nothing_else_about_the_draft(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _CREATE_FORWARD)
        fill = _fills(graph)

        _ = await _reply(client, mode="forward", to=[_GRACE])

        assert set(_sent(fill)) == {"@odata.type", "body"}

    async def test_neither_write_offers_an_attachment_a_copy_or_a_blind_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph, _CREATE_FORWARD)
        fill = _fills(graph)

        _ = await _reply(client, mode="forward", to=[_GRACE])

        keys = [key.casefold() for key in (*_sent(create), *_sent(fill))]
        assert not [key for key in keys if "attach" in key]
        assert not [key for key in keys if "cc" in key]

    async def test_both_writes_ask_for_immutable_ids(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)

        _ = await _reply(client)

        for route in (create, fill):
            assert 'IdType="ImmutableId"' in route.calls.last.request.headers["Prefer"]

    async def test_it_asks_graph_for_nothing_but_the_create_and_the_fill(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)
        send = graph.post("/me/messages/AAMkAGI2SYNTHETIC-reply-draft-0001%3D/send").mock(
            return_value=httpx.Response(202)
        )

        _ = await _reply(client)

        assert send.call_count == 0
        assert len(graph.calls) == 2

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = graph.post(_CREATE_REPLY).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _reply(client)

        assert create.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_fill_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        fill = graph.patch(_FILL).mock(return_value=httpx.Response(503))

        answer = await _reply(client)

        assert fill.call_count == 1
        assert answer.body_written is False


class TestTheModesAndAddressesItRefuses:
    @pytest.mark.parametrize("mode", ["replyAll", "reply_all", "reply-all", "REPLY", ""])
    async def test_a_mode_that_is_not_one_of_the_two_reaches_graph_at_all(
        self, client: GraphServiceClient, graph: respx.MockRouter, mode: str
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="reply-all") as raised:
            _ = await _reply(client, mode=mode)

        assert "outlook_draft_reply_all" in str(raised.value)
        assert len(graph.calls) == 0

    async def test_to_on_a_reply_is_refused_and_the_refusal_names_the_mode(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="`reply`"):
            _ = await _reply(client, to=[_GRACE])

        assert len(graph.calls) == 0, "a refused argument creates nothing in the mailbox"

    async def test_a_forward_with_nobody_to_forward_to_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _CREATE_FORWARD)

        with pytest.raises(ToolError, match="forward"):
            _ = await _reply(client, mode="forward")

        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        "address",
        [
            "Grace Hopper <grace@example.invalid>",
            "grace@example.invalid, pam@example.invalid",
            "grace@example.invalid; pam@example.invalid",
            "Grace Hopper",
            "grace@",
            "@example.invalid",
            "grace@ex ample.invalid",
            "grace@example@invalid",
            "   ",
        ],
    )
    async def test_a_forward_entry_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, address: str
    ) -> None:
        _ = _creates(graph, _CREATE_FORWARD)

        with pytest.raises(ToolError):
            _ = await _reply(client, mode="forward", to=[address])

        assert len(graph.calls) == 0

    async def test_the_refusal_says_where_an_address_may_come_from(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="outlook_find_recipient"):
            _ = await _reply(client, mode="forward", to=["Grace Hopper"])

    async def test_surrounding_whitespace_is_trimmed_rather_than_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph, _CREATE_FORWARD)
        _ = _fills(graph)

        _ = await _reply(client, mode="forward", to=[f"  {_GRACE}  "])

        assert _addressed(_sent(create), "ToRecipients") == [_GRACE]

    @pytest.mark.parametrize(
        "ref",
        [
            "outlook:///drafts/AAMkAGI2SYNTHETIC-immutable-0001%3D",
            "outlook:///folders/AQMkADAwSYNTHETIC",
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            "AAMkAGI2SYNTHETIC-immutable-0001=",
            "https://outlook.office365.invalid/owa/?ItemID=synthetic",
            "Invoice 4471",
        ],
    )
    async def test_a_message_ref_that_is_not_a_message_handle_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, ref: str
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="outlook:///messages"):
            _ = await _reply(client, message_ref=ref)

        assert len(graph.calls) == 0

    async def test_eleven_forward_recipients_all_reach_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph, _CREATE_FORWARD)
        _ = _fills(graph)
        many = [f"person{number}@example.invalid" for number in range(11)]

        _ = await _reply(client, mode="forward", to=many)

        assert _addressed(_sent(create), "ToRecipients") == many


class TestTheSchemaItPublishes:
    async def test_it_takes_five_arguments_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert set(_properties(parameters)) == {
            "message_ref",
            "mode",
            "body_html",
            "to",
            "mailbox",
        }

    async def test_the_only_modes_it_offers_are_reply_and_forward(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        mode = _properties(parameters)["mode"]
        assert mode["$ref"] == "#/$defs/MailReplyMode"
        published = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
        assert cast("Sequence[str]", published["MailReplyMode"]["enum"]) == list(replier.MODES)
        assert list(replier.MODES) == ["reply", "forward"]

    @pytest.mark.parametrize("word", ["cc", "bcc", "blind", "all", "file", "upload", "drive"])
    async def test_no_argument_offers_a_copy_or_markup(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert not [name for name in _properties(parameters) if word in name.casefold()]

    async def test_it_publishes_no_attachments_argument_and_no_file_bytes(
        self, every_tool: Client[FastMCPTransport]
    ) -> None:
        listed = {tool.name: tool for tool in await every_tool.list_tools()}
        published = listed[replier.TOOL_NAME].input_schema

        assert "attachments" not in _properties(published)
        assert not [name for name in _properties(published) if "attach" in name.casefold()]
        assert "content_bytes" not in json.dumps(published)

    async def test_the_message_the_mode_and_the_text_are_required_and_to_is_not(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert cast("Sequence[str]", parameters["required"]) == [
            "message_ref",
            "mode",
            "body_html",
        ]

    async def test_to_defaults_to_nobody_and_has_no_ceiling(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        to = _properties(parameters)["to"]
        assert to["default"] == []
        assert "maxItems" not in to

    async def test_two_calls_do_not_share_one_recipient_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        forward = _creates(graph, _CREATE_FORWARD)
        reply = _creates(graph, _CREATE_REPLY)
        _ = _fills(graph)

        _ = await _reply(client, mode="forward", to=[_GRACE])
        _ = await _reply(client)

        assert _addressed(_sent(forward), "ToRecipients") == [_GRACE]
        assert not [key for key in _sent(reply) if "recipient" in key.casefold()]


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_microsoft_documents_for_these_writes(self) -> None:
        assert replier.GRAPH_PERMISSIONS == ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

    def test_a_missing_message_is_never_blamed_on_a_folder_move(self) -> None:
        assert "A moved message gets a new id" not in replier.GRAPH_NOT_FOUND
        assert "does not mean that the message moved" not in replier.GRAPH_NOT_FOUND
        assert "If a message moves to another folder of this mailbox, its handle does not" in (
            replier.GRAPH_NOT_FOUND
        )
        assert "If somebody deletes the message permanently, or moves it to an archive" in (
            replier.GRAPH_NOT_FOUND
        )

    def test_the_two_writes_this_file_makes_directly_are_named_as_their_own_steps(self) -> None:
        assert replier.STEP_CREATE_REPLY == "create_reply"
        assert replier.STEP_FILL_REPLY == "fill_reply"
        assert not hasattr(replier, "STEP_ATTACH_REPLY")

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

    async def test_the_description_says_it_cannot_send_and_that_the_human_does(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "cannot send" in lowered
        assert "the user presses send in outlook" in lowered

    async def test_the_description_says_a_forward_brings_its_own_attachments_regardless(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        mode_description = cast("str", _properties(parameters)["mode"]["description"])
        assert "carries the original's own attachments" in mode_description.casefold()

    async def test_the_description_rules_out_the_copy_fields_and_names_the_reply_all_tool(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "offers no cc or bcc" in description.casefold()
        assert (
            "If this deployment exposes outlook_draft_reply_all, that tool drafts a reply-all."
        ) in description
        assert "no reply-all" not in description.casefold()

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

    async def test_the_description_says_a_shared_mailbox_needs_agreement_and_the_own_one_does_not(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "This tool asks the user to agree before it changes a shared or delegated mailbox. "
            + "It changes the user's own mailbox without a question."
        ) in description
        assert "`mailbox`" in description

    def test_a_stale_handle_is_told_where_to_find_the_message_again(self) -> None:
        assert "outlook_search_mail" in replier.GRAPH_NOT_FOUND


class TestMailboxTargeting:
    async def test_no_mailbox_replies_in_the_signed_in_users_own_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        created = _creates(graph)
        filled = _fills(graph)

        _ = await _reply(client)

        assert created.called
        assert filled.called

    async def test_a_mailbox_replies_in_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        created = graph.post(_SHARED_CREATE_REPLY).mock(
            return_value=httpx.Response(201, json=_draft())
        )
        filled = graph.patch(_SHARED_FILL).mock(return_value=httpx.Response(200, json=_filled()))

        answer = await _reply(client, confirm=_agrees, mailbox=_SHARED_MAILBOX)

        assert created.called
        assert filled.called
        assert answer.body_written is True


def _questions() -> tuple[list[str], Confirm]:
    asked: list[str] = []

    async def capturing(question: str, about: str) -> Confirmed:
        asked.append(question)
        assert about
        return None

    return asked, capturing


class TestThePersonBeforeTheDraftIsCreated:
    async def test_the_signed_in_users_own_mailbox_asks_nobody_and_reads_nothing_first(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)

        _ = await _reply(client, confirm=_never_asked)

        assert _methods(graph) == ["POST", "PATCH"]

    async def test_a_shared_mailbox_is_asked_about_once_and_gets_one_draft(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph)
        create = _shared_writes(graph)
        asked, capturing = _questions()

        _ = await _reply(client, mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert len(asked) == 1
        assert read.call_count == 1
        assert create.call_count == 1
        assert _written(graph) == ["POST", "PATCH"]

    async def test_a_refusal_writes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)

        with pytest.raises(ToolError, match=_NOT_CREATED):
            _ = await _reply(client, mailbox=_SHARED_MAILBOX, confirm=_refuses)

        assert _written(graph) == []

    async def test_a_question_the_client_must_carry_writes_nothing_and_is_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)

        answer = await replier.draft_reply(
            client,
            message_ref=_MESSAGE_REF,
            mode="reply",
            body_html=_BODY,
            confirm=_asks_the_client,
            mailbox=_SHARED_MAILBOX,
        )

        assert isinstance(answer, InputRequiredResult)
        assert _written(graph) == []

    async def test_a_message_that_is_gone_is_a_not_found_before_any_question_or_write(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_SHARED_MESSAGE).mock(return_value=httpx.Response(404, json=_REFUSED))
        _ = _shared_writes(graph)

        with pytest.raises(GraphNotFound):
            _ = await _reply(client, mailbox=_SHARED_MAILBOX, confirm=_never_asked)

        assert _written(graph) == []

    async def test_the_question_for_a_reply_names_the_mailbox_the_message_and_the_sender(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)
        asked, capturing = _questions()

        _ = await _reply(client, mailbox=_SHARED_MAILBOX, confirm=capturing)

        (question,) = asked
        assert "Create a reply draft in the mailbox 'alex@example.invalid'?" in question
        assert "The reply is to the message 'Invoice 4471'." in question
        assert "not the signed-in user's own" in question
        assert f"addressed to {_ADA}." in question
        assert "Nothing is sent." in question
        assert "anyone with access to it can see it" in question
        sentences = re.split(r"(?<=[.?])\s+", question)
        assert max(len(sentence.split()) for sentence in sentences) <= 20, sentences

    async def test_the_question_for_a_reply_names_the_reply_to_address_over_the_sender(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _original(reply_to=["invoices@example.invalid"]))
        _ = _shared_writes(graph)
        asked, capturing = _questions()

        _ = await _reply(client, mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert "addressed to invoices@example.invalid." in asked[0]
        assert _ADA not in asked[0]

    async def test_the_question_for_a_forward_names_the_forward_and_where_it_goes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph, _SHARED_CREATE_FORWARD)
        asked, capturing = _questions()

        _ = await _reply(
            client, mode="forward", to=[_GRACE, _PAM], mailbox=_SHARED_MAILBOX, confirm=capturing
        )

        (question,) = asked
        assert "Create a forward draft in the mailbox" in question
        assert "The forward is of the message 'Invoice 4471'." in question
        assert f"addressed to {_GRACE}, {_PAM}." in question
        assert _ADA not in question

    async def test_a_message_with_no_subject_and_no_sender_is_still_described(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _original(subject=None, sender=None))
        _ = _shared_writes(graph)
        asked, capturing = _questions()

        _ = await _reply(client, mailbox=_SHARED_MAILBOX, confirm=capturing)

        assert "The reply is to the message with no subject." in asked[0]
        assert "addressed to an address that Microsoft chooses." in asked[0]

    async def test_a_long_mailbox_and_subject_are_cut_in_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        long_mailbox = f"{'m' * 300}@example.invalid"
        _ = graph.get(f"/users/{long_mailbox}/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D").mock(
            return_value=httpx.Response(200, json=_original(subject="s" * 255))
        )
        _ = graph.post(
            f"/users/{long_mailbox}/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/createReply"
        ).mock(return_value=httpx.Response(201, json=_draft()))
        _ = graph.patch(
            f"/users/{long_mailbox}/messages/AAMkAGI2SYNTHETIC-reply-draft-0001%3D"
        ).mock(return_value=httpx.Response(200, json=_filled()))
        asked, capturing = _questions()

        _ = await _reply(client, mailbox=long_mailbox, confirm=capturing)

        assert "m" * 300 not in asked[0]
        assert "s" * 255 not in asked[0]

    async def test_a_changed_body_mode_or_addressee_binds_the_agreement_to_a_different_state(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _shared_writes(graph)
        _ = _shared_writes(graph, _SHARED_CREATE_FORWARD)
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert question
            bound.append(about)
            return None

        _ = await _reply(client, mailbox=_SHARED_MAILBOX, confirm=capturing)
        _ = await _reply(client, mailbox=_SHARED_MAILBOX, confirm=capturing)
        _ = await _reply(
            client, body_html="<p>Other.</p>", mailbox=_SHARED_MAILBOX, confirm=capturing
        )
        _ = await _reply(
            client, mode="forward", to=[_GRACE], mailbox=_SHARED_MAILBOX, confirm=capturing
        )
        _ = await _reply(
            client, mode="forward", to=[_PAM], mailbox=_SHARED_MAILBOX, confirm=capturing
        )

        assert bound[0] == bound[1]
        assert len({*bound}) == 4


class TestWhatItAnswers:
    async def test_the_recipients_are_read_off_graph_and_never_echoed_from_the_arguments(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _CREATE_FORWARD)
        _ = _fills(
            graph,
            _filled(to=[_recipient("Pam Beesly", _PAM)], cc=[_recipient("Ada Lovelace", _ADA)]),
        )

        answer = await _reply(client, mode="forward", to=[_GRACE])

        assert [address.address for address in answer.to] == [_PAM]
        assert [address.address for address in answer.cc] == [_ADA]

    async def test_a_reply_reports_the_reply_to_address_graph_chose_over_the_sender(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph, _filled(to=[_recipient("Invoices", "invoices@example.invalid")]))

        answer = await _reply(client)

        assert [address.address for address in answer.to] == ["invoices@example.invalid"]

    async def test_the_subject_and_the_body_are_read_off_the_fill(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph, _filled(subject="RE: Invoice 4471 (stored)", content="Stored text."))

        answer = await _reply(client, body_html=_BODY)

        assert answer.subject == "RE: Invoice 4471 (stored)"
        assert answer.body == "Stored text."
        assert answer.body_written is True
        assert answer.failure is None

    async def test_the_handle_addresses_a_draft_and_cannot_be_read_as_a_message(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)

        answer = await _reply(client)

        handle = mail_draft_handle(answer.uri)
        assert handle is not None
        assert handle.draft_id == _DRAFT_ID
        assert mail_message_handle(answer.uri) is None

    async def test_it_answers_the_link_graph_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)

        answer = await _reply(client)

        assert answer.web_link == _WEB_LINK
        assert answer.mode == "reply"

    async def test_a_draft_graph_gave_no_link_answers_null_rather_than_a_built_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, payload=_draft(web_link=None))
        _ = _fills(graph, _filled(web_link=None))

        answer = await _reply(client)

        assert answer.web_link is None

    def test_no_attachment_or_blind_copy_is_addressable_in_the_answer_at_all(self) -> None:
        fields = [name.casefold() for name in MailReplyDraft.model_fields]
        assert not [name for name in fields if "attach" in name]
        assert not [name for name in fields if "bcc" in name]


class TestWhenTheTextCannotBeWritten:
    async def test_a_refused_fill_answers_the_draft_it_left_behind_rather_than_raising(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, payload=_draft(to=[_recipient("Ada Lovelace", _ADA)]))
        _ = graph.patch(_FILL).mock(return_value=httpx.Response(403, json=_REFUSED))

        answer = await _reply(client)

        assert answer.body_written is False
        assert answer.failure is not None
        assert [address.address for address in answer.to] == [_ADA]

    async def test_the_empty_draft_is_still_addressable_so_the_user_can_be_pointed_at_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = graph.patch(_FILL).mock(return_value=httpx.Response(403, json=_REFUSED))

        answer = await _reply(client)

        handle = mail_draft_handle(answer.uri)
        assert handle is not None
        assert handle.draft_id == _DRAFT_ID
        assert answer.web_link == _WEB_LINK

    async def test_the_text_that_never_landed_is_not_reported_as_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = graph.patch(_FILL).mock(return_value=httpx.Response(403, json=_REFUSED))

        answer = await _reply(client, body_html="Wire the payment to the new account.")

        assert answer.body is None


class TestTheFailuresItPassesOn:
    async def test_a_refused_create_is_a_forbidden_and_nothing_is_filled(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = graph.post(_CREATE_REPLY).mock(return_value=httpx.Response(403, json=_REFUSED))
        fill = _fills(graph)

        with pytest.raises(GraphForbidden):
            _ = await _reply(client)

        assert create.call_count == 1
        assert fill.call_count == 0
