"""`outlook_mark_mail` — read state, follow-up flag and importance, on up to twenty messages.

The first tool in this connector that changes anything, so the shape of it is mostly about what a
write is allowed to be rather than about Graph.

**Three properties, and the signature is the control on the rest.** `subject`, `body`,
`toRecipients` and `ccRecipients` are absent from the arguments and from the PATCH body, and their
absence is the whole of the guard: Microsoft makes those writable only while `isDraft` is true, and
what a PATCH of one against a sent message does is documented nowhere. There is no filter
downstream to drop them, because nothing upstream can name them — kiota serialises a property that
was never set not at all, so a body built here says exactly the properties this call was asked to
change and no more.

**`destructiveHint` is true, and `WRITE_ADDITIVE` would be a lie.** MCP defines a non-destructive
tool as one performing "only additive updates". Clearing a follow-up flag is not additive: Exchange
keeps `startDateTime`, `dueDateTime` and `completedDateTime` on `followupFlag`, this tool never
reads them, and `flagStatus: notFlagged` discards all three. Lowering an importance and marking a
message read likewise overwrite state nobody recorded first.

**One PATCH per message, and the answer is one row per message.** A batched write that reported a
single outcome would have to answer "did it work?" for twenty messages with one boolean, and the
honest value is neither of them: Graph 404s a message that was moved or purged since the handle was
minted while writing the other nineteen. So each write is its own request, each failure is caught
where it happens, and a caller reads the rows. A permission that was never consented cannot produce
that shape — the On-Behalf-Of exchange fails before this body runs — so a 403 reaching a row here
is about that message and not about the connector's consent.

**What is reported is read off the PATCH response, never off the arguments.** Graph answers a
message PATCH with the updated message, so `isRead`, `flag.flagStatus` and `importance` come back
from Exchange and are echoed from there. A tool that reported its own arguments would say a write
succeeded in exactly the case worth catching — the one where Exchange accepted the request and
stored something else, or nothing.

**`no_retry()` on every PATCH.** A PATCH of these three properties is idempotent in principle, so
this is not about double application: it is that the retry middleware turns one row into an
unknown number of attempts spread over a `Retry-After` wait, and this tool's promise is that its
answer says exactly what it did. The SDK retries every verb, and `GRAPH_MAX_RETRIES` defaults to 3.

**`Prefer: IdType="ImmutableId"` on the way in.** The handle carries the immutable id
`outlook_search_mail` and `outlook_list_mail` mint, and Graph reads a path id in whichever id space
the request declares. Without the header the immutable id is read as a `RestId` and every row is a
404 — the same load-bearing header `outlook_read_mail` sends, for the same reason.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from fastmcp.tools import tool as tool_metadata
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.followup_flag import FollowupFlag
from msgraph.generated.models.followup_flag_status import FollowupFlagStatus
from msgraph.generated.models.importance import Importance
from msgraph.generated.models.message import Message
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step, no_retry
from office_365_mcp.shared.handles import MailMessageHandle, mail_message_handle
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE, graph_client_for_caller

TOOL_NAME = "outlook_mark_mail"

STEP_MARK = "mark_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.ReadWrite",)

# An invented id in the shape this tool accepts: an argument it rejects never reaches Graph.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "message_refs": ["outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"],
    "is_read": True,
}

# One call must not be able to touch a whole mailbox. Twenty is the whole of the bulk this tool
# offers: the schema publishes it, the worker asserts it, and there is no page two.
MAX_MESSAGES = 20

type MailImportance = Literal["low", "normal", "high"]

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_FLAG_STATUS: Mapping[bool, FollowupFlagStatus] = {
    True: FollowupFlagStatus.Flagged,
    False: FollowupFlagStatus.NotFlagged,
}

_DESCRIPTION = f"""\
Change how up to {MAX_MESSAGES} messages are marked in the signed-in user's own mailbox: read or \
unread, flagged for follow-up or not, and the importance Outlook shows against them. THIS CHANGES \
THE MAILBOX. The change is immediate, this connector cannot undo it — no tool here restores a \
previous state — and the user sees it in Outlook on every device, where an unread count moves, a \
flag appears in or leaves their follow-up list, and an importance marker changes. Clearing a flag \
also discards the follow-up dates Outlook was keeping with it. Pass at least one of `is_read`, \
`flagged` and `importance`; whichever are given are applied to every message named, so one call is \
one change to one set of messages. `message_refs` takes the `uri` of a tool result verbatim — a \
subject line, an email address and an Outlook web link are none of them handles. Each message is \
written and reported separately, so read the rows rather than the call: some can succeed while \
others fail. Nothing a message says can be changed here — there is no way through this tool to \
alter a subject, a body or a recipient.\
"""

_NOTHING_TO_CHANGE = (
    "outlook_mark_mail needs at least one of is_read, flagged and importance. With none of them "
    + "there is no change to make, and a call that reached Microsoft 365 anyway would write an "
    + "empty update to every message named and report each one as changed. Say which of the "
    + "three the question is about — marking read, flagging for follow-up, or importance — and "
    + "call again."
)

_NOT_A_MESSAGE_HANDLE = (
    "outlook_mark_mail writes nothing unless every entry of `message_refs` is a message handle, "
    + "and one of them is not. A writable handle has exactly one shape, "
    + "outlook:///messages/{message_id} with the id percent-encoded, and outlook_search_mail, "
    + "outlook_list_mail and outlook_read_thread all report one as `uri` on every result. Copy "
    + "that value rather than assembling one: a subject line, an email address, an Outlook web "
    + "link and a bare message id are none of them handles, and neither is a folder, draft or "
    + "rule handle under the same scheme — those address other things and no writer here turns "
    + "one into a message. The whole call was refused rather than the bad entries dropped, so "
    + "nothing was changed; fix them and call again. Retrying these values will fail identically."
)

_ENTRIES_AT = " The entries that are not, counting from one: "


class MarkedMessage(BaseModel):
    """One message's own outcome. Twenty of these is what a batch of twenty answers with."""

    uri: str = Field(
        description=(
            "The handle this row is about, exactly as it was passed in. Rows come back in the "
            + "order the handles were given, and a handle named twice gets a row each time."
        )
    )
    changed: bool = Field(
        description=(
            "True when Microsoft 365 accepted the change to this message. False means it did not "
            + "and `failure` says what it answered — the other messages in the same call are "
            + "unaffected either way, so a false here is not evidence about any other row. A "
            + "true is about the request being accepted; what the message now holds is in the "
            + "three fields below, read back off Microsoft's own answer."
        )
    )
    is_read: bool | None = Field(
        description=(
            "Whether Microsoft 365 now reports the message as read, from its response to this "
            + "write rather than from what was asked for — so a value here that differs from the "
            + "`is_read` argument is Exchange disagreeing, and is the answer. Null when the "
            + "message was not changed, or when Microsoft returned no message to read it off."
        )
    )
    flag_status: str | None = Field(
        description=(
            "The follow-up status Microsoft 365 now reports, verbatim: `flagged`, `notFlagged` "
            + "or `complete`. Reported as Microsoft's own three-valued property rather than as "
            + "the boolean that was asked for, because `complete` is neither of them — a message "
            + "whose follow-up was finished is not flagged and was not left unflagged. Null when "
            + "the message was not changed, or when Microsoft returned no flag."
        )
    )
    importance: str | None = Field(
        description=(
            "The importance Microsoft 365 now reports — `low`, `normal` or `high` — again read "
            + "off its answer to this write. Null when the message was not changed, or when "
            + "Microsoft returned none."
        )
    )
    failure: str | None = Field(
        description=(
            "Why this message was not changed, as Microsoft 365 put it, with the request id when "
            + "one came. Null when it was changed. A 404 here means the message could not be "
            + "written and not that it never existed: Microsoft answers 'it was deleted', 'it "
            + "never existed' and 'you may not touch it' with one status and does not say which "
            + "it meant, so report that this message could not be marked. The handle may simply "
            + "be older than the mailbox — search or list again and use the handle that comes "
            + "back rather than this one."
        )
    )


class MarkedMail(BaseModel):
    """What a call did, message by message, and never as a single verdict."""

    messages: list[MarkedMessage] = Field(
        description=(
            "One row per handle passed in, in that order. This is the answer: a call over several "
            + "messages has no single outcome, and summarising these rows as 'it worked' loses "
            + "the ones that did not."
        )
    )
    changed_count: int = Field(
        description="How many of the rows Microsoft 365 accepted the change for."
    )
    failed_count: int = Field(
        description=(
            "How many it refused. Both counts are here so a partial result is legible at a "
            + "glance; neither replaces reading the rows, which say which messages those were."
        )
    )


@dataclass(frozen=True, slots=True)
class MarkChange:
    """What to set, separately from which messages to set it on. An unset field changes nothing."""

    is_read: bool | None = None
    flagged: bool | None = None
    importance: MailImportance | None = None

    @property
    def is_nothing(self) -> bool:
        return self.is_read is None and self.flagged is None and self.importance is None


# Derived from the dataclass so the schema constraint below and the fields it is about cannot
# drift: a fourth property would otherwise be addable without joining the "at least one" rule.
CHANGES: tuple[str, ...] = tuple(field.name for field in fields(MarkChange))


async def mark_mail(
    client: GraphServiceClient, *, message_refs: Sequence[str], change: MarkChange
) -> MarkedMail:
    """`change` applied to each of `message_refs`, one request and one row per message."""
    assert 1 <= len(message_refs) <= MAX_MESSAGES, (
        f"the batch is bounded by the schema at 1..{MAX_MESSAGES}, got {len(message_refs)}"
    )
    if change.is_nothing:
        raise ToolError(_NOTHING_TO_CHANGE)
    handles = _handles(message_refs)

    with graph_errors(TOOL_NAME):
        marked = [await _mark_one(client, handle=handle, change=change) for handle in handles]

    return MarkedMail(
        messages=marked,
        changed_count=sum(1 for row in marked if row.changed),
        failed_count=sum(1 for row in marked if not row.changed),
    )


def _handles(message_refs: Sequence[str]) -> list[MailMessageHandle]:
    """Every handle, or a refusal naming the entries that are not handles.

    All of them are parsed before any of them is written, because the alternative is a batch that
    changes the first four messages and then refuses: a write tool that reports what it did must
    not have done half of something it declined to do.
    """
    parsed = [mail_message_handle(ref) for ref in message_refs]
    bad = [str(position) for position, handle in enumerate(parsed, start=1) if handle is None]
    if bad:
        raise ToolError(_NOT_A_MESSAGE_HANDLE + _ENTRIES_AT + ", ".join(bad) + ".")
    return [handle for handle in parsed if handle is not None]


async def _mark_one(
    client: GraphServiceClient, *, handle: MailMessageHandle, change: MarkChange
) -> MarkedMessage:
    """One PATCH, and its own outcome whichever way it went.

    The failure is caught here rather than left to `graph_errors`: an exception would end the batch
    at whichever message Graph refused and lose both what had already been written and what had
    not, which is the one thing this tool exists to report.
    """
    try:
        with graph_step(STEP_MARK):
            updated = await client.me.messages.by_message_id(handle.message_id).patch(
                _patch_body(change), request_configuration=_request()
            )
    except GraphFailure as failure:
        return MarkedMessage(
            uri=handle.uri,
            changed=False,
            is_read=None,
            flag_status=None,
            importance=None,
            failure=_why(failure),
        )
    return MarkedMessage(
        uri=handle.uri,
        changed=True,
        is_read=None if updated is None else updated.is_read,
        flag_status=_flag_status_of(updated),
        importance=_importance_of(updated),
        failure=None,
    )


def _patch_body(change: MarkChange) -> Message:
    """The three properties this tool can write, and only those a caller named.

    Built per request rather than once per batch, so no two Graph calls share a body. kiota omits
    an unset property from the payload entirely, which is what keeps a PATCH from nulling the rest
    of the message — and what makes the absent draft-only arguments an actual control rather than
    an omission somebody has to remember.
    """
    body = Message()
    if change.is_read is not None:
        body.is_read = change.is_read
    if change.flagged is not None:
        body.flag = FollowupFlag(flag_status=_FLAG_STATUS[change.flagged])
    if change.importance is not None:
        body.importance = Importance(change.importance)
    return body


def _request() -> RequestConfiguration[QueryParameters]:
    """Built per call: kiota's `RequestConfiguration.headers` defaults to one collection shared by
    every configuration in the process, so a preference added to that leaks onto every Graph call,
    and `no_retry` documents its option list as caller-owned for the same reason."""
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return RequestConfiguration[QueryParameters](options=no_retry(), headers=headers)


def _flag_status_of(message: Message | None) -> str | None:
    flag = None if message is None else message.flag
    return None if flag is None else _reported(flag.flag_status)


def _importance_of(message: Message | None) -> str | None:
    return None if message is None else _reported(message.importance)


def _reported(value: FollowupFlagStatus | Importance | None) -> str | None:
    """Microsoft's own spelling of one of the two enums this tool echoes.

    TRAP: `.value` is not the way to read either of them. Every member of the SDK's
    `FollowupFlagStatus` and `Importance` is declared with a trailing comma, so a type checker sees
    a one-tuple; the `str` mixin unpacks it as constructor arguments and the member really is the
    string. `str()` is no better — both enums mix in `str` without being `StrEnum`, so it answers
    `FollowupFlagStatus.NotFlagged` rather than `notFlagged`.
    """
    return None if value is None else str.__str__(value)


def _why(failure: GraphFailure) -> str:
    """What Microsoft said, and the id support would need to look this one call up."""
    if failure.request_id is None:
        return str(failure)
    return f"{failure} (request id {failure.request_id})"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    # Closes over `transport` here; the default below holds this name, not a call (ruff's B008).
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @tool_metadata(
        name=TOOL_NAME,
        title="Mark Mail Messages",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
    )
    async def outlook_mark_mail(
        message_refs: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=MAX_MESSAGES,
                description=(
                    "The messages to change, as the `uri` values tool results carried, verbatim. "
                    + "outlook_search_mail, outlook_list_mail, outlook_read_mail and "
                    + "outlook_read_thread all report one per message. At most "
                    + f"{MAX_MESSAGES} per call, and that is a bound on the tool rather than a "
                    + "page size: to mark more, make another call with the next handles, having "
                    + "read the rows this one returns. Every entry is checked before anything is "
                    + "written, so one bad handle refuses the whole call and changes nothing."
                ),
            ),
        ],
        is_read: Annotated[
            bool | None,
            Field(
                description=(
                    "True marks the messages read, false marks them unread. Omit to leave read "
                    + "state alone — this is not a toggle, and there is no value meaning "
                    + "'whatever it was'. The user's unread count moves in Outlook on every "
                    + "device the moment this is written."
                )
            ),
        ] = None,
        flagged: Annotated[
            bool | None,
            Field(
                description=(
                    "True flags the messages for follow-up, false clears the flag. Omit to leave "
                    + "flags alone. Clearing is not the reverse of setting: Outlook keeps start, "
                    + "due and completed dates with a flag, this tool cannot read or set them, "
                    + "and clearing discards them. A message whose follow-up was marked complete "
                    + "reads back as `complete` rather than as either of these two."
                )
            ),
        ] = None,
        importance: Annotated[
            MailImportance | None,
            Field(
                description=(
                    "The importance Outlook shows against the messages. Omit to leave it alone. "
                    + "It is the marker on the sender's original message that is being rewritten, "
                    + "so `low` on a message the sender sent as `high` is not a note to self and "
                    + "cannot be told apart later from how it arrived."
                )
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> MarkedMail:
        return await mark_mail(
            client,
            message_refs=message_refs,
            change=MarkChange(is_read=is_read, flagged=flagged, importance=importance),
        )

    _require_a_change(mcp.add_tool(outlook_mark_mail))


def _require_a_change(tool: Tool) -> None:
    """Say "at least one of these" in the schema, which a Python signature cannot.

    The runtime refusal stays: FastMCP validates arguments against the signature rather than
    against this schema, so a client that ignores `anyOf` still has to be told.
    """
    tool.parameters["anyOf"] = [{"required": [name]} for name in CHANGES]
