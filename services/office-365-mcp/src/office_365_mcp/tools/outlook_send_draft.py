from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.message import Message
from msgraph.generated.users.item.messages.item.message_item_request_builder import (
    MessageItemRequestBuilder,
)
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import MailMessageHandle, mail_message_handle
from office_365_mcp.shared.immutable_ids import immutable_id_headers
from office_365_mcp.shared.mail import MailAddress
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    WRITE_DESTRUCTIVE,
    Confirmed,
    confirmation_digest,
    graph_client_for_caller,
    graph_mailbox,
    person_confirms,
)

TOOL_NAME = "outlook_send_draft"

STEP_READ_DRAFT = "read_draft"
STEP_SEND_DRAFT = "send_draft"

GRAPH_PERMISSIONS: tuple[str, ...] = (
    "Mail.Send",
    "Mail.ReadBasic",
    "Mail.Send.Shared",
    "Mail.Read.Shared",
)

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_list_mail",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "draft_ref": "outlook:///messages/AAMkAGI2SYNTHETIC-draft-0001%3D"
}

_DRAFT_FIELDS: tuple[str, ...] = (
    "toRecipients",
    "ccRecipients",
    "bccRecipients",
    "subject",
    "isDraft",
    "changeKey",
)

_MessageQuery = MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Sends one mail draft, from the signed-in user's own mailbox or, with `mailbox`, a shared or \
delegated one. The handle comes from outlook_draft_mail, outlook_draft_reply, \
outlook_draft_reply_all or outlook_update_draft. These four tools and this tool are in the \
outlook-send preset. This connector cannot undo a send or recall the message.

Notes:
- This tool reads the message first. It sends nothing unless Microsoft holds the message as a \
draft.
- This tool asks the user to agree before it sends anything, every time. This tool sends nothing \
unless the user agrees.
- If the draft changes after this tool asks the user, this tool sends nothing. A new call asks the \
user about the draft as it is now.
- If a call times out, do not call this tool again first. The mail can already be out. Before you \
call again, make sure that outlook_list_mail does not show the message in `sentitems`.
"""

_NOT_A_MESSAGE_HANDLE = (
    "outlook_send_draft takes the `draft_ref` handle of the draft to send, and this is not one. "
    + "Use the `uri` that outlook_draft_mail or outlook_draft_reply answered with. A handle has "
    + "exactly one shape:\n"
    + "  outlook:///messages/{message_id}\n"
    + "with the id percent-encoded, for example "
    + "outlook:///messages/AAMkAGI2SYNTHETIC-draft-0001%3D. A subject line, an email address, a "
    + "bare message id and an Outlook web link are not handles. Neither is a folder or rule "
    + "handle under the same scheme, which addresses something that is not a message. Nothing "
    + "was sent. If the mail still needs writing, call outlook_draft_mail and send the handle it "
    + "answers with. Retrying this value will fail identically."
)

_NOT_A_DRAFT = (
    "That handle addresses a message that Microsoft does not hold as a draft, so "
    + "outlook_send_draft refused it. NOTHING WAS SENT BY THIS CALL. The message can be mail that "
    + "somebody sent to the user. It can also be a draft that somebody already sent: by an "
    + "earlier call in this conversation, or by the user in Outlook. In that case it is already "
    + "on its way, and sending it again delivers a duplicate. Microsoft documents this route as "
    + "sending an existing draft, and does not say what it does to a message that already went "
    + "out. An action that cannot be undone is not worth finding out. Do not retry this handle: "
    + "it will be refused the same way. If you drafted this mail in this conversation, tell the "
    + "user it was probably already sent. If the user wants to reply to this message, draft the "
    + "reply with outlook_draft_reply and send the handle it answers with. If they want a fresh "
    + "message, compose a new draft with outlook_draft_mail."
)

_CHANGED_AFTER_ASKING = (
    "The draft changed after this tool asked the user. This tool sent nothing, because the user "
    + "agreed to the earlier version of the draft. Call this tool again with the same "
    + "`draft_ref`. The new call asks the user about the draft as it is now."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return the draft this call named, and NOTHING WAS SENT. The handle "
    + "is well formed, so this is not a bad argument. A draft leaves Drafts once it is sent, and "
    + "the user can also delete it or move it in Outlook. Graph reports all of these as this one "
    + "404, without saying which one it meant. Never report the mail as sent: this call did not "
    + "send it, and whether an earlier one did is not knowable from here. Retrying will not "
    + "help, and this connector has no other route to that draft. Ask the user whether the mail "
    + "was already sent. If it was not, compose a fresh draft with outlook_draft_mail."
)


class MailSent(BaseModel):
    to: list[MailAddress] = Field(description="Who received the message.")
    cc: list[MailAddress] = Field(description="Who received a copy.")
    subject: str | None = Field(description="The subject the message was sent with, or null.")
    sent_at: str = Field(description="When the send was accepted, ISO-8601 in UTC.")


SEND = "send"
_DO_NOT_SEND = "do not send"
_NOTHING_SENT = "Nothing was sent, and the draft is untouched and still in Drafts."
_NO_ADDRESS = "an address Microsoft did not record"

type _Confirm = Callable[[Message, str | None], Awaitable[Confirmed]]


def a_person_agrees(ctx: Context) -> _Confirm:
    confirm = person_confirms(ctx, agree=SEND, decline=_DO_NOT_SEND, nothing_happened=_NOTHING_SENT)

    async def asked(draft: Message, mailbox: str | None) -> Confirmed:
        everyone = [
            one.address or one.name or _NO_ADDRESS
            for one in MailAddress.each_of(draft.to_recipients)
            + MailAddress.each_of(draft.cc_recipients)
        ] + [
            f"{one.address or one.name or _NO_ADDRESS} (blind copy)"
            for one in MailAddress.each_of(draft.bcc_recipients)
        ]
        identity = f" as {mailbox}" if mailbox is not None else ""
        question = (
            f"Send the draft {draft.subject or '(no subject)'!r} to "
            f"{', '.join(everyone) or 'nobody'}{identity}? Sending cannot be undone."
        )
        assert draft.change_key is not None, (
            "Graph answered the draft read with no changeKey, "
            "so an accept cannot be bound to this version of the draft"
        )
        about = confirmation_digest(question, draft.change_key)
        return await confirm(question, about)

    return asked


async def send_draft(
    client: GraphServiceClient, *, draft_ref: str, confirm: _Confirm, mailbox: str | None = None
) -> MailSent | InputRequiredResult:
    handle = _handle_for(draft_ref)
    reached = graph_mailbox(client, mailbox)

    asked: InputRequiredResult | None = None
    with graph_errors(TOOL_NAME):
        draft = await _read(reached, handle)
        refused: str | None = _NOT_A_DRAFT
        if draft is not None and draft.is_draft is True:
            with not_graph():
                answer = await confirm(draft, mailbox)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
            if answer is None:
                refused = _refusal_after(draft, await _read(reached, handle))
        sent_at = await _send(reached, handle) if refused is None and asked is None else None

    assert draft is not None, "Graph answered a draft read with no message"
    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert sent_at is not None, "a send that nothing refused recorded no time"
    return _answer(draft, sent_at=sent_at)


def _handle_for(draft_ref: str) -> MailMessageHandle:
    handle = mail_message_handle(draft_ref)
    if handle is None:
        raise ToolError(_NOT_A_MESSAGE_HANDLE)
    return handle


async def _read(reached: UserItemRequestBuilder, handle: MailMessageHandle) -> Message | None:
    with graph_step(STEP_READ_DRAFT):
        return await reached.messages.by_message_id(handle.message_id).get(
            request_configuration=_read_request()
        )


def _refusal_after(asked_about: Message, latest: Message | None) -> str | None:
    if latest is None or latest.is_draft is not True:
        return _NOT_A_DRAFT
    if latest.change_key != asked_about.change_key:
        return _CHANGED_AFTER_ASKING
    return None


async def _send(reached: UserItemRequestBuilder, handle: MailMessageHandle) -> datetime:
    with graph_step(STEP_SEND_DRAFT):
        await reached.messages.by_message_id(handle.message_id).send.post(
            request_configuration=_send_request()
        )
    return datetime.now(UTC)


def _read_request() -> RequestConfiguration[_MessageQuery]:
    return RequestConfiguration[_MessageQuery](
        query_parameters=_MessageQuery(select=list(_DRAFT_FIELDS)),
        headers=immutable_id_headers(),
    )


def _send_request() -> RequestConfiguration[QueryParameters]:
    return RequestConfiguration[QueryParameters](headers=immutable_id_headers(), options=no_retry())


def _answer(draft: Message, *, sent_at: datetime) -> MailSent:
    return MailSent(
        to=MailAddress.each_of(draft.to_recipients),
        cc=MailAddress.each_of(draft.cc_recipients),
        subject=draft.subject,
        sent_at=sent_at.isoformat(),
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Send a Drafted Mail Message",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
    )
    async def outlook_send_draft(
        draft_ref: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The draft to send: the `uri` that outlook_draft_mail, outlook_draft_reply, "
                    "outlook_draft_reply_all or outlook_update_draft answered with. Copy it "
                    "exactly."
                ),
            ),
        ],
        ctx: Context,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> MailSent | InputRequiredResult:
        return await send_draft(
            client, draft_ref=draft_ref, confirm=a_person_agrees(ctx), mailbox=mailbox
        )
