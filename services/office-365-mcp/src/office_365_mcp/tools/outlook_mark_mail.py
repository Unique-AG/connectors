"""`outlook_mark_mail` — read state, follow-up flag and importance, on up to twenty messages.

This is the first tool in this connector that changes data. Its design is about what a write
can do. It is not about the details of Graph itself.

**Three properties are writable. The signature controls the rest.** The arguments and the PATCH
body both leave out `subject`, `body`, `toRecipients` and `ccRecipients`. This absence is the
whole guard. Microsoft Graph allows a write to those four properties only while `isDraft` is
true. Graph does not document what a PATCH of one of them does against a message that was
already sent. No filter downstream removes these properties, because no argument upstream can
name them. Kiota, the SDK, does not serialize a property that nobody set. So the body this tool
builds contains exactly the properties the call asked to change, and nothing more.

**`destructiveHint` is true. `WRITE_ADDITIVE` is not correct here.** MCP defines a non-destructive
tool as one that performs "only additive updates". Clearing a follow-up flag is not additive.
Exchange keeps `startDateTime`, `dueDateTime` and `completedDateTime` on `followupFlag`. This
tool never reads these three fields. `flagStatus: notFlagged` discards all three. Setting a lower
importance, or marking a message read, also overwrites state that this tool never read first.

**Each message gets one PATCH. The answer has one row per message.** A single combined result
cannot honestly answer "did it work?" for twenty messages with one true or false value. Graph can
answer 404 for one message whose handle went stale, while it writes the other nineteen without
error. So each write is its own request. Each failure is caught where it happens, and the caller
reads the per-message rows. A missing consent cannot produce this shape: the On-Behalf-Of token
exchange fails before this function runs. So a 403 in one row is about that one message, not
about the connector's own consent.

**The report comes from the PATCH response, never from the arguments.** Graph answers a message
PATCH with the updated message. So `isRead`, `flag.flagStatus` and `importance` come back from
Exchange, and this tool echoes them from there. A tool that reports its own arguments instead
claims success in exactly the case that needs catching: the case where Exchange accepts the
request and stores something different, or stores nothing.

**Every PATCH uses `no_retry()`.** A PATCH of these three properties is idempotent, so double
application is not the risk. The risk is that the retry logic turns one row into an unknown
number of attempts, spread over a `Retry-After` wait. This tool promises that its answer states
exactly what it did, once. The SDK retries every HTTP verb by default, and `GRAPH_MAX_RETRIES`
defaults to 3.

**`Prefer: IdType="ImmutableId"` goes on every request.** The handle carries the immutable id
that `outlook_search_mail` and `outlook_list_mail` mint. Graph reads a path id in whichever id
space the request declares. Without this header, Graph reads the immutable id as a `RestId`, and
every row becomes a 404. `outlook_read_mail` sends the same header, for the same reason.
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

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "message_refs": ["outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"],
    "is_read": True,
}

# One call must not touch a whole mailbox. Twenty is the full batch size this tool offers.
# The schema publishes this limit, the worker asserts it, and there is no page two.
MAX_MESSAGES = 20

type MailImportance = Literal["low", "normal", "high"]

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_FLAG_STATUS: Mapping[bool, FollowupFlagStatus] = {
    True: FollowupFlagStatus.Flagged,
    False: FollowupFlagStatus.NotFlagged,
}

_DESCRIPTION = f"""\
Change how up to {MAX_MESSAGES} messages are marked in the signed-in user's own mailbox. You \
can change three things: read or unread state, the follow-up flag, and the importance Outlook \
shows for each message. THIS CHANGES THE MAILBOX. The change is immediate, and this connector \
cannot undo it. No tool here restores a previous state. The user sees the change in Outlook on \
every device. An unread count moves, a flag appears in or leaves the follow-up list, and an \
importance marker changes. If `flagged` is set to false, this also erases the follow-up dates \
that Outlook stored with the flag. Pass at least one of `is_read`, `flagged` and `importance`. \
Every value given applies to every message named, so one call makes one change to one set of \
messages. `message_refs` takes the `uri` value from a tool result, copied exactly. A subject \
line, an email address and an Outlook web link are not handles. Each message is written and \
reported separately. Read the rows, not only the call result: some can succeed while others \
fail. This tool cannot change what a message says. There is no way here to alter a subject, a \
body or a recipient.\
"""

_NOTHING_TO_CHANGE = (
    "outlook_mark_mail needs at least one of is_read, flagged and importance. With none of them, "
    + "there is nothing to change. If a call reaches Microsoft 365 anyway, it writes an empty "
    + "update to every message named, and reports each one as changed. Say which of the three "
    + "the question is about: marking read, flagging for follow-up, or importance. Then call "
    + "again."
)

_NOT_A_MESSAGE_HANDLE = (
    "outlook_mark_mail writes nothing unless every entry of `message_refs` is a message handle, "
    + "and one of them is not. A writable handle has exactly one shape: "
    + "outlook:///messages/{message_id}, with the id percent-encoded. outlook_search_mail, "
    + "outlook_list_mail and outlook_read_thread all report this value as `uri` on every result. "
    + "Copy that value. Do not assemble one yourself. A subject line, an email address, an "
    + "Outlook web link and a bare message id are not handles. A folder, draft or rule handle "
    + "under the same scheme is not a message handle either. Those address other things, and no "
    + "writer here turns one into a message. This tool refused the whole call instead of dropping "
    + "the bad entries, so nothing changed. Fix them and call again. Retrying these same values "
    + "will fail identically."
)

_ENTRIES_AT = " The entries that are not, counting from one: "


class MarkedMessage(BaseModel):
    """One message's own outcome. A batch of twenty messages answers with twenty of these."""

    uri: str = Field(
        description=(
            "The handle this row is about, exactly as it was passed in. Rows come back in the "
            + "order the handles were given, and a handle named twice gets a row each time."
        )
    )
    changed: bool = Field(
        description=(
            "True when Microsoft 365 accepted the change to this message. False means it did "
            + "not, and `failure` states what Microsoft answered. The other messages in the same "
            + "call are unaffected either way, so a false here is not evidence about any other "
            + "row. A true means only that Microsoft accepted the request. What the message now "
            + "holds is in the three fields below, read back from Microsoft's own answer."
        )
    )
    is_read: bool | None = Field(
        description=(
            "Whether Microsoft 365 now reports the message as read. This value comes from the "
            + "response to this write, not from what the call asked for. A value here that "
            + "differs from the `is_read` argument means Exchange disagreed, and that is the "
            + "answer. Null when the message was not changed, or when Microsoft returned no "
            + "message to read the value from."
        )
    )
    flag_status: str | None = Field(
        description=(
            "The follow-up status Microsoft 365 now reports, exactly as Microsoft states it: "
            + "`flagged`, `notFlagged` or `complete`. This tool reports Microsoft's own "
            + "three-value property instead of the true or false value the call asked for, "
            + "because `complete` is neither one. A message whose follow-up is finished is not "
            + "flagged, and is not left unflagged either. Null when the message was not changed, "
            + "or when Microsoft returned no flag."
        )
    )
    importance: str | None = Field(
        description=(
            "The importance Microsoft 365 now reports: `low`, `normal` or `high`. This value is "
            + "read from Microsoft's response to this write. Null when the message was not "
            + "changed, or when Microsoft returned none."
        )
    )
    failure: str | None = Field(
        description=(
            "Why this message was not changed, as Microsoft 365 stated it, with the request id "
            + "when one came. Null when the change succeeded. A 404 here means the write did "
            + "not happen, not that the message never existed. Microsoft answers 'it was "
            + "deleted', 'it never existed' and 'you cannot touch it' with the same one status, "
            + "and does not say which one it meant. So this field reports only that the message "
            + "was not marked. The handle can simply be older than the mailbox. Search or list "
            + "again, and use the handle that comes back instead of this one."
        )
    )


class MarkedMail(BaseModel):
    """What a call did, message by message, and never as a single verdict."""

    messages: list[MarkedMessage] = Field(
        description=(
            "One row per handle passed in, in that order. This is the answer: a call over "
            + "several messages has no single outcome. A summary of 'it worked' loses the "
            + "messages that did not."
        )
    )
    changed_count: int = Field(
        description="How many of the rows Microsoft 365 accepted the change for."
    )
    failed_count: int = Field(
        description=(
            "How many it refused. Both counts are here so a partial result is clear at a "
            + "glance. Neither replaces reading the rows, which say which messages those were."
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


# Derived from the dataclass fields, so the schema constraint below and the fields cannot drift
# apart. Without this, a new field does not join the "at least one" rule by itself.
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
    """Every handle, or a refusal that names the entries that are not handles.

    This function parses every handle before it writes any message. The alternative is a batch
    that changes the first four messages and then refuses. A write tool must report what it
    truly did, and must not refuse an action that it partly completed.
    """
    parsed = [mail_message_handle(ref) for ref in message_refs]
    bad = [str(position) for position, handle in enumerate(parsed, start=1) if handle is None]
    if bad:
        raise ToolError(_NOT_A_MESSAGE_HANDLE + _ENTRIES_AT + ", ".join(bad) + ".")
    return [handle for handle in parsed if handle is not None]


async def _mark_one(
    client: GraphServiceClient, *, handle: MailMessageHandle, change: MarkChange
) -> MarkedMessage:
    """One PATCH, and its own outcome, whichever way it went.

    This function catches the failure here instead of leaving it to `graph_errors`. An exception
    here ends the batch at the message Graph refused, and loses the record of what was already
    written and what was not. Reporting that record is the one thing this tool exists to do.
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
    """The three properties this tool can write, and only the ones a caller named.

    This function builds the body once per request, not once per batch, so no two Graph calls
    share a body. Kiota omits an unset property from the payload entirely. This is what keeps a
    PATCH from wiping out the rest of the message. It is also what makes the absent draft-only
    arguments a real control, not an omission someone has to remember.
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
    """Built per call. Kiota's `RequestConfiguration.headers` defaults to one collection shared
    by every configuration in the process, so a preference added to it leaks onto every Graph
    call. `no_retry` documents its option list as caller-owned, for the same reason."""
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return RequestConfiguration[QueryParameters](options=no_retry(), headers=headers)


def _flag_status_of(message: Message | None) -> str | None:
    flag = None if message is None else message.flag
    return None if flag is None else _reported(flag.flag_status)


def _importance_of(message: Message | None) -> str | None:
    return None if message is None else _reported(message.importance)


def _reported(value: FollowupFlagStatus | Importance | None) -> str | None:
    """Microsoft's own spelling for one of the two enums this tool echoes.

    TRAP: `.value` is not the way to read either enum. Every member of the SDK's
    `FollowupFlagStatus` and `Importance` is declared with a trailing comma. A type checker sees
    a one-tuple because of this comma, but the `str` mixin unpacks it as constructor arguments,
    so the member really is the plain string. `str()` is no better. Both enums mix in `str`
    without being a `StrEnum`, so `str()` answers `FollowupFlagStatus.NotFlagged` instead of
    `notFlagged`.
    """
    return None if value is None else str.__str__(value)


def _why(failure: GraphFailure) -> str:
    """What Microsoft said, and the id support needs to look up this one call."""
    if failure.request_id is None:
        return str(failure)
    return f"{failure} (request id {failure.request_id})"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
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
                    "The messages to change, as the `uri` values from tool results, copied "
                    + "exactly. outlook_search_mail, outlook_list_mail, outlook_read_mail and "
                    + "outlook_read_thread each report one per message. At most "
                    + f"{MAX_MESSAGES} per call. This is a bound on the tool, not a page size: "
                    + "to mark more, read the rows this call returns, then make another call "
                    + "with the next handles. Every entry is checked before anything is "
                    + "written, so one bad handle refuses the whole call and changes nothing."
                ),
            ),
        ],
        is_read: Annotated[
            bool | None,
            Field(
                description=(
                    "True marks the messages read, false marks them unread. Omit this argument "
                    + "to leave read state alone. This is not a toggle, and there is no value "
                    + "that means 'whatever it was'. The user's unread count moves in Outlook on "
                    + "every device the moment this write lands."
                )
            ),
        ] = None,
        flagged: Annotated[
            bool | None,
            Field(
                description=(
                    "True flags the messages for follow-up, false clears the flag. Omit to leave "
                    + "flags alone. Setting and clearing a flag are not opposites: Outlook keeps "
                    + "start, due and completed dates with a flag, and this tool cannot read or "
                    + "set them. Clearing the flag discards those three dates. A message whose "
                    + "follow-up was marked complete reads back as `complete`, not as either "
                    + "true or false."
                )
            ),
        ] = None,
        importance: Annotated[
            MailImportance | None,
            Field(
                description=(
                    "The importance Outlook shows against the messages. Omit this argument to "
                    + "leave it alone. This write rewrites the marker on the sender's original "
                    + "message, so a `low` value on a message the sender sent as `high` is not "
                    + "a private note. It cannot be told apart later from how the message "
                    + "arrived."
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
    """Say "at least one of these" in the schema. A Python signature cannot say that.

    The runtime refusal stays. FastMCP validates arguments against the signature, not against
    this schema, so a client that ignores `anyOf` still needs to be told.
    """
    tool.parameters["anyOf"] = [{"required": [name]} for name in CHANGES]
