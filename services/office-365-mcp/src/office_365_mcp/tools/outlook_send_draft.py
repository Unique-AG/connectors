from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.headers_collection import HeadersCollection
from mcp.types import InputRequiredResult
from msgraph.generated.models.message import Message
from msgraph.generated.users.item.messages.item.message_item_request_builder import (
    MessageItemRequestBuilder,
)
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import MailDraftHandle, mail_draft_handle, mail_message_handle
from office_365_mcp.shared.mail import MailAddress
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    WRITE_DESTRUCTIVE,
    Confirmed,
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

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "draft_ref": "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D"
}

_DRAFT_FIELDS: tuple[str, ...] = ("toRecipients", "ccRecipients", "subject", "isDraft")

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_MessageQuery = MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters

_DESCRIPTION = (
    "Sends a draft from outlook_draft_mail or outlook_draft_reply onto the wire. This cannot "
    "be undone, and asks the person to approve before sending."
)

_NOT_A_DRAFT_HANDLE = (
    "outlook_send_draft takes the `draft_ref` handle that outlook_draft_mail or "
    + "outlook_draft_reply answered with, and this is not one. A sendable handle has exactly one "
    + "shape:\n"
    + "  outlook:///drafts/{draft_id}\n"
    + "with the id percent-encoded, for example "
    + "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D. Only a handle of the drafts family is "
    + "accepted, and only the two drafting tools mint one. A subject line, an email address, a "
    + "message id and an Outlook web link are not handles. Neither is a folder or rule handle "
    + "under the same scheme, which addresses something that is not a draft. Nothing was sent. "
    + "If the mail still needs writing, call outlook_draft_mail and send the handle it answers "
    + "with. Retrying this value will fail identically."
)

_A_MESSAGE_IS_NOT_A_DRAFT = (
    "That is a message handle (outlook:///messages/{id}), and outlook_send_draft will not send "
    + "it. Nothing was sent. Only a draft THIS CONNECTOR COMPOSED can be sent. That is why a "
    + "draft has a handle family of its own: outlook:///drafts/{id}, minted by outlook_draft_mail "
    + "and outlook_draft_reply, and by nothing else. A message handle comes from reading the "
    + "mailbox: a search hit, a folder listing, a thread. So it addresses mail somebody else "
    + "wrote, or mail that was already sent. Neither one has a route here to an outbound "
    + "message. If the user wants to reply to that message, draft the reply first with "
    + "outlook_draft_reply. Show it to them. Then send the draft handle it answers with."
)

_ALREADY_SENT = (
    "That draft handle addresses a message Microsoft does not hold as a draft any more. So "
    + "outlook_send_draft refused it, and NOTHING WAS SENT BY THIS CALL. Overwhelmingly, the "
    + "likeliest reason is that the message was already sent: by an earlier call in this "
    + "conversation, or by the user in Outlook. In that case it is already on its way, and "
    + "sending it again delivers a duplicate. Microsoft documents this route as sending an "
    + "existing draft, and does not say what it does to a message that already went out. An "
    + "action that cannot be undone is not worth finding out. Do not retry this handle: it will "
    + "be refused the same way. Tell the user the mail was probably already sent. If they "
    + "want a fresh message, compose a new draft with outlook_draft_mail."
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

type _Confirm = Callable[[Message, str | None], Awaitable[Confirmed]]


def a_person_agrees(ctx: Context) -> _Confirm:
    confirm = person_confirms(ctx, agree=SEND, decline=_DO_NOT_SEND, nothing_happened=_NOTHING_SENT)

    async def asked(draft: Message, mailbox: str | None) -> Confirmed:
        everyone = [
            one.address or one.name or "an address Microsoft did not record"
            for one in MailAddress.each_of(draft.to_recipients)
            + MailAddress.each_of(draft.cc_recipients)
        ]
        identity = f" as {mailbox}" if mailbox is not None else ""
        question = (
            f"Send the draft {draft.subject or '(no subject)'!r} to "
            f"{', '.join(everyone) or 'nobody'}{identity}? Sending cannot be undone."
        )
        return await confirm(question, question)

    return asked


async def send_draft(
    client: GraphServiceClient, *, draft_ref: str, confirm: _Confirm, mailbox: str | None = None
) -> MailSent | InputRequiredResult:
    handle = _handle_for(draft_ref)
    reached = graph_mailbox(client, mailbox)

    asked: InputRequiredResult | None = None
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_READ_DRAFT):
            draft = await reached.messages.by_message_id(handle.draft_id).get(
                request_configuration=_read_request()
            )
        refused: str | None = _ALREADY_SENT
        if draft is not None and draft.is_draft is True:
            with not_graph():
                answer = await confirm(draft, mailbox)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        sent_at = await _send(reached, handle) if refused is None and asked is None else None

    assert draft is not None, "Graph answered a draft read with no message"
    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert sent_at is not None, "a send that nothing refused recorded no time"
    return _answer(draft, sent_at=sent_at)


def _handle_for(draft_ref: str) -> MailDraftHandle:
    handle = mail_draft_handle(draft_ref)
    if handle is not None:
        return handle
    if mail_message_handle(draft_ref) is not None:
        raise ToolError(_A_MESSAGE_IS_NOT_A_DRAFT)
    raise ToolError(_NOT_A_DRAFT_HANDLE)


async def _send(reached: UserItemRequestBuilder, handle: MailDraftHandle) -> datetime:
    with graph_step(STEP_SEND_DRAFT):
        await reached.messages.by_message_id(handle.draft_id).send.post(
            request_configuration=_send_request()
        )
    return datetime.now(UTC)


def _read_request() -> RequestConfiguration[_MessageQuery]:
    return RequestConfiguration[_MessageQuery](
        query_parameters=_MessageQuery(select=list(_DRAFT_FIELDS)),
        headers=_immutable_ids(),
    )


def _send_request() -> RequestConfiguration[QueryParameters]:
    return RequestConfiguration[QueryParameters](headers=_immutable_ids(), options=no_retry())


def _immutable_ids() -> HeadersCollection:
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return headers


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
                    "The draft to send: the uri that outlook_draft_mail or outlook_draft_reply "
                    "answered with."
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
