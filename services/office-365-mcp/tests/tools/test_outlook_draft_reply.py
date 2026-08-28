"""Every payload here is synthesised. No draft in this file was ever created in a real mailbox.

The rules this file is about are the ones the tool's shape is: there is no reply-all and no way to
spell one, `to` belongs to a forward and nowhere else, no Cc, Bcc or attachment argument exists,
the recipients reported come off Microsoft's answer, neither write is retried, and a fill that
fails is reported as the addressed empty draft it leaves behind rather than raised over.
"""

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
from office_365_mcp.shared.seam import WRITE_ADDITIVE
from office_365_mcp.tools import outlook_draft_reply as replier
from office_365_mcp.tools.outlook_draft_reply import MailReplyDraft, MailReplyMode

_MESSAGE_ID = "AAMkAGI2SYNTHETIC-immutable-0001="

_DRAFT_ID = "AAMkAGI2SYNTHETIC-reply-draft-0001="

# Spelled by the one module allowed to spell them, so a change to the grammar reaches this file.
_MESSAGE_REF = MailMessageHandle(_MESSAGE_ID).uri

# The SDK re-encodes each id for the URL, so this is what the decoded handle comes back as.
_CREATE_REPLY = "/me/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/createReply"
_CREATE_FORWARD = "/me/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/createForward"
_FILL = "/me/messages/AAMkAGI2SYNTHETIC-reply-draft-0001%3D"

_WEB_LINK = "https://outlook.office365.invalid/owa/?ItemID=synthetic-reply-draft"

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"
_PAM = "pam@example.invalid"

_SUBJECT = "RE: Invoice 4471"
_BODY = "Friday works for me."

# What Graph seeds a reply draft with before anything is written into it: the original, quoted.
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
    """Graph's 201: a whole message, `isDraft` set, its body still Outlook's own seeded quote."""
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
    """What Graph answers the fill with: the same draft, its body now the text that was written."""
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


async def _reply(client: GraphServiceClient, **overrides: object) -> MailReplyDraft:
    """One valid call, so a test that is about something else says only that thing."""
    arguments: dict[str, object] = {
        "message_ref": _MESSAGE_REF,
        "mode": "reply",
        "body_text": _BODY,
    }
    arguments.update(overrides)
    return await replier.draft_reply(
        client,
        message_ref=cast("str", arguments["message_ref"]),
        mode=cast("MailReplyMode", arguments["mode"]),
        body_text=cast("str", arguments["body_text"]),
        to=cast("Sequence[str]", arguments.get("to", ())),
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
    """The published schema and annotations, which is the surface a client actually reads."""
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
        """Microsoft's known-issues page says the comment "isn't part of the body of the response
        message draft", so sending one would write prose nobody could read back."""
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

    async def test_the_body_reaches_the_mailbox_as_text_and_never_as_html(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A model that can write markup can write a link whose text and target differ, in a
        message a human sends under their own name."""
        _ = _creates(graph)
        fill = _fills(graph)

        _ = await _reply(client, body_text="Read https://payments.invalid/pay before Friday.")

        body = cast("dict[str, object]", _sent(fill)["body"])
        assert body["contentType"] == "text"
        assert body["content"] == "Read https://payments.invalid/pay before Friday."

    async def test_the_fill_names_the_body_and_nothing_else_about_the_draft(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """kiota omits an unset property, so the recipients Microsoft computed are not overwritten
        by a PATCH that never mentions them."""
        _ = _creates(graph, _CREATE_FORWARD)
        fill = _fills(graph)

        _ = await _reply(client, mode="forward", to=[_GRACE])

        # `@odata.type` is the SDK's own annotation on the payload, not a property being written.
        assert set(_sent(fill)) == {"@odata.type", "body"}

    async def test_neither_write_offers_an_attachment_a_copy_or_a_blind_copy(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """There is no argument for any of them, so there is nothing to put in either request —
        checked on the wire rather than on the signature."""
        create = _creates(graph, _CREATE_FORWARD)
        fill = _fills(graph)

        _ = await _reply(client, mode="forward", to=[_GRACE])

        keys = [key.casefold() for key in (*_sent(create), *_sent(fill))]
        assert not [key for key in keys if "attach" in key]
        assert not [key for key in keys if "cc" in key]

    async def test_both_writes_ask_for_immutable_ids(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The handle coming in carries an immutable id and the handle going out has to be one
        too: without the header Graph reads the path id in the wrong space and 404s."""
        create = _creates(graph)
        fill = _fills(graph)

        _ = await _reply(client)

        for route in (create, fill):
            assert 'IdType="ImmutableId"' in route.calls.last.request.headers["Prefer"]

    async def test_it_asks_graph_for_nothing_but_the_create_and_the_fill(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Sending is a Graph call this tool must never make. Counting every request is the check
        that survives somebody adding one under a path this test did not think to name."""
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
        """Graph publishes no idempotency key here, and the SDK retries POST as readily as GET: a
        503 arriving after Graph accepted the create leaves the user a duplicate draft."""
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
        """Reply-all is the one worth naming: its recipients are the To and Cc of a message
        somebody else wrote, so it is an audience an attacker picks."""
        _ = _creates(graph)

        with pytest.raises(ToolError, match="reply-all"):
            _ = await _reply(client, mode=mode)

        assert len(graph.calls) == 0

    async def test_to_on_a_reply_is_refused_and_the_refusal_names_the_mode(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """On a reply the recipient is Microsoft's to compute from the original, which is the
        point of replying rather than composing."""
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

    async def test_a_recipient_list_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _reply(client, mode="forward", to=[_GRACE] * (replier.MAX_RECIPIENTS + 1))


class TestTheSchemaItPublishes:
    async def test_it_takes_four_arguments_and_no_others(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert set(_properties(parameters)) == {"message_ref", "mode", "body_text", "to"}

    async def test_the_only_modes_it_offers_are_reply_and_forward(
        self, transport: httpx.AsyncClient
    ) -> None:
        """Reply-all is unspellable rather than refused: a published mode is an invitation the
        model takes, and its audience is the To and Cc of a message a stranger wrote."""
        parameters, _tool = await _registered(transport)

        mode = _properties(parameters)["mode"]
        assert mode["$ref"] == "#/$defs/MailReplyMode"
        published = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
        assert cast("Sequence[str]", published["MailReplyMode"]["enum"]) == list(replier.MODES)
        assert list(replier.MODES) == ["reply", "forward"]

    @pytest.mark.parametrize(
        "word", ["cc", "bcc", "blind", "all", "attach", "file", "upload", "drive", "html"]
    )
    async def test_no_argument_offers_a_copy_an_attachment_or_markup(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert not [name for name in _properties(parameters) if word in name.casefold()]

    async def test_the_message_the_mode_and_the_text_are_required_and_to_is_not(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert cast("Sequence[str]", parameters["required"]) == [
            "message_ref",
            "mode",
            "body_text",
        ]

    async def test_to_defaults_to_nobody_and_is_bounded(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        to = _properties(parameters)["to"]
        assert to["default"] == []
        assert to["maxItems"] == replier.MAX_RECIPIENTS

    async def test_two_calls_do_not_share_one_recipient_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The default is declared on the `Field` rather than in the signature, where a `[]` would
        be one list for the life of the process."""
        forward = _creates(graph, _CREATE_FORWARD)
        reply = _creates(graph, _CREATE_REPLY)
        _ = _fills(graph)

        _ = await _reply(client, mode="forward", to=[_GRACE])
        _ = await _reply(client)

        assert _addressed(_sent(forward), "ToRecipients") == [_GRACE]
        assert not [key for key in _sent(reply) if "recipient" in key.casefold()]


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_microsoft_documents_for_these_writes(self) -> None:
        assert replier.GRAPH_PERMISSIONS == ("Mail.ReadWrite",)

    def test_the_two_writes_are_named_as_their_own_steps(self) -> None:
        assert replier.STEP_CREATE_REPLY == "create_reply"
        assert replier.STEP_FILL_REPLY == "fill_reply"

    async def test_it_announces_itself_as_a_write_that_destroys_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.readOnlyHint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructiveHint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotentHint is WRITE_ADDITIVE["idempotentHint"]

    async def test_the_description_says_it_cannot_send_and_that_the_human_does(
        self, transport: httpx.AsyncClient
    ) -> None:
        """What a model is told it cannot do is the only place these limits exist for it: nothing
        downstream re-reads the tool file."""
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "cannot send" in lowered
        assert "sends the draft themselves from outlook" in lowered

    async def test_the_description_says_a_forward_brings_the_attachments_this_tool_cannot_add(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "no attachment" in lowered
        assert "carries the original message's own attachments" in lowered

    async def test_the_description_rules_out_reply_all_and_the_copy_fields(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "no reply-all" in lowered
        assert "no cc and no bcc" in lowered

    def test_the_known_issue_the_second_write_exists_for_is_cited(self) -> None:
        """The fill looks removable until you know Microsoft drops the comment, so the citation is
        part of the tool rather than of a commit message nobody reads again."""
        docstring = replier.__doc__ or ""
        assert "learn.microsoft.com/en-us/graph/known-issues" in docstring
        assert "isn't part of the body of the response message draft" in docstring

    def test_a_stale_handle_is_told_where_to_find_the_message_again(self) -> None:
        assert "outlook_search_mail" in replier.GRAPH_NOT_FOUND


class TestWhatItAnswers:
    async def test_the_recipients_are_read_off_graph_and_never_echoed_from_the_arguments(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A forward addressed somewhere other than where this call asked is exactly what has to
        be visible before a human presses Send."""
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
        """Microsoft addresses a reply to the original's reply-to when it has one, which no caller
        can predict — so it is reported rather than assumed."""
        _ = _creates(graph)
        _ = _fills(graph, _filled(to=[_recipient("Invoices", "invoices@example.invalid")]))

        answer = await _reply(client)

        assert [address.address for address in answer.to] == ["invoices@example.invalid"]

    async def test_the_subject_and_the_body_are_read_off_the_fill(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _ = _fills(graph, _filled(subject="RE: Invoice 4471 (stored)", content="Stored text."))

        answer = await _reply(client, body_text=_BODY)

        assert answer.subject == "RE: Invoice 4471 (stored)"
        assert answer.body == "Stored text."
        assert answer.body_written is True
        assert answer.failure is None

    async def test_the_handle_addresses_a_draft_and_cannot_be_read_as_a_message(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph gives a draft the same id space as any other message. Keeping the families apart
        is what stops a message a reader found being spelled as something a sender accepts."""
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
        """The create has already put an addressed draft in the mailbox by then, and raising would
        report a mailbox that did not change when one did."""
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
        """Answering with `body_text` here would say the draft holds prose it does not hold, and
        the seeded quote it does hold is the original message rather than anything written."""
        _ = _creates(graph)
        _ = graph.patch(_FILL).mock(return_value=httpx.Response(403, json=_REFUSED))

        answer = await _reply(client, body_text="Wire the payment to the new account.")

        assert answer.body is None


class TestTheFailuresItPassesOn:
    async def test_a_refused_create_is_a_forbidden_and_nothing_is_filled(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Nothing exists yet when the create fails, so this one raises: there is no half-written
        draft to report."""
        create = graph.post(_CREATE_REPLY).mock(return_value=httpx.Response(403, json=_REFUSED))
        fill = _fills(graph)

        with pytest.raises(GraphForbidden):
            _ = await _reply(client)

        assert create.call_count == 1
        assert fill.call_count == 0
