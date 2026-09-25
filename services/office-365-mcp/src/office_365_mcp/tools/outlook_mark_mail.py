from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.followup_flag import FollowupFlag
from msgraph.generated.models.followup_flag_status import FollowupFlagStatus
from msgraph.generated.models.importance import Importance
from msgraph.generated.models.message import Message
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step, no_retry
from office_365_mcp.shared.handles import MailMessageHandle, mail_message_handle
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    WRITE_DESTRUCTIVE,
    graph_client_for_caller,
    graph_mailbox,
)

TOOL_NAME = "outlook_mark_mail"

STEP_MARK = "mark_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "message_refs": ["outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"],
    "is_read": True,
}

MAX_MESSAGES = 20

type MailImportance = Literal["low", "normal", "high"]

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_FLAG_STATUS: Mapping[bool, FollowupFlagStatus] = {
    True: FollowupFlagStatus.Flagged,
    False: FollowupFlagStatus.NotFlagged,
}

_DESCRIPTION = (
    f"Marks up to {MAX_MESSAGES} messages as read or unread, flags them for follow-up, or "
    "sets their importance, in the signed-in user's own mailbox or, with `mailbox`, a shared "
    "or delegated one."
)

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

_ENTRIES_AT = " The entries that are not, numbered from one: "


class MarkedMessage(BaseModel):
    uri: str = Field(description="The handle this row is about, exactly as the request passed it.")
    changed: bool = Field(
        description=(
            "Whether Microsoft 365 accepted the write for this message; false means `failure` "
            "states why."
        )
    )
    is_read: bool | None = Field(
        description=(
            "Whether Microsoft 365 now reports the message as read; null if this tool did not "
            "change it."
        )
    )
    flag_status: str | None = Field(
        description=(
            "The follow-up status Microsoft 365 now reports (`flagged`, `notFlagged`, or "
            "`complete`); null if unchanged."
        )
    )
    importance: str | None = Field(
        description=(
            "The importance Microsoft 365 now reports (`low`, `normal`, or `high`); null if "
            "unchanged."
        )
    )
    failure: str | None = Field(
        description=(
            "Why Microsoft 365 did not change this message, as it stated it; null if the "
            "change succeeded."
        )
    )


class MarkedMail(BaseModel):
    messages: list[MarkedMessage] = Field(
        description="One row per handle in `message_refs`, in that order."
    )
    changed_count: int = Field(
        description="How many of the rows Microsoft 365 accepted the change for."
    )
    failed_count: int = Field(
        description="How many messages Microsoft 365 refused; see `messages` for which ones."
    )


@dataclass(frozen=True, slots=True)
class MarkChange:
    is_read: bool | None = None
    flagged: bool | None = None
    importance: MailImportance | None = None

    @property
    def is_nothing(self) -> bool:
        return self.is_read is None and self.flagged is None and self.importance is None


async def mark_mail(
    client: GraphServiceClient,
    *,
    message_refs: Sequence[str],
    change: MarkChange,
    mailbox: str | None = None,
) -> MarkedMail:
    assert 1 <= len(message_refs) <= MAX_MESSAGES, (
        f"the batch is bounded by the schema at 1..{MAX_MESSAGES}, got {len(message_refs)}"
    )
    if change.is_nothing:
        raise ToolError(_NOTHING_TO_CHANGE)
    handles = _handles(message_refs)
    reached = graph_mailbox(client, mailbox)

    with graph_errors(TOOL_NAME):
        marked = [await _mark_one(reached, handle=handle, change=change) for handle in handles]

    return MarkedMail(
        messages=marked,
        changed_count=sum(1 for row in marked if row.changed),
        failed_count=sum(1 for row in marked if not row.changed),
    )


def _handles(message_refs: Sequence[str]) -> list[MailMessageHandle]:
    parsed = [mail_message_handle(ref) for ref in message_refs]
    bad = [str(position) for position, handle in enumerate(parsed, start=1) if handle is None]
    if bad:
        raise ToolError(_NOT_A_MESSAGE_HANDLE + _ENTRIES_AT + ", ".join(bad) + ".")
    return [handle for handle in parsed if handle is not None]


async def _mark_one(
    reached: UserItemRequestBuilder, *, handle: MailMessageHandle, change: MarkChange
) -> MarkedMessage:
    try:
        with graph_step(STEP_MARK):
            updated = await reached.messages.by_message_id(handle.message_id).patch(
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
    body = Message()
    if change.is_read is not None:
        body.is_read = change.is_read
    if change.flagged is not None:
        body.flag = FollowupFlag(flag_status=_FLAG_STATUS[change.flagged])
    if change.importance is not None:
        body.importance = Importance(change.importance)
    return body


def _request() -> RequestConfiguration[QueryParameters]:
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return RequestConfiguration[QueryParameters](options=no_retry(), headers=headers)


def _flag_status_of(message: Message | None) -> str | None:
    flag = None if message is None else message.flag
    return None if flag is None else _reported(flag.flag_status)


def _importance_of(message: Message | None) -> str | None:
    return None if message is None else _reported(message.importance)


def _reported(value: FollowupFlagStatus | Importance | None) -> str | None:
    return None if value is None else str.__str__(value)


def _why(failure: GraphFailure) -> str:
    if failure.request_id is None:
        return str(failure)
    return f"{failure} (request id {failure.request_id})"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
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
                    f"The messages to change: up to {MAX_MESSAGES} `uri` values from a search, "
                    "list, read, or thread result."
                ),
            ),
        ],
        is_read: Annotated[
            bool | None,
            Field(description="True marks the messages read, false marks them unread."),
        ] = None,
        flagged: Annotated[
            bool | None,
            Field(description="True flags the messages for follow-up, false clears the flag."),
        ] = None,
        importance: Annotated[
            MailImportance | None,
            Field(description="The importance to set: `low`, `normal`, or `high`."),
        ] = None,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> MarkedMail:
        return await mark_mail(
            client,
            message_refs=message_refs,
            change=MarkChange(is_read=is_read, flagged=flagged, importance=importance),
            mailbox=mailbox,
        )
