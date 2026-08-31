"""`outlook_send_draft` — the only tool in this connector that puts mail on the wire.

It takes one draft handle and nothing else. `outlook:///drafts/{id}` is a handle family of its
own (`shared/handles.py`), minted only by `outlook_draft_mail` and `outlook_draft_reply`. This
is this tool's defense, not a formality. Graph gives a draft the same id space as every other
message, so one shared family lets a message a reader *found* be spelled as a draft, and handed
here. Kept apart, "send the mail you just wrote" is expressible, and "send that mail I found" is
not. This tool sends only a message that the mailbox still reports as a draft, addressed by a
handle of the drafts family, which only the two drafting tools mint.

**No argument can change the message.** There is no recipient, subject, body or attachment
argument. Their absence is the whole safety story: what is sent is exactly what a human can
already open in their Drafts folder. The model composes, a person can look, and this tool pulls
the trigger on what is there. An argument that edited the draft on the way out puts words on the
wire, under the user's own address, that nobody had the chance to read.

**Microsoft's one-shot send is never used here.** `POST /me/sendMail` composes and delivers from
arguments alone, so no draft exists for anyone to read first. It is the one send that can be
told to keep no copy in Sent Items, leaving the user's own mailbox with no record that the
message ever existed. It also answers `202 Accepted` with an empty body, so nothing about the
delivery can be echoed back. The flag that suppresses that copy is not merely unused here. It is
not spellable in this file, because an argument nobody declares is a capability nobody can
reach. `POST /me/messages/{id}/send` is the send that leaves a trail. Microsoft files the message
in Sent Items (https://learn.microsoft.com/en-us/graph/api/message-send), and the pre-read below
records who it went to.

**Two calls. The read comes first.** `GET /me/messages/{id}` reads the recipients, the subject
and `isDraft`. Then the send happens. This order is not an optimization: the send answers `202
Accepted` with an empty body. Once the send happens, the handle no longer addresses a draft, so
a read afterward has nothing to report. A send that reported only "sent" leaves no record of who
received it. This is the only place that record can come from.

**`Mail.ReadBasic` is declared beside `Mail.Send` because of that read.** The On-Behalf-Of token
is minted for exactly the declared permissions, so a tool that declares `Mail.Send` alone gets a
403 on its own pre-read. Microsoft's least privileged delegated permission for the send is
`Mail.Send`, and it publishes no alternative
(https://learn.microsoft.com/en-us/graph/api/message-send). For the read, it is `Mail.ReadBasic`,
with `Mail.Read` as the higher-privileged option
(https://learn.microsoft.com/en-us/graph/api/message-get). `Mail.ReadBasic` withholds the body
and the attachments, and nothing this reads needs them. Asking for `Mail.Read` instead buys this
tool nothing, and costs the consent screen a permission that opens every message in the mailbox.

**A message that is not a draft is refused rather than sent.** Graph documents this route as
sending an existing draft, and says nothing at all about what it does to a message that already
went out. An irreversible action must not rest on undocumented behavior, so `isDraft` is
selected in the pre-read, and a false answer stops the call before the send.

**`no_retry()` on the send is the single most important line in this file.** The SDK's retry
middleware retries `POST` exactly as readily as `GET`. Its retry statuses are 429, 503 and 504,
and `GRAPH_MAX_RETRIES` defaults to 3. Microsoft publishes no idempotency key for sending mail.
An unguarded send therefore delivers the same message up to four times, and no part of that is
recoverable. `tests/graph_client/test_client.py::TestANonIdempotentCallIsNotRetried` proves that
the default and the override differ.

**`Prefer: IdType="ImmutableId"` on both requests.** Every handle this connector mints carries an
immutable id. Graph reads an id in the path in whichever id space the request declares. Without
the header, the id the draft tool handed out is read as a `RestId`, and answered with a 404 that
means nothing in particular.

**No blind copy is read or reported**, which matches the draft this sends: `outlook_draft_mail`
declares no `bcc` argument at all, so a draft that reaches here has none to report.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.message import Message
from msgraph.generated.users.item.messages.item.message_item_request_builder import (
    MessageItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry
from office_365_mcp.shared.handles import MailDraftHandle, mail_draft_handle, mail_message_handle
from office_365_mcp.shared.mail import MailAddress
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE, graph_client_for_caller

TOOL_NAME = "outlook_send_draft"

STEP_READ_DRAFT = "read_draft"
STEP_SEND_DRAFT = "send_draft"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Send", "Mail.ReadBasic")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "draft_ref": "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D"
}

# Everything the answer is built from, and nothing else. `body` is deliberately absent: this
# tool does not need the words to send them, and `Mail.ReadBasic` withholds them anyway.
# Re-reading a body the model already wrote puts it through the context a second time.
_DRAFT_FIELDS: tuple[str, ...] = ("toRecipients", "ccRecipients", "subject", "isDraft")

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_MessageQuery = MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Send a draft that outlook_draft_mail or outlook_draft_reply created in the signed-in user's own \
Drafts folder. THIS PUTS MAIL ON THE WIRE: it is delivered from the user's own address, in their \
name, and IT CANNOT BE UNDONE. This connector has no recall and no unsend, and nothing here \
reaches a message once it is in somebody else's mailbox. Show the draft to the user and get \
their agreement first. Read them the recipients, the subject and the body that the drafting \
tool answered with, and call this only once they say to send it. It takes one argument, the \
draft's own handle, and NOTHING it is given can change the message. There is no recipient, \
subject, body or attachment argument here, so what goes out is exactly what the user can already \
open in Outlook. Only a handle of the drafts family is accepted: a message handle from \
outlook_search_mail, outlook_list_mail or outlook_read_thread is refused, and no message id, \
subject line or Outlook web link becomes a draft handle. A message that was already sent is \
refused rather than sent again. This tool answers with the recipients and subject that Microsoft \
held for the draft at the moment it went, which is the only record of what left the mailbox. \
Repeat it to the user.\
"""

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
    + "it. Nothing was sent. Only a draft THIS CONNECTOR COMPOSED can be sent, which is why a "
    + "draft has a handle family of its own: outlook:///drafts/{id}, minted by outlook_draft_mail "
    + "and outlook_draft_reply and by nothing else. A message handle comes from reading the "
    + "mailbox: a search hit, a folder listing, a thread. So it addresses mail somebody else "
    + "wrote, or mail that was already sent, and there is no route here from either of those to "
    + "an outbound message. If the user wants to reply to that message, draft the reply first "
    + "with outlook_draft_reply, show it to them, and send the draft handle it answers with."
)

_ALREADY_SENT = (
    "That draft handle addresses a message Microsoft does not hold as a draft any more, so "
    + "outlook_send_draft refused it and NOTHING WAS SENT BY THIS CALL. Overwhelmingly, the "
    + "likeliest reason is that the message was already sent: by an earlier call in this "
    + "conversation, or by the user in Outlook. In that case it is already on its way, and "
    + "sending it again delivers a duplicate. Microsoft documents this route as sending an "
    + "existing draft, and does not say what it does to a message that already went out. An "
    + "action that cannot be undone is not worth finding out. Do not retry this handle: it will "
    + "be refused the same way. Tell the user the mail was probably already sent, and if they "
    + "want a fresh message, compose a new draft with outlook_draft_mail."
)

# Read by `tools/__init__.py` into the 404 advice table. The default advice, to check the id came
# from a tool response verbatim, is wrong here because it did: `draft_ref` is a handle this
# connector minted.
GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return the draft this call named, and NOTHING WAS SENT. The handle "
    + "is well formed, so this is not a bad argument. A draft leaves Drafts once it is sent, and "
    + "the user can also delete it or move it in Outlook. Graph reports all of these as this one "
    + "404, without saying which one it meant. Never report the mail as sent: this call did not "
    + "send it, and whether an earlier one did is not knowable from here. Retrying will not "
    + "help, and this connector has no other route to that draft. Ask the user whether the mail "
    + "was already sent, and compose a fresh draft with outlook_draft_mail if it was not."
)


class MailSent(BaseModel):
    """What left the mailbox, read from the draft as Microsoft held it a moment before it went."""

    to: list[MailAddress] = Field(
        description=(
            "Who the message was sent to, read off Microsoft's copy of the draft immediately "
            + "before the send rather than echoed from anything this call was told. This is the "
            + "record of who now has the mail, so repeat it to the user in full. It cannot be "
            + "changed and the send CANNOT BE RECALLED by this connector: there is no unsend "
            + "here, and nothing in this server reaches a message once it is in a recipient's "
            + "mailbox."
        )
    )
    cc: list[MailAddress] = Field(
        description=(
            "Who was copied, read the same way and as impossible to recall: everyone here has the "
            + "mail too. Empty when Graph held none. No blind copy is reported and none can be — "
            + "no tool in this connector puts one on a draft."
        )
    )
    subject: str | None = Field(
        description=(
            "The subject Microsoft held for the draft when it went, which is what the recipients "
            + "see in their inbox. Null when the draft carried none."
        )
    )
    sent_at: str = Field(
        description=(
            "When Microsoft accepted the send, ISO-8601 in UTC, clocked by this connector at the "
            + "moment the request was accepted — Microsoft answers a send with an empty body, so "
            + "there is no timestamp of its own to report and this is within seconds rather than "
            + "exact. Delivery is Microsoft's from here on and there is no way back: the send "
            + "cannot be recalled, unsent or canceled by this connector."
        )
    )


async def send_draft(client: GraphServiceClient, *, draft_ref: str) -> MailSent:
    """Read the draft `draft_ref` addresses, then send it: two requests, in that order."""
    handle = _handle_for(draft_ref)

    with graph_errors(TOOL_NAME):
        with graph_step(STEP_READ_DRAFT):
            draft = await client.me.messages.by_message_id(handle.draft_id).get(
                request_configuration=_read_request()
            )
        sendable = draft is not None and draft.is_draft is True
        sent_at = await _send(client, handle) if sendable else None

    # This function decides inside the block above, and raises outside it. `graph_errors` treats
    # a `ToolError` that escapes it as a Graph operation that failed for a reason the seam cannot
    # describe. A message this tool refuses to send is not a Graph failure at all.
    assert draft is not None, "Graph answered a draft read with no message"
    if sent_at is None:
        raise ToolError(_ALREADY_SENT)
    return _answer(draft, sent_at=sent_at)


def _handle_for(draft_ref: str) -> MailDraftHandle:
    """The draft `draft_ref` addresses. A message handle gets its own refusal, because "that is a
    message, not a draft" is the one mistake a model can make here that looks like success."""
    handle = mail_draft_handle(draft_ref)
    if handle is not None:
        return handle
    if mail_message_handle(draft_ref) is not None:
        raise ToolError(_A_MESSAGE_IS_NOT_A_DRAFT)
    raise ToolError(_NOT_A_DRAFT_HANDLE)


async def _send(client: GraphServiceClient, handle: MailDraftHandle) -> datetime:
    """The send itself, and when Microsoft accepted it. Answers 202 with an empty body."""
    with graph_step(STEP_SEND_DRAFT):
        await client.me.messages.by_message_id(handle.draft_id).send.post(
            request_configuration=_send_request()
        )
    return datetime.now(UTC)


def _read_request() -> RequestConfiguration[_MessageQuery]:
    """Built per call: kiota's `RequestConfiguration.headers` defaults to one collection shared by
    every configuration in the process, so a preference added to that leaks onto every Graph call.
    """
    return RequestConfiguration[_MessageQuery](
        query_parameters=_MessageQuery(select=list(_DRAFT_FIELDS)),
        headers=_immutable_ids(),
    )


def _send_request() -> RequestConfiguration[QueryParameters]:
    """`no_retry()`, which is what stops one message being delivered four times: the SDK retries
    `POST` on 429, 503 and 504 three times by default, and Graph publishes no idempotency key for
    sending mail, so a retry after a lost response sends the message again.

    No request body is built here at all. Microsoft's own reference says one is unnecessary for
    this route. A body is also where a flag that suppresses the copy in Sent Items has to go.
    """
    return RequestConfiguration[QueryParameters](headers=_immutable_ids(), options=no_retry())


def _immutable_ids() -> HeadersCollection:
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return headers


def _answer(draft: Message, *, sent_at: datetime) -> MailSent:
    """Everything but the clock comes off the pre-read, so the transcript records what Microsoft
    held a moment before the send rather than what this call was asked to send."""
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
                    "The draft to send, as the `uri` outlook_draft_mail or outlook_draft_reply "
                    + "answered with, verbatim: outlook:///drafts/{draft_id}. That is the only "
                    + "shape this accepts, and it is the only argument there is. Nothing here "
                    + "can change the recipients, the subject, the body or anything else about "
                    + "the message, so what is sent is the draft the user can already read in "
                    + "Outlook. A message handle from a search, a listing or a thread is refused: "
                    + "mail somebody else wrote is not this user's to send. Show the draft to the "
                    + "user and wait for them to agree before passing it here. The send cannot be "
                    + "undone."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> MailSent:
        return await send_draft(client, draft_ref=draft_ref)
