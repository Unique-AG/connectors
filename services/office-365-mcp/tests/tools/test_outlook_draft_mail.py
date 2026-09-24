"""Every payload in this file is synthetic data. This file never creates a draft in a real
mailbox."""

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

from office_365_mcp.graph_client import GraphFailure, GraphForbidden, GraphUnavailable
from office_365_mcp.shared.handles import MailDraftHandle, mail_draft_handle, mail_message_handle
from office_365_mcp.shared.mail import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION,
    MAX_ATTACHMENTS,
    MailAttachmentInput,
)
from office_365_mcp.shared.seam import WRITE_ADDITIVE
from office_365_mcp.tools import outlook_draft_mail as drafter
from office_365_mcp.tools.outlook_draft_mail import MailDraft

_TINY_FILE = base64.b64encode(bytes.fromhex("47494638396101000100")).decode()

_LARGE_FILE = base64.b64encode(b"x" * MAX_ATTACHMENT_BYTES).decode()


def _attachment(
    name: str = "budget.pdf", content_type: str = "application/pdf", content_bytes: str = _TINY_FILE
) -> MailAttachmentInput:
    return MailAttachmentInput(name=name, content_type=content_type, content_bytes=content_bytes)


_DRAFT_ID = "AAMkAGI2SYNTHETIC-draft-0001="

_MESSAGES = "/me/messages"

_WEB_LINK = "https://outlook.office365.invalid/owa/?ItemID=synthetic-draft"

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"

_SUBJECT = "Invoice 4471"
_BODY = "Sending this over for review."

_UPLOAD_URL = "https://attachment-upload.invalid/session/mail?authtoken=synthetic"


def _session_route(graph: respx.MockRouter, *, draft_id: str = _DRAFT_ID) -> respx.Route:
    """This route mocks `createUploadSession`, Graph's first call in the upload-session path.
    `tests/shared/test_attachment_upload.py` mocks the same call, for the function that this
    file calls."""
    return graph.post(f"{_MESSAGES}/{draft_id}/attachments/createUploadSession").mock(
        return_value=httpx.Response(
            201,
            json={
                "uploadUrl": _UPLOAD_URL,
                "expirationDateTime": "2026-09-24T00:00:00Z",
                "nextExpectedRanges": ["0-"],
            },
        )
    )


def _chunk_route(graph: respx.MockRouter, *, status: int = 201) -> respx.Route:
    """This route mocks every chunk `PUT` to the pre-authenticated `uploadUrl` above, for any
    number of chunks that `_LARGE_FILE` splits into. The split itself is the concern of
    `shared/attachment_upload.py`. Its own test suite already covers the split."""
    return graph.route(method="PUT", host="attachment-upload.invalid").mock(
        return_value=httpx.Response(status)
    )


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
    """Graph's `201` response is a whole message. `isDraft` is set, and there is no
    `sentDateTime`."""
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


async def _draft(
    client: GraphServiceClient, transport: httpx.AsyncClient, **overrides: object
) -> MailDraft:
    """This function makes one valid call. A test about one thing then overrides only that
    argument."""
    arguments: dict[str, object] = {"to": [_ADA], "subject": _SUBJECT, "body_html": _BODY}
    arguments.update(overrides)
    return await drafter.draft_mail(
        client,
        transport,
        to=cast("Sequence[str]", arguments["to"]),
        subject=cast("str", arguments["subject"]),
        body_html=cast("str", arguments["body_html"]),
        cc=cast("Sequence[str]", arguments.get("cc", ())),
        attachments=cast("Sequence[MailAttachmentInput]", arguments.get("attachments", ())),
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
    """This returns the published schema and annotations. This is the surface that a client
    actually reads."""
    mcp: FastMCP = FastMCP(name="schema-under-test")
    drafter.register(mcp, transport)
    tool = await mcp.get_tool(drafter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_declares_the_immutable_id_space_the_handle_is_minted_in(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """Every other handle that this connector creates carries an immutable id. If a draft
        handle uses a different id space, it becomes the one exception to that rule.
        `outlook_send_draft` reads this handle.
        """
        route = _creates(graph, _created())

        _ = await _draft(client, transport)

        assert 'IdType="ImmutableId"' in route.calls.last.request.headers["Prefer"]

    async def test_it_creates_one_message_in_the_mailbox_collection(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, transport)

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
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        written: str,
    ) -> None:
        """Microsoft decides what is safe in a body. This connector filters nothing. Whatever the
        caller writes reaches Graph byte for byte. One example alone cannot prove that."""
        route = _creates(graph, _created())

        _ = await _draft(client, transport, body_html=written)

        body = cast("dict[str, object]", _sent(route)["body"])
        assert body["contentType"] == "html"
        assert body["content"] == written

    async def test_it_sends_the_recipients_and_the_subject_it_was_given(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, transport, to=[_ADA, _GRACE], cc=["pam@example.invalid"])

        sent = _sent(route)
        assert _addressed(sent, "toRecipients") == [_ADA, _GRACE]
        assert _addressed(sent, "ccRecipients") == ["pam@example.invalid"]
        assert sent["subject"] == _SUBJECT

    async def test_nothing_it_sends_carries_an_attachment_or_a_blind_copy(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """There is no argument for either. So there is nothing to put in the request. This test
        looks at the wire for that fact, not at the function signature."""
        route = _creates(graph, _created())

        _ = await _draft(client, transport)

        keys = [key.casefold() for key in _sent(route)]
        assert not [key for key in keys if "attach" in key]
        assert not [key for key in keys if "bcc" in key]

    async def test_it_asks_graph_for_nothing_but_the_create(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """Sending mail is a second Graph call. This tool must never make that call. This test
        counts every request. It does not look for one path by name. That count still catches a
        new call under a path this test did not name."""
        route = _creates(graph, _created())
        send_mail = graph.post("/me/sendMail").mock(return_value=httpx.Response(202))

        _ = await _draft(client, transport)

        assert route.call_count == 1
        assert send_mail.call_count == 0
        assert len(graph.calls) == 1, "the only request a draft costs is the one that creates it"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """Graph publishes no idempotency key for this call. The SDK retries a `POST` request the
        same way it retries a `GET` request. A `503` response that arrives after Graph already
        accepted the create leaves the user with a duplicate draft."""
        route = graph.post(_MESSAGES).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _draft(client, transport)

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
        self,
        client: GraphServiceClient,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        address: str,
    ) -> None:
        route = _creates(graph, _created())

        with pytest.raises(ToolError):
            _ = await _draft(client, transport, to=[address])

        assert route.call_count == 0, "a refused argument creates nothing in the mailbox"

    async def test_a_cc_entry_is_held_to_the_same_rule_and_names_its_argument(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        with pytest.raises(ToolError, match="`cc`"):
            _ = await _draft(client, transport, cc=["Grace Hopper <grace@example.invalid>"])

        assert route.call_count == 0

    async def test_the_refusal_says_where_an_address_may_come_from(
        self, client: GraphServiceClient, transport: httpx.AsyncClient
    ) -> None:
        with pytest.raises(ToolError, match="outlook_find_recipient"):
            _ = await _draft(client, transport, to=["Ada Lovelace"])

    async def test_surrounding_whitespace_is_trimmed_rather_than_refused(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, transport, to=[f"  {_ADA}  "])

        assert _addressed(_sent(route), "toRecipients") == [_ADA]

    @pytest.mark.parametrize("count", [0, drafter.MAX_RECIPIENTS + 1])
    async def test_a_recipient_list_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, count: int
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _draft(client, transport, to=[_ADA] * count)

    async def test_a_cc_list_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, transport: httpx.AsyncClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _draft(client, transport, cc=[_ADA] * (drafter.MAX_RECIPIENTS + 1))


class TestTheSchemaItPublishes:
    async def test_it_takes_six_arguments_and_no_others(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"to", "subject", "body_html", "cc", "attachments", "mailbox"}

    @pytest.mark.parametrize("word", ["bcc", "blind", "file", "upload", "drive", "url"])
    async def test_no_argument_offers_a_blind_copy_a_fetch_or_markup(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        """This test looks for the absence of the argument. That absence is the real control. A
        runtime refusal keeps the argument in the schema. A model reads a published argument as
        an invitation to use it. `attachments` is the one deliberate exception. Its own tests,
        below, cover `attachments`. It never appears in this list."""
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_attachments_is_the_only_argument_naming_a_file(
        self, transport: httpx.AsyncClient
    ) -> None:
        """`attachments` is the one argument allowed to contain the word `file` or `attach`. This
        test matches by name. It still catches a second argument that reaches the same
        capability."""
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert [name for name in properties if "attach" in name.casefold()] == ["attachments"]

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
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """The default value comes from the `Field` declaration, not from the function signature.
        A default of `[]` in the function signature becomes one shared list for the life of the
        process."""
        route = _creates(graph, _created())

        _ = await _draft(client, transport, cc=["pam@example.invalid"])
        _ = await _draft(client, transport)

        assert _addressed(_sent(route), "ccRecipients") == []


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_microsoft_documents_for_creating_a_message(self) -> None:
        """Microsoft's walkthrough for shared folders names `Mail.ReadWrite.Shared` as the
        permission for writing a message into a mailbox other than `/me`."""
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

    async def test_the_description_says_it_cannot_send_and_names_the_attachment_ceiling(
        self, transport: httpx.AsyncClient
    ) -> None:
        """The tool description is the only place where the model reads these limits. It states
        what it cannot do, and now what it can attach and how much. No other file re-reads the
        tool file for the model."""
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lowered = description.casefold()
        assert "cannot send" in lowered
        assert "bcc" in lowered
        assert "outlook_find_recipient" in description
        assert f"up to {MAX_ATTACHMENTS}" in lowered
        assert "url" in lowered


class TestMailboxTargeting:
    async def test_no_mailbox_drafts_into_the_signed_in_users_own_mailbox(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, transport)

        assert route.called

    async def test_a_mailbox_drafts_into_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post("/users/alex@example.invalid/messages").mock(
            return_value=httpx.Response(201, json=_created())
        )

        answer = await drafter.draft_mail(
            client,
            transport,
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
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """The record of a draft must show who the draft actually reaches, not who this call
        asked for. This exposes a recipient that the user did not ask for."""
        _ = _creates(
            graph,
            _created(
                to=[_recipient("Ada Lovelace", _ADA), _recipient("Grace Hopper", _GRACE)],
                cc=[_recipient("Pam Beesly", "pam@example.invalid")],
            ),
        )

        answer = await _draft(client, transport, to=[_ADA])

        assert [address.address for address in answer.to] == [_ADA, _GRACE]
        assert [address.address for address in answer.cc] == ["pam@example.invalid"]

    async def test_the_subject_and_body_are_read_off_graph_too(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(
            graph,
            _created(
                subject="Invoice 4471 (stored)",
                body={"contentType": "text", "content": "Stored by Microsoft."},
            ),
        )

        answer = await _draft(client, transport, subject=_SUBJECT, body_html=_BODY)

        assert answer.subject == "Invoice 4471 (stored)"
        assert answer.body == "Stored by Microsoft."

    async def test_it_answers_the_link_graph_returned(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created())

        answer = await _draft(client, transport)

        assert answer.web_link == _WEB_LINK

    async def test_a_draft_graph_gave_no_link_answers_null_rather_than_a_built_one(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created(web_link=None))

        answer = await _draft(client, transport)

        assert answer.web_link is None

    async def test_the_handle_addresses_a_draft_and_cannot_be_read_as_a_message(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """Graph gives a draft the same id space as any other message. This connector keeps the
        two handle families separate. That separation stops a message id a reader found from
        being used as a draft id that a sender tool accepts."""
        _ = _creates(graph, _created())

        answer = await _draft(client, transport)

        handle = mail_draft_handle(answer.uri)
        assert handle is not None
        assert handle.draft_id == _DRAFT_ID
        assert mail_message_handle(answer.uri) is None

    async def test_an_empty_cc_comes_back_empty_rather_than_absent(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created(cc=[]))

        answer = await _draft(client, transport)

        assert answer.cc == []

    def test_attachments_is_the_only_field_naming_an_attachment(self) -> None:
        assert [name for name in MailDraft.model_fields if "attach" in name.casefold()] == [
            "attachments"
        ]


class TestAttachments:
    async def test_a_default_call_attaches_nothing(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        answer = await _draft(client, transport)

        assert "attachments" not in _sent(route)
        assert answer.attachments == []

    async def test_an_attachment_reaches_graph_inside_the_same_create(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, transport, attachments=[_attachment(name="budget.pdf")])

        assert route.call_count == 1, "one draft, one request — the attachment travels with it"
        sent = cast("list[dict[str, object]]", _sent(route)["attachments"])
        assert len(sent) == 1
        assert sent[0]["name"] == "budget.pdf"
        assert sent[0]["contentType"] == "application/pdf"
        assert sent[0]["@odata.type"] == "#microsoft.graph.fileAttachment"

    async def test_content_bytes_reaches_graph_as_the_same_base64_it_was_given(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(client, transport, attachments=[_attachment(content_bytes=_TINY_FILE)])

        sent = cast("list[dict[str, object]]", _sent(route)["attachments"])
        assert sent[0]["contentBytes"] == _TINY_FILE

    async def test_several_attachments_keep_their_order(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        _ = await _draft(
            client,
            transport,
            attachments=[_attachment(name="one.pdf"), _attachment(name="two.pdf")],
        )

        sent = cast("list[dict[str, object]]", _sent(route)["attachments"])
        assert [one["name"] for one in sent] == ["one.pdf", "two.pdf"]

    async def test_invalid_base64_is_refused_before_anything_reaches_graph(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())

        with pytest.raises(ToolError, match="not.*valid base64"):
            _ = await _draft(
                client, transport, attachments=[_attachment(content_bytes="not base64 at all!")]
            )

        assert route.call_count == 0, "a refused attachment creates nothing in the mailbox"

    async def test_a_file_at_or_past_the_absolute_ceiling_is_refused_before_anything_reaches_graph(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """This test uses `MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION`, not `MAX_ATTACHMENT_BYTES`. A
        file at the inline ceiling now attaches through the upload session. See
        `TestLargeAttachments...` below. Only Microsoft's own absolute ceiling still refuses the
        file outright."""
        route = _creates(graph, _created())
        oversized = base64.b64encode(b"x" * MAX_ATTACHMENT_BYTES_VIA_UPLOAD_SESSION).decode()

        with pytest.raises(ToolError, match="150 MB"):
            _ = await _draft(client, transport, attachments=[_attachment(content_bytes=oversized)])

        assert route.call_count == 0, "a refused attachment creates nothing in the mailbox"

    async def test_a_file_just_under_the_inline_ceiling_attaches_directly_with_one_request(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = _creates(graph, _created())
        fits = base64.b64encode(b"x" * (MAX_ATTACHMENT_BYTES - 1)).decode()

        _ = await _draft(client, transport, attachments=[_attachment(content_bytes=fits)])

        assert route.call_count == 1

    async def test_an_attachment_list_outside_the_schema_is_a_programming_error(
        self, client: GraphServiceClient, transport: httpx.AsyncClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _draft(client, transport, attachments=[_attachment()] * (MAX_ATTACHMENTS + 1))

    async def test_the_answer_reports_name_type_and_decoded_size_not_the_bytes(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _created())

        answer = await _draft(client, transport, attachments=[_attachment(name="budget.pdf")])

        assert len(answer.attachments) == 1
        one = answer.attachments[0]
        assert one.name == "budget.pdf"
        assert one.content_type == "application/pdf"
        assert one.size == len(base64.b64decode(_TINY_FILE))
        assert not hasattr(one, "content_bytes")

    async def test_the_schema_bounds_attachments_the_same_way_as_recipients(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        attachments = cast("Mapping[str, object]", properties["attachments"])
        assert attachments["default"] == []
        assert attachments["maxItems"] == MAX_ATTACHMENTS

    def test_no_blind_copy_is_addressable_in_the_answer_at_all(self) -> None:
        assert not [name for name in MailDraft.model_fields if "bcc" in name.casefold()]


class TestLargeAttachmentsGoThroughAnUploadSessionAfterTheDraftExists:
    """If the attachment size is at or past `MAX_ATTACHMENT_BYTES`, an attachment cannot travel
    inside the create call. See the module docstring of the tool for the reason. So this file
    always creates the draft first, then uploads each large attachment separately. Each upload
    goes through `shared.attachment_upload.upload_attachment`, against the draft id that the
    create call just returned.
    """

    async def test_a_small_and_a_large_attachment_split_between_the_create_and_a_separate_upload(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph, _created())
        session = _session_route(graph)
        chunks = _chunk_route(graph)

        answer = await _draft(
            client,
            transport,
            attachments=[
                _attachment(name="small.pdf"),
                _attachment(name="large.pdf", content_bytes=_LARGE_FILE),
            ],
        )

        sent = cast("list[dict[str, object]]", _sent(create)["attachments"])
        assert [one["name"] for one in sent] == ["small.pdf"], (
            "only the small attachment travels inside the create — the large one is held back"
        )
        assert session.called, "the large attachment reached createUploadSession"
        assert chunks.called, "the large attachment's bytes reached the uploadUrl"
        assert [one.name for one in answer.attachments] == ["small.pdf", "large.pdf"]
        assert answer.attachments[1].size == len(base64.b64decode(_LARGE_FILE))

    async def test_a_draft_with_only_large_attachments_uploads_every_one_after_the_create(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph, _created())
        session = _session_route(graph)
        chunks = _chunk_route(graph)
        second_large = base64.b64encode(b"y" * MAX_ATTACHMENT_BYTES).decode()

        answer = await _draft(
            client,
            transport,
            attachments=[
                _attachment(name="one.pdf", content_bytes=_LARGE_FILE),
                _attachment(name="two.pdf", content_bytes=second_large),
            ],
        )

        assert "attachments" not in _sent(create), "no attachment here is small enough to embed"
        assert session.call_count == 2, "one upload session per large attachment"
        assert chunks.call_count == 2
        assert [one.name for one in answer.attachments] == ["one.pdf", "two.pdf"], (
            "held-back attachments upload in the order they were given"
        )

    async def test_a_refused_upload_names_the_draft_that_already_exists_and_what_already_landed(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """By the time a large attachment's upload can fail, the create call has already
        succeeded. So the draft is real. The module docstring promises that the exception states
        this fact. Every other refusal in this file can still leave the caller to assume that
        nothing happened, but this one cannot."""
        _ = _creates(graph, _created())
        session = _session_route(graph)
        _ = graph.route(method="PUT", host="attachment-upload.invalid").mock(
            return_value=httpx.Response(500, text="synthetic upload-session failure")
        )
        handle = MailDraftHandle(_DRAFT_ID).uri

        with pytest.raises(ToolError) as failure:
            _ = await _draft(
                client,
                transport,
                attachments=[
                    _attachment(name="small.pdf"),
                    _attachment(name="large.pdf", content_bytes=_LARGE_FILE),
                ],
            )

        assert session.called
        message = str(failure.value)
        assert handle in message, "the draft this call already created is named, not just implied"
        assert "large.pdf" in message, "which attachment was refused is named"
        assert "not all-or-nothing" in message or "rolls the draft back" in message, (
            "the message says plainly that this is not atomic, not just that something failed"
        )

    async def test_a_second_large_attachment_is_never_attempted_after_the_first_is_refused(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """This code stops at the first refusal. It does not try to upload the rest. Graph gives
        no way to ask whether a later attachment landed. If the code skipped ahead, it could
        silently under-report what is actually on the draft."""
        _ = _creates(graph, _created())
        session = _session_route(graph)
        _ = graph.route(method="PUT", host="attachment-upload.invalid").mock(
            return_value=httpx.Response(500, text="synthetic upload-session failure")
        )
        second_large = base64.b64encode(b"y" * MAX_ATTACHMENT_BYTES).decode()

        with pytest.raises(ToolError):
            _ = await _draft(
                client,
                transport,
                attachments=[
                    _attachment(name="one.pdf", content_bytes=_LARGE_FILE),
                    _attachment(name="two.pdf", content_bytes=second_large),
                ],
            )

        assert session.call_count == 1, "the second attachment was never attempted"

    async def test_the_underlying_graph_failure_is_the_raised_exceptions_cause(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        """The code chains the error with `from`. So the original `GraphFailure` object, with its
        status, code, and request id, stays available to anything that reads `__cause__`. The
        message a caller sees is this file's own text, not the generic text that Microsoft
        Graph's own error gives."""
        _ = _creates(graph, _created())
        _ = _session_route(graph)
        _ = graph.route(method="PUT", host="attachment-upload.invalid").mock(
            return_value=httpx.Response(500, text="synthetic upload-session failure")
        )

        with pytest.raises(ToolError) as failure:
            _ = await _draft(
                client,
                transport,
                attachments=[_attachment(name="large.pdf", content_bytes=_LARGE_FILE)],
            )

        assert isinstance(failure.value.__cause__, GraphFailure)


class TestTheFailuresItPassesOn:
    async def test_a_refused_create_is_a_forbidden(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_MESSAGES).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _draft(client, transport)

    async def test_a_mailbox_that_rejects_the_write_creates_nothing(
        self, client: GraphServiceClient, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_MESSAGES).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _draft(client, transport)

        assert route.call_count == 1, "a refused write is not retried into a duplicate draft"
