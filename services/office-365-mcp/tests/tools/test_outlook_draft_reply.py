import base64
import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphUnavailable
from office_365_mcp.shared.handles import MailMessageHandle, mail_draft_handle, mail_message_handle
from office_365_mcp.shared.mail import MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS, MailAttachmentInput
from office_365_mcp.shared.seam import WRITE_ADDITIVE
from office_365_mcp.tools import outlook_draft_reply as replier
from office_365_mcp.tools.outlook_draft_reply import MailReplyDraft, MailReplyMode

_TINY_FILE = base64.b64encode(bytes.fromhex("47494638396101000100")).decode()


def _attachment(
    name: str = "budget.pdf", content_type: str = "application/pdf", content_bytes: str = _TINY_FILE
) -> MailAttachmentInput:
    return MailAttachmentInput(name=name, content_type=content_type, content_bytes=content_bytes)


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


def _attached(
    *, name: str = "budget.pdf", content_type: str = "application/pdf"
) -> dict[str, object]:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "id": f"AAMkAGI2SYNTHETIC-attachment-{name}",
        "name": name,
        "contentType": content_type,
        "size": len(base64.b64decode(_TINY_FILE)),
        "isInline": False,
    }


def _attaches(graph: respx.MockRouter, *payloads: dict[str, object]) -> respx.Route:
    responses = [httpx.Response(201, json=payload) for payload in payloads] or [
        httpx.Response(201, json=_attached())
    ]
    return graph.post(f"{_FILL}/attachments").mock(side_effect=responses)


_UPLOAD_URL = "https://attachment-upload.invalid/session/reply?authtoken=synthetic"


def _session_route(graph: respx.MockRouter, *, upload_url: str = _UPLOAD_URL) -> respx.Route:
    return graph.post(f"{_FILL}/attachments/createUploadSession").mock(
        return_value=httpx.Response(
            201,
            json={
                "uploadUrl": upload_url,
                "expirationDateTime": "2026-09-24T00:00:00Z",
                "nextExpectedRanges": ["0-"],
            },
        )
    )


def _chunk_route(graph: respx.MockRouter, *, status: int = 201) -> respx.Route:
    return graph.route(method="PUT", host="attachment-upload.invalid").mock(
        return_value=httpx.Response(status)
    )


def _large_content() -> bytes:
    return b"a" * (MAX_ATTACHMENT_BYTES + 1)


def _large_attachment(
    name: str = "recording.mp4", content_type: str = "video/mp4"
) -> MailAttachmentInput:
    return MailAttachmentInput(
        name=name,
        content_type=content_type,
        content_bytes=base64.b64encode(_large_content()).decode(),
    )


async def _reply(
    client: GraphServiceClient, transport: httpx.AsyncClient, **overrides: object
) -> MailReplyDraft:
    arguments: dict[str, object] = {
        "message_ref": _MESSAGE_REF,
        "mode": "reply",
        "body_html": _BODY,
    }
    arguments.update(overrides)
    return await replier.draft_reply(
        client,
        transport,
        message_ref=cast("str", arguments["message_ref"]),
        mode=cast("MailReplyMode", arguments["mode"]),
        body_html=cast("str", arguments["body_html"]),
        to=cast("Sequence[str]", arguments.get("to", ())),
        attachments=cast("Sequence[MailAttachmentInput]", arguments.get("attachments", ())),
    )


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
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        _ = _fills(graph)

        _ = await _reply(client, transport)

        assert create.call_count == 1

    async def test_a_forward_is_created_on_the_forward_route_and_carries_its_recipients(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph, _CREATE_FORWARD)
        _ = _fills(graph)

        _ = await _reply(client, transport, mode="forward", to=[_GRACE, _PAM])

        assert create.call_count == 1
        assert _addressed(_sent(create), "ToRecipients") == [_GRACE, _PAM]

    async def test_the_create_carries_no_comment_because_graph_drops_it(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        _ = _fills(graph)

        _ = await _reply(client, transport)

        assert not [key for key in _sent(create) if "comment" in key.casefold()]

    async def test_the_fill_is_a_second_write_and_not_optional(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)

        _ = await _reply(client, transport)

        assert create.call_count == 1
        assert fill.call_count == 1
        assert len(graph.calls) == 2, "a draft with text in it costs exactly two requests"

    async def test_the_body_reaches_the_mailbox_as_html(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        fill = _fills(graph)

        _ = await _reply(
            client, transport, body_html="Read https://payments.invalid/pay before Friday."
        )

        body = cast("dict[str, object]", _sent(fill)["body"])
        assert body["contentType"] == "html"
        assert body["content"] == "Read https://payments.invalid/pay before Friday."

    async def test_the_fill_names_the_body_and_nothing_else_about_the_draft(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _CREATE_FORWARD)
        fill = _fills(graph)

        _ = await _reply(client, transport, mode="forward", to=[_GRACE])

        assert set(_sent(fill)) == {"@odata.type", "body"}

    async def test_neither_write_offers_an_attachment_a_copy_or_a_blind_copy(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph, _CREATE_FORWARD)
        fill = _fills(graph)

        _ = await _reply(client, transport, mode="forward", to=[_GRACE])

        keys = [key.casefold() for key in (*_sent(create), *_sent(fill))]
        assert not [key for key in keys if "attach" in key]
        assert not [key for key in keys if "cc" in key]

    async def test_both_writes_ask_for_immutable_ids(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)

        _ = await _reply(client, transport)

        for route in (create, fill):
            assert 'IdType="ImmutableId"' in route.calls.last.request.headers["Prefer"]

    async def test_it_asks_graph_for_nothing_but_the_create_and_the_fill(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)
        send = graph.post("/me/messages/AAMkAGI2SYNTHETIC-reply-draft-0001%3D/send").mock(
            return_value=httpx.Response(202)
        )

        _ = await _reply(client, transport)

        assert send.call_count == 0
        assert len(graph.calls) == 2

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = graph.post(_CREATE_REPLY).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _reply(client, transport)

        assert create.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_fill_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        fill = graph.patch(_FILL).mock(return_value=httpx.Response(503))

        answer = await _reply(client, transport)

        assert fill.call_count == 1
        assert answer.body_written is False


class TestTheModesAndAddressesItRefuses:
    @pytest.mark.parametrize("mode", ["replyAll", "reply_all", "reply-all", "REPLY", ""])
    async def test_a_mode_that_is_not_one_of_the_two_reaches_graph_at_all(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        mode: str,
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="reply-all"):
            _ = await _reply(client, transport, mode=mode)

        assert len(graph.calls) == 0

    async def test_to_on_a_reply_is_refused_and_the_refusal_names_the_mode(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="`reply`"):
            _ = await _reply(client, transport, to=[_GRACE])

        assert len(graph.calls) == 0, "a refused argument creates nothing in the mailbox"

    async def test_a_forward_with_nobody_to_forward_to_is_refused(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _CREATE_FORWARD)

        with pytest.raises(ToolError, match="forward"):
            _ = await _reply(client, transport, mode="forward")

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
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        address: str,
    ) -> None:
        _ = _creates(graph, _CREATE_FORWARD)

        with pytest.raises(ToolError):
            _ = await _reply(client, transport, mode="forward", to=[address])

        assert len(graph.calls) == 0

    async def test_the_refusal_says_where_an_address_may_come_from(
        self, client: GraphServiceClient, transport: httpx.AsyncClient
    ) -> None:
        with pytest.raises(ToolError, match="outlook_find_recipient"):
            _ = await _reply(client, transport, mode="forward", to=["Grace Hopper"])

    async def test_surrounding_whitespace_is_trimmed_rather_than_refused(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph, _CREATE_FORWARD)
        _ = _fills(graph)

        _ = await _reply(client, transport, mode="forward", to=[f"  {_GRACE}  "])

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
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        ref: str,
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="outlook:///messages"):
            _ = await _reply(client, transport, message_ref=ref)

        assert len(graph.calls) == 0

    async def test_a_recipient_list_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, transport: httpx.AsyncClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _reply(
                client, transport, mode="forward", to=[_GRACE] * (replier.MAX_RECIPIENTS + 1)
            )


class TestTheSchemaItPublishes:
    async def test_it_takes_six_arguments_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        assert set(_properties(parameters)) == {
            "message_ref",
            "mode",
            "body_html",
            "to",
            "attachments",
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

    async def test_attachments_is_the_only_argument_naming_a_file(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert [name for name in _properties(parameters) if "attach" in name.casefold()] == [
            "attachments"
        ]

    async def test_the_message_the_mode_and_the_text_are_required_and_to_is_not(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert cast("Sequence[str]", parameters["required"]) == [
            "message_ref",
            "mode",
            "body_html",
        ]

    async def test_to_defaults_to_nobody_and_is_bounded(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        to = _properties(parameters)["to"]
        assert to["default"] == []
        assert to["maxItems"] == replier.MAX_RECIPIENTS

    async def test_two_calls_do_not_share_one_recipient_list(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        forward = _creates(graph, _CREATE_FORWARD)
        reply = _creates(graph, _CREATE_REPLY)
        _ = _fills(graph)

        _ = await _reply(client, transport, mode="forward", to=[_GRACE])
        _ = await _reply(client, transport)

        assert _addressed(_sent(forward), "ToRecipients") == [_GRACE]
        assert not [key for key in _sent(reply) if "recipient" in key.casefold()]


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_microsoft_documents_for_these_writes(self) -> None:
        assert replier.GRAPH_PERMISSIONS == ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

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
        parameters, tool = await _registered(transport)

        mode_description = cast("str", _properties(parameters)["mode"]["description"])
        assert "carries the original's own attachments" in mode_description.casefold()

    async def test_the_description_rules_out_reply_all_and_the_copy_fields(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "offers no reply-all, cc, or bcc" in lowered

    async def test_the_description_names_the_attachment_ceiling(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert f"up to {MAX_ATTACHMENTS}" in lowered
        assert "url" in lowered

    def test_a_stale_handle_is_told_where_to_find_the_message_again(self) -> None:
        assert "outlook_search_mail" in replier.GRAPH_NOT_FOUND


class TestMailboxTargeting:
    async def test_no_mailbox_replies_in_the_signed_in_users_own_mailbox(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        created = _creates(graph)
        filled = _fills(graph)

        _ = await _reply(client, transport)

        assert created.called
        assert filled.called

    async def test_a_mailbox_replies_in_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        created = graph.post(
            "/users/alex@example.invalid/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/createReply"
        ).mock(return_value=httpx.Response(201, json=_draft()))
        filled = graph.patch(
            "/users/alex@example.invalid/messages/AAMkAGI2SYNTHETIC-reply-draft-0001%3D"
        ).mock(return_value=httpx.Response(200, json=_filled()))

        answer = await replier.draft_reply(
            client,
            transport,
            message_ref=_MESSAGE_REF,
            mode="reply",
            body_html=_BODY,
            mailbox="alex@example.invalid",
        )

        assert created.called
        assert filled.called
        assert answer.body_written is True


class TestWhatItAnswers:
    async def test_the_recipients_are_read_off_graph_and_never_echoed_from_the_arguments(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _CREATE_FORWARD)
        _ = _fills(
            graph,
            _filled(to=[_recipient("Pam Beesly", _PAM)], cc=[_recipient("Ada Lovelace", _ADA)]),
        )

        answer = await _reply(client, transport, mode="forward", to=[_GRACE])

        assert [address.address for address in answer.to] == [_PAM]
        assert [address.address for address in answer.cc] == [_ADA]

    async def test_a_reply_reports_the_reply_to_address_graph_chose_over_the_sender(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph, _filled(to=[_recipient("Invoices", "invoices@example.invalid")]))

        answer = await _reply(client, transport)

        assert [address.address for address in answer.to] == ["invoices@example.invalid"]

    async def test_the_subject_and_the_body_are_read_off_the_fill(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph, _filled(subject="RE: Invoice 4471 (stored)", content="Stored text."))

        answer = await _reply(client, transport, body_html=_BODY)

        assert answer.subject == "RE: Invoice 4471 (stored)"
        assert answer.body == "Stored text."
        assert answer.body_written is True
        assert answer.failure is None

    async def test_the_handle_addresses_a_draft_and_cannot_be_read_as_a_message(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)

        answer = await _reply(client, transport)

        handle = mail_draft_handle(answer.uri)
        assert handle is not None
        assert handle.draft_id == _DRAFT_ID
        assert mail_message_handle(answer.uri) is None

    async def test_it_answers_the_link_graph_returned(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)

        answer = await _reply(client, transport)

        assert answer.web_link == _WEB_LINK
        assert answer.mode == "reply"

    async def test_a_draft_graph_gave_no_link_answers_null_rather_than_a_built_one(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, payload=_draft(web_link=None))
        _ = _fills(graph, _filled(web_link=None))

        answer = await _reply(client, transport)

        assert answer.web_link is None

    def test_attachments_and_attachment_failure_are_the_only_attachment_fields(self) -> None:
        fields = [name.casefold() for name in MailReplyDraft.model_fields]
        assert {name for name in fields if "attach" in name} == {
            "attachments",
            "attachment_failure",
        }
        assert not [name for name in fields if "bcc" in name]


class TestNewAttachments:
    async def test_a_default_call_attaches_nothing(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)
        attach = _attaches(graph)

        answer = await _reply(client, transport)

        assert attach.call_count == 0
        assert answer.attachments == []
        assert answer.attachment_failure is None

    async def test_a_new_attachment_is_its_own_call_after_the_fill(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)
        attach = _attaches(graph, _attached(name="budget.pdf"))

        _ = await _reply(client, transport, attachments=[_attachment(name="budget.pdf")])

        assert create.call_count == 1
        assert fill.call_count == 1
        assert attach.call_count == 1
        sent = cast("dict[str, object]", json.loads(attach.calls.last.request.content))
        assert sent["name"] == "budget.pdf"
        assert sent["contentType"] == "application/pdf"
        assert sent["@odata.type"] == "#microsoft.graph.fileAttachment"

    async def test_attaching_asks_for_immutable_ids_and_never_retries(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)
        attach = _attaches(graph)

        _ = await _reply(client, transport, attachments=[_attachment()])

        assert 'IdType="ImmutableId"' in attach.calls.last.request.headers["Prefer"]

    async def test_several_new_attachments_are_sent_in_order_one_call_each(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)
        attach = _attaches(graph, _attached(name="one.pdf"), _attached(name="two.pdf"))

        answer = await _reply(
            client,
            transport,
            attachments=[_attachment(name="one.pdf"), _attachment(name="two.pdf")],
        )

        assert attach.call_count == 2
        assert [one.name for one in answer.attachments] == ["one.pdf", "two.pdf"]

    async def test_a_forward_can_both_carry_the_original_and_attach_something_new(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph, _CREATE_FORWARD)
        fill = _fills(graph)
        attach = _attaches(graph, _attached(name="budget.pdf"))

        _ = await _reply(
            client,
            transport,
            mode="forward",
            to=[_GRACE],
            attachments=[_attachment(name="budget.pdf")],
        )

        assert create.call_count == 1
        assert fill.call_count == 1
        assert attach.call_count == 1

    async def test_invalid_base64_is_refused_before_anything_reaches_graph(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)
        attach = _attaches(graph)

        with pytest.raises(ToolError, match="not.*valid base64"):
            _ = await _reply(
                client, transport, attachments=[_attachment(content_bytes="not base64!!!")]
            )

        assert create.call_count == 0, "a refused attachment creates nothing at all"
        assert fill.call_count == 0
        assert attach.call_count == 0

    async def test_a_file_at_or_past_the_ceiling_is_refused_before_anything_reaches_graph(
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(replier, "MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION", 5 * 1024 * 1024)
        create = _creates(graph)
        oversized = base64.b64encode(b"x" * (5 * 1024 * 1024)).decode()

        with pytest.raises(ToolError, match="5 MB"):
            _ = await _reply(client, transport, attachments=[_attachment(content_bytes=oversized)])

        assert create.call_count == 0

    async def test_a_file_at_the_old_reject_ceiling_now_attaches_through_a_session(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        _ = _fills(graph)
        session = _session_route(graph)
        chunk = _chunk_route(graph)
        at_the_old_ceiling = base64.b64encode(b"x" * MAX_ATTACHMENT_BYTES).decode()

        answer = await _reply(
            client, transport, attachments=[_attachment(content_bytes=at_the_old_ceiling)]
        )

        assert create.call_count == 1
        assert session.call_count == 1
        assert chunk.call_count == 1
        assert answer.attachment_failure is None

    async def test_an_attachment_list_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, transport: httpx.AsyncClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _reply(client, transport, attachments=[_attachment()] * (MAX_ATTACHMENTS + 1))

    async def test_a_refused_attachment_answers_what_landed_before_it_rather_than_raising(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)
        _ = graph.post(f"{_FILL}/attachments").mock(
            side_effect=[
                httpx.Response(201, json=_attached(name="one.pdf")),
                httpx.Response(403, json=_REFUSED),
            ]
        )

        answer = await _reply(
            client,
            transport,
            attachments=[_attachment(name="one.pdf"), _attachment(name="two.pdf")],
        )

        assert [one.name for one in answer.attachments] == ["one.pdf"]
        assert answer.attachment_failure is not None
        assert answer.body_written is True

    async def test_a_refused_attachment_stops_rather_than_trying_the_rest(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph)
        attach = graph.post(f"{_FILL}/attachments").mock(
            return_value=httpx.Response(403, json=_REFUSED)
        )

        answer = await _reply(
            client,
            transport,
            attachments=[_attachment(name="one.pdf"), _attachment(name="two.pdf")],
        )

        assert attach.call_count == 1, "the second file is never attempted after the first fails"
        assert answer.attachments == []

    async def test_the_schema_bounds_attachments_the_same_way_as_recipients(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        attachments = _properties(parameters)["attachments"]
        assert attachments["default"] == []
        assert attachments["maxItems"] == MAX_ATTACHMENTS


class TestWhenTheTextCannotBeWritten:
    async def test_a_refused_fill_answers_the_draft_it_left_behind_rather_than_raising(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, payload=_draft(to=[_recipient("Ada Lovelace", _ADA)]))
        _ = graph.patch(_FILL).mock(return_value=httpx.Response(403, json=_REFUSED))

        answer = await _reply(client, transport)

        assert answer.body_written is False
        assert answer.failure is not None
        assert [address.address for address in answer.to] == [_ADA]

    async def test_the_empty_draft_is_still_addressable_so_the_user_can_be_pointed_at_it(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = graph.patch(_FILL).mock(return_value=httpx.Response(403, json=_REFUSED))

        answer = await _reply(client, transport)

        handle = mail_draft_handle(answer.uri)
        assert handle is not None
        assert handle.draft_id == _DRAFT_ID
        assert answer.web_link == _WEB_LINK

    async def test_the_text_that_never_landed_is_not_reported_as_the_body(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = graph.patch(_FILL).mock(return_value=httpx.Response(403, json=_REFUSED))

        answer = await _reply(client, transport, body_html="Wire the payment to the new account.")

        assert answer.body is None


class TestTheFailuresItPassesOn:
    async def test_a_refused_create_is_a_forbidden_and_nothing_is_filled(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = graph.post(_CREATE_REPLY).mock(return_value=httpx.Response(403, json=_REFUSED))
        fill = _fills(graph)

        with pytest.raises(GraphForbidden):
            _ = await _reply(client, transport)

        assert create.call_count == 1
        assert fill.call_count == 0


class TestLargeAttachmentsGoThroughTheUploadSession:
    async def test_a_small_and_a_large_attachment_both_land_on_the_draft_the_create_made(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)
        inline = _attaches(graph, _attached(name="budget.pdf"))
        session = _session_route(graph)
        chunk = _chunk_route(graph)

        answer = await _reply(
            client,
            transport,
            attachments=[_attachment(name="budget.pdf"), _large_attachment(name="recording.mp4")],
        )

        assert create.call_count == 1
        assert fill.call_count == 1
        assert inline.call_count == 1, "the small file took the inline path, not a session"
        assert session.call_count == 1, "the large file opened exactly one upload session"
        assert chunk.call_count == 1
        assert [one.name for one in answer.attachments] == ["budget.pdf", "recording.mp4"]
        assert answer.attachment_failure is None

    async def test_every_attachment_can_be_large(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)
        session = _session_route(graph)
        chunk = _chunk_route(graph)

        answer = await _reply(
            client,
            transport,
            attachments=[_large_attachment(name="one.mp4"), _large_attachment(name="two.mp4")],
        )

        assert create.call_count == 1
        assert fill.call_count == 1
        assert session.call_count == 2, "each large file opens its own upload session"
        assert chunk.call_count == 2
        assert [one.name for one in answer.attachments] == ["one.mp4", "two.mp4"]

    async def test_a_large_attachment_whose_upload_session_is_refused_stops_there(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        fill = _fills(graph)
        inline = _attaches(graph, _attached(name="budget.pdf"))
        session = graph.post(f"{_FILL}/attachments/createUploadSession").mock(
            return_value=httpx.Response(403, json=_REFUSED)
        )

        answer = await _reply(
            client,
            transport,
            attachments=[_attachment(name="budget.pdf"), _large_attachment(name="recording.mp4")],
        )

        assert create.call_count == 1
        assert fill.call_count == 1
        assert inline.call_count == 1, "the small attachment before it still landed"
        assert session.call_count == 1
        assert [one.name for one in answer.attachments] == ["budget.pdf"]
        assert answer.attachment_failure is not None
        assert answer.body_written is True

    async def test_a_large_attachment_that_fails_mid_upload_leaves_the_draft_with_what_landed_first(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        _ = _fills(graph)
        inline = _attaches(graph, _attached(name="budget.pdf"))
        session = _session_route(graph)
        chunk = graph.route(method="PUT", host="attachment-upload.invalid").mock(
            return_value=httpx.Response(500, text="synthetic upload-session failure")
        )

        answer = await _reply(
            client,
            transport,
            attachments=[_attachment(name="budget.pdf"), _large_attachment(name="recording.mp4")],
        )

        assert create.call_count == 1, "the draft itself was created and is not rolled back"
        assert inline.call_count == 1
        assert session.call_count == 1
        assert chunk.call_count == 1, "the failed chunk is never retried"
        assert [one.name for one in answer.attachments] == ["budget.pdf"]
        assert answer.attachment_failure is not None
        assert answer.body_written is True

    async def test_a_second_large_attachment_is_never_attempted_after_the_first_fails(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        _ = _fills(graph)
        session = graph.post(f"{_FILL}/attachments/createUploadSession").mock(
            return_value=httpx.Response(403, json=_REFUSED)
        )

        answer = await _reply(
            client,
            transport,
            attachments=[_large_attachment(name="one.mp4"), _large_attachment(name="two.mp4")],
        )

        assert create.call_count == 1
        assert session.call_count == 1, "the second file's session is never opened"
        assert answer.attachments == []
