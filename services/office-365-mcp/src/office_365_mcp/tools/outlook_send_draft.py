"""`outlook_send_draft` — the only tool in this connector that puts mail on the wire.

It takes one draft handle and nothing else. `outlook:///drafts/{id}` is a handle family of its own
(`shared/handles.py`), minted only by `outlook_draft_mail` and `outlook_draft_reply`, and that is
this tool's defence rather than a formality: Graph gives a draft the same id space as every other
message, so a single family would let a message a reader *found* be spelled as a draft and handed
here. Kept apart, "send the mail you just wrote" is expressible and "send that mail I found" is
not — this tool sends only a message the mailbox still reports as a draft, addressed by a handle
of the drafts family, which only the two drafting tools mint.

**No argument may change the message.** There is no recipient, subject, body or attachment
argument, and their absence is the whole safety story: what is sent is exactly what a human can
already open in their Drafts folder. The model composes, a person can look, and this pulls the
trigger on what is there. An argument that edited the draft on the way out would put words on the
wire under the user's own address that nobody had the chance to read.

**Microsoft's one-shot send is never used here.** `POST /me/sendMail` composes and delivers from
arguments alone, so no draft exists for anyone to have read first; it is the one send that can be
told to keep no copy in Sent Items, leaving the user's own mailbox with no record that the message
ever existed; and it answers `202 Accepted` with an empty body, so nothing about the delivery can
be echoed back. The flag that suppresses that copy is not merely unused here — it is not spellable
in this file, because an argument nobody declares is a capability nobody can reach.
`POST /me/messages/{id}/send` is the send that leaves a trail: Microsoft files the message in Sent
Items (https://learn.microsoft.com/en-us/graph/api/message-send), and the pre-read below records
who it went to.

**Two calls, and the read comes first.** `GET /me/messages/{id}` for the recipients, the subject
and `isDraft`, then the send. The order is not an optimisation: the send answers `202 Accepted`
with an empty body, and once it has gone the handle no longer addresses a draft, so a read
afterwards has nothing to report. A send that reported only "sent" would leave no record of who
received it, and this is the only place that record can come from.

**`Mail.ReadBasic` is declared beside `Mail.Send` because of that read.** The On-Behalf-Of token is
minted for exactly the declared permissions, so a tool declaring `Mail.Send` alone would 403 on its
own pre-read. Microsoft's least privileged delegated permission for the send is `Mail.Send` and it
publishes no alternative (https://learn.microsoft.com/en-us/graph/api/message-send); for the read
it is `Mail.ReadBasic`, with `Mail.Read` the higher privileged one
(https://learn.microsoft.com/en-us/graph/api/message-get). `Mail.ReadBasic` withholds the body and
the attachments and nothing this reads, so asking for `Mail.Read` would buy this tool nothing and
cost the consent screen a permission that opens every message in the mailbox.

**A message that is not a draft is refused rather than sent.** Graph documents this route as
sending an existing draft and says nothing whatever about what it does to a message that has
already gone. An irreversible action must not rest on undocumented behaviour, so `isDraft` is
selected in the pre-read and a false answer stops the call before the send.

**`no_retry()` on the send is the single most important line in this file.** The SDK's retry
middleware retries `POST` exactly as readily as `GET` — its retry statuses are 429, 503 and 504 —
`GRAPH_MAX_RETRIES` defaults to 3, and Microsoft publishes no idempotency key for sending mail. An
unguarded send therefore delivers the same message up to four times, and no part of that is
recoverable. `tests/graph_client/test_client.py::TestANonIdempotentCallIsNotRetried` proves the
default and the override differ.

**`Prefer: IdType="ImmutableId"` on both requests.** Every handle this connector mints carries an
immutable id, and Graph reads an id in the path in whichever id space the request declares — so
without the header the id the draft tool handed out is read as a `RestId` and answered with a 404
that means nothing in particular.

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

# An invented handle in the shape this tool accepts: an argument it rejects never reaches Graph.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "draft_ref": "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D"
}

# Everything the answer is built from, and nothing else. `body` is deliberately absent: this tool
# does not need the words to send them, `Mail.ReadBasic` withholds them anyway, and re-reading a
# body the model already wrote would put it through the context a second time.
_DRAFT_FIELDS: tuple[str, ...] = ("toRecipients", "ccRecipients", "subject", "isDraft")

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_MessageQuery = MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Send a draft that outlook_draft_mail or outlook_draft_reply created in the signed-in user's own \
Drafts folder. THIS PUTS MAIL ON THE WIRE: it is delivered from the user's own address, in their \
name, and IT CANNOT BE UNDONE — this connector has no recall and no unsend, and nothing here \
reaches a message once it is in somebody else's mailbox. Show the draft to the user and get their \
agreement first: read them the recipients, the subject and the body that the drafting tool \
answered with, and call this only once they have said to send it. It takes one argument, the \
draft's own handle, and NOTHING it is given can change the message — there is no recipient, \
subject, body or attachment argument here, so what goes out is exactly what the user can already \
open in Outlook. Only a handle of the drafts family is accepted: a message handle from \
outlook_search_mail, outlook_list_mail or outlook_read_thread is refused, and no message id, \
subject line or Outlook web link becomes a draft handle. A message that has already been sent is \
refused rather than sent again. Answers the recipients and subject Microsoft held for the draft \
at the moment it went, which is the only record of what left the mailbox — repeat it to the user.\
"""

_NOT_A_DRAFT_HANDLE = (
    "outlook_send_draft takes the `draft_ref` handle that outlook_draft_mail or "
    + "outlook_draft_reply answered with, and this is not one. A sendable handle has exactly one "
    + "shape:\n"
    + "  outlook:///drafts/{draft_id}\n"
    + "with the id percent-encoded, e.g. outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D. Only "
    + "a handle of the drafts family is accepted, and only the two drafting tools mint one — "
    + "only thing that says so — a subject line, an email address, a message id and an Outlook "
    + "web link are none of them handles, and a folder or rule handle under the same scheme "
    + "addresses something that is not a draft. Nothing was sent. If the mail still needs "
    + "writing, call outlook_draft_mail and send the handle it answers with; retrying this value "
    + "will fail identically."
)

_A_MESSAGE_IS_NOT_A_DRAFT = (
    "That is a message handle (outlook:///messages/{id}), and outlook_send_draft will not send "
    + "it. Nothing was sent. Only a draft THIS CONNECTOR COMPOSED can be sent, which is why a "
    + "draft has a handle family of its own: outlook:///drafts/{id}, minted by outlook_draft_mail "
    + "and outlook_draft_reply and by nothing else. A message handle comes from reading the "
    + "mailbox — a search hit, a folder listing, a thread — so it addresses mail somebody else "
    + "wrote or mail that has already been sent, and there is no route here from either of those "
    + "to an outbound message. If the user wants to reply to that message, draft the reply first "
    + "with outlook_draft_reply, show it to them, and send the draft handle it answers with."
)

_ALREADY_SENT = (
    "That draft handle addresses a message Microsoft does not hold as a draft any more, so "
    + "outlook_send_draft refused it and NOTHING WAS SENT BY THIS CALL. Overwhelmingly the "
    + "likeliest reason is that the message has already been sent — by an earlier call in this "
    + "conversation, or by the user in Outlook — in which case it is already on its way and "
    + "sending it again would deliver a duplicate. Microsoft documents this route as sending an "
    + "existing draft and does not say what it does to a message that has already gone, and an "
    + "action that cannot be undone is not worth finding out. Do not retry this handle: it will "
    + "be refused the same way. Tell the user the mail appears to have gone already, and if they "
    + "want a fresh message, compose a new draft with outlook_draft_mail."
)

# Read by `tools/__init__.py` into the 404 advice table. The default advice, to check the id came
# from a tool response verbatim, is wrong here because it did: `draft_ref` is a handle this
# connector minted.
GRAPH_NOT_FOUND = (
    "Microsoft 365 would not return the draft this call named, and NOTHING WAS SENT. The handle "
    + "is well formed, so this is not a bad argument: a draft is gone from Drafts once it has "
    + "been sent, and the user can also have deleted it or moved it in Outlook, all of which "
    + "Graph reports as this one 404 without saying which it meant. Never report the mail as "
    + "sent — this call did not send it, and whether an earlier one did is not knowable from "
    + "here. Retrying will not help and this connector has no other route to that draft. Ask the "
    + "user whether the mail has already gone, and compose a fresh draft with outlook_draft_mail "
    + "if it has not."
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
            + "cannot be recalled, unsent or cancelled by this connector."
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

    # Decided inside the block above and raised outside it: `graph_errors` counts a `ToolError`
    # escaping it as a Graph operation that failed for a reason the seam cannot describe, and a
    # message this tool refuses to send is not a Graph failure at all.
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
    this route, and a body is where a flag suppressing the copy in Sent Items would have to go.
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
    # Closes over `transport` here; the default below holds this name, not a call (ruff's B008).
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
                    + "shape this accepts, and it is the only argument there is — nothing here "
                    + "can change the recipients, the subject, the body or anything else about "
                    + "the message, so what is sent is the draft the user can already read in "
                    + "Outlook. A message handle from a search, a listing or a thread is refused: "
                    + "mail somebody else wrote is not this user's to send. Show the draft to the "
                    + "user and wait for them to agree before passing it here; the send cannot be "
                    + "undone."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> MailSent:
        return await send_draft(client, draft_ref=draft_ref)
