from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.followup_flag import FollowupFlag
from msgraph.generated.models.followup_flag_status import FollowupFlagStatus
from msgraph.generated.models.importance import Importance
from msgraph.generated.models.message import Message
from msgraph.generated.users.item.messages.item.message_item_request_builder import (
    MessageItemRequestBuilder,
)
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.calendar import ZONE_NAME, wall_clock
from office_365_mcp.shared.categories import (
    LIST_CATEGORIES_GUARD,
    CategoryName,
    merged_categories,
    named_in_both,
)
from office_365_mcp.shared.handles import MailMessageHandle, mail_message_handle
from office_365_mcp.shared.immutable_ids import immutable_id_headers
from office_365_mcp.shared.mail import FlagMoment, MailImportance
from office_365_mcp.shared.odata import spelled
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    Confirmed,
    confirmation_digest,
    graph_client_for_caller,
    graph_mailbox,
    person_confirms,
)

TOOL_NAME = "outlook_mark_mail"

STEP_READ_MESSAGE = "mail_message"
STEP_MARK = "mark_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "message_refs": ["outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"],
    "is_read": True,
}

type FlagStatus = Literal["flagged", "complete", "notFlagged"]

_MessageQuery = MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters

_CATEGORY_FIELDS: tuple[str, ...] = ("categories",)

_FLAG_STATUS: Mapping[bool, FollowupFlagStatus] = {
    True: FollowupFlagStatus.Flagged,
    False: FollowupFlagStatus.NotFlagged,
}

_READ_TEXT: Mapping[bool, str] = {True: "mark them as read", False: "mark them as unread"}

_FLAG_TEXT: Mapping[FollowupFlagStatus, str] = {
    FollowupFlagStatus.Flagged: "flag them for follow-up",
    FollowupFlagStatus.NotFlagged: "clear their follow-up flag",
    FollowupFlagStatus.Complete: "mark their follow-up complete",
}

_AGREE = "change"
_DECLINE = "do not change"
_NOTHING_CHANGED = "No message was changed."

_SOMEONE_ELSES = "That mailbox belongs to someone else, not to the signed-in user."

_DESCRIPTION = """\
Marks messages as read or unread, flags them for follow-up, sets their importance, and adds or \
removes their categories. This tool can also mark a follow-up complete, or give a flag a start \
date and a due date. This tool changes messages in the signed-in user's own mailbox or, with \
`mailbox`, in a shared or delegated one. outlook_move_mail is the tool that moves messages to \
another folder.

Notes:
- This tool changes each message separately. If one message fails, this tool still changes the \
other messages, and the row of that message gives the reason.
- This tool asks the user to agree before it changes a shared or delegated mailbox. It changes \
the user's own mailbox without a question.
"""

_RETRY = " If you call this tool again with the same arguments, the call will fail the same way."

_NOTHING_TO_CHANGE = (
    "outlook_mark_mail needs at least one of `is_read`, `flagged`, `flag_status`, "
    + "`flag_starts_at`, `importance`, `add_categories` and `remove_categories`. With none of "
    + f"them, there is nothing to change. {_NOTHING_CHANGED} Find out which change the user "
    + "asked for, and then call again."
)

_BOTH_FLAG_FORMS = (
    "`flagged` and `flag_status` both set the follow-up status, so this tool takes only one of "
    + "them. `flagged` is the short form. True is `flagged`, and false is `notFlagged`. Remove "
    + f"one of the two and call again. {_NOTHING_CHANGED}{_RETRY}"
)

_DUE_NEEDS_START = (
    "`flag_due_at` needs `flag_starts_at`, because Microsoft 365 refuses a due date without a "
    + f"start date. Add a start date and call again. {_NOTHING_CHANGED}{_RETRY}"
)

_START_NEEDS_ZONE = (
    "`flag_starts_at` and `flag_due_at` need `flag_time_zone`, because a wall-clock time "
    + "without a zone is not one moment. If you do not know the zone, ask the user. Then add "
    + f"`flag_time_zone` and call again. {_NOTHING_CHANGED}{_RETRY}"
)

_ZONE_NEEDS_START = (
    "`flag_time_zone` is the zone of `flag_starts_at` and `flag_due_at`, and this call has "
    + "neither of them. Add a start date, or remove `flag_time_zone`. "
    + f"{_NOTHING_CHANGED}{_RETRY}"
)

_DUE_BEFORE_START = (
    "`flag_due_at` is before `flag_starts_at`, and a follow-up cannot be due before it starts. "
    + "Both times are in `flag_time_zone`. Find out which time the user means, and then call "
    + f"again. {_NOTHING_CHANGED}{_RETRY}"
)

_DATES_NEED_FLAGGED = (
    "A start date and a due date go only with the status `flagged`. This call also clears the "
    + "flag or marks it complete. Remove the dates, or set `flag_status` to `flagged`. "
    + f"{_NOTHING_CHANGED}{_RETRY}"
)


def _not_a_time(argument: str, value: str) -> str:
    return (
        f"outlook_mark_mail cannot read {value!r} in `{argument}` as a time. Write "
        + "`YYYY-MM-DDTHH:MM` or `YYYY-MM-DDTHH:MM:SS`, for example `2026-03-02T14:00`. Do not "
        + "add an offset or a `Z`. Put the zone in `flag_time_zone`. "
        + f"{_NOTHING_CHANGED}{_RETRY}"
    )


def _in_both_lists(name: str) -> str:
    return (
        f"The category {name!r} is in both `add_categories` and `remove_categories`. Put each "
        + "category name in one list only. A different case is not a different category. "
        + f"{_NOTHING_CHANGED}{_RETRY}"
    )


_NOT_A_MESSAGE_HANDLE = (
    "outlook_mark_mail writes nothing unless every entry of `message_refs` is a message handle, "
    + "and one of them is not. A writable handle has exactly one shape: "
    + "outlook:///messages/{message_id}, with the id percent-encoded. outlook_search_mail, "
    + "outlook_list_mail and outlook_read_thread all report this value as `uri` on every result. "
    + "Copy that value. Do not assemble one yourself. A subject line, an email address, an "
    + "Outlook web link and a bare message id are not handles. A folder or rule handle "
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
    flag_start: FlagMoment | None = Field(
        description=(
            "When the follow-up starts, as Microsoft 365 now reports it. The value is null if "
            "the flag has no start date, or if the message did not change."
        )
    )
    flag_due: FlagMoment | None = Field(
        description=(
            "When the follow-up is due, as Microsoft 365 now reports it. The value is null if "
            "the flag has no due date, or if the message did not change."
        )
    )
    categories: list[str] | None = Field(
        description=(
            "The categories that Microsoft 365 now reports on the message, in its order. The "
            "value is null if Microsoft 365 reports no list, or if the message did not change."
        )
    )
    failure: str | None = Field(
        description=(
            "Why this message did not change. If Microsoft 365 accepted the change, the value is "
            "null. If Microsoft 365 answered with an error, the value gives the HTTP status, the "
            "error code and the request id. If the connector did not get an answer that it can "
            "read, the value says why."
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
        description=(
            "How many messages did not change. `messages` shows which ones. If no message "
            "changed, the call gives an error instead of this result."
        )
    )


@dataclass(frozen=True, slots=True)
class MarkChange:
    is_read: bool | None = None
    flagged: bool | None = None
    importance: MailImportance | None = None
    flag_status: FlagStatus | None = None
    flag_starts_at: str | None = None
    flag_due_at: str | None = None
    flag_time_zone: str | None = None
    add_categories: tuple[str, ...] = ()
    remove_categories: tuple[str, ...] = ()

    @property
    def is_nothing(self) -> bool:
        return self == MarkChange()


@dataclass(frozen=True, slots=True)
class _Attempt:
    row: MarkedMessage
    failure: GraphFailure | None


async def mark_mail(
    client: GraphServiceClient,
    *,
    message_refs: Sequence[str],
    change: MarkChange,
    confirm: Confirm,
    mailbox: str | None = None,
) -> MarkedMail | InputRequiredResult:
    assert len(message_refs) >= 1, "the schema admits no empty batch"
    refused = _refusal(change)
    if refused is not None:
        raise ToolError(refused)
    handles = _handles(message_refs)
    reached = graph_mailbox(client, mailbox)

    answer: Confirmed = None
    attempts: list[_Attempt] = []
    with graph_errors(TOOL_NAME):
        if mailbox is not None:
            with not_graph():
                answer = await confirm(
                    _question(mailbox, len(handles), change), _about(mailbox, handles, change)
                )
        if answer is None:
            attempts = [
                await _mark_one(reached, handle=handle, change=change) for handle in handles
            ]
            _raise_when_nothing_changed(attempts)

    if isinstance(answer, InputRequiredResult):
        return answer
    if answer is not None:
        raise ToolError(answer)

    marked = [attempt.row for attempt in attempts]
    return MarkedMail(
        messages=marked,
        changed_count=sum(1 for row in marked if row.changed),
        failed_count=sum(1 for row in marked if not row.changed),
    )


def _refusal(change: MarkChange) -> str | None:
    if change.is_nothing:
        return _NOTHING_TO_CHANGE
    if change.flagged is not None and change.flag_status is not None:
        return _BOTH_FLAG_FORMS
    return _dates_refusal(change) or _categories_refusal(change)


def _dates_refusal(change: MarkChange) -> str | None:
    if change.flag_starts_at is None:
        if change.flag_due_at is not None:
            return _DUE_NEEDS_START
        return None if change.flag_time_zone is None else _ZONE_NEEDS_START
    if change.flag_time_zone is None:
        return _START_NEEDS_ZONE
    if _status_of(change) != FollowupFlagStatus.Flagged:
        return _DATES_NEED_FLAGGED
    starts = wall_clock(change.flag_starts_at)
    if starts is None:
        return _not_a_time("flag_starts_at", change.flag_starts_at)
    if change.flag_due_at is None:
        return None
    due = wall_clock(change.flag_due_at)
    if due is None:
        return _not_a_time("flag_due_at", change.flag_due_at)
    return _DUE_BEFORE_START if due < starts else None


def _categories_refusal(change: MarkChange) -> str | None:
    both = named_in_both(change.add_categories, change.remove_categories)
    return None if both is None else _in_both_lists(both)


def _status_of(change: MarkChange) -> FollowupFlagStatus | None:
    if change.flagged is not None:
        return _FLAG_STATUS[change.flagged]
    if change.flag_status is not None:
        return FollowupFlagStatus(change.flag_status)
    if change.flag_starts_at is not None:
        return FollowupFlagStatus.Flagged
    return None


def _question(mailbox: str, count: int, change: MarkChange) -> str:
    return (
        f"Change {count} {'message' if count == 1 else 'messages'} in the mailbox "
        + f"{cut_for_a_question(mailbox)!r}? This tool will {_changes(change)}. "
        + _SOMEONE_ELSES
    )


def _changes(change: MarkChange) -> str:
    parts = [
        text
        for text in (
            None if change.is_read is None else _READ_TEXT[change.is_read],
            _flag_text(change),
            None if change.importance is None else f"set their importance to {change.importance}",
            _categories_text("add", change.add_categories),
            _categories_text("remove", change.remove_categories),
        )
        if text is not None
    ]
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _flag_text(change: MarkChange) -> str | None:
    status = _status_of(change)
    if status is None:
        return None
    if change.flag_starts_at is None:
        return _FLAG_TEXT[status]
    due = "" if change.flag_due_at is None else f" to {change.flag_due_at}"
    return f"{_FLAG_TEXT[status]} from {change.flag_starts_at}{due} in {change.flag_time_zone}"


def _categories_text(verb: str, names: Sequence[str]) -> str | None:
    if not names:
        return None
    noun = "category" if len(names) == 1 else "categories"
    return f"{verb} the {noun} {cut_for_a_question(', '.join(names))!r}"


def _about(mailbox: str, handles: Sequence[MailMessageHandle], change: MarkChange) -> str:
    return confirmation_digest(mailbox, asdict(change), [handle.uri for handle in handles])


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_CHANGED)


def _handles(message_refs: Sequence[str]) -> list[MailMessageHandle]:
    parsed = [mail_message_handle(ref) for ref in message_refs]
    bad = [str(position) for position, handle in enumerate(parsed, start=1) if handle is None]
    if bad:
        raise ToolError(_NOT_A_MESSAGE_HANDLE + _ENTRIES_AT + ", ".join(bad) + ".")
    return [handle for handle in parsed if handle is not None]


async def _mark_one(
    reached: UserItemRequestBuilder, *, handle: MailMessageHandle, change: MarkChange
) -> _Attempt:
    try:
        categories = await _categories_after(reached, handle=handle, change=change)
        with graph_step(STEP_MARK):
            updated = await reached.messages.by_message_id(handle.message_id).patch(
                _patch_body(change, categories=categories), request_configuration=_request()
            )
    except GraphFailure as failure:
        return _Attempt(
            row=MarkedMessage(
                uri=handle.uri,
                changed=False,
                is_read=None,
                flag_status=None,
                importance=None,
                flag_start=None,
                flag_due=None,
                categories=None,
                failure=_why(failure),
            ),
            failure=failure,
        )
    flag = None if updated is None else updated.flag
    return _Attempt(
        row=MarkedMessage(
            uri=handle.uri,
            changed=True,
            is_read=None if updated is None else updated.is_read,
            flag_status=_flag_status_of(updated),
            importance=_importance_of(updated),
            flag_start=None if flag is None else FlagMoment.from_moment(flag.start_date_time),
            flag_due=None if flag is None else FlagMoment.from_moment(flag.due_date_time),
            categories=None if updated is None else updated.categories,
            failure=None,
        ),
        failure=None,
    )


async def _categories_after(
    reached: UserItemRequestBuilder, *, handle: MailMessageHandle, change: MarkChange
) -> list[str] | None:
    if not change.add_categories and not change.remove_categories:
        return None
    with graph_step(STEP_READ_MESSAGE):
        current = await reached.messages.by_message_id(handle.message_id).get(
            request_configuration=RequestConfiguration[_MessageQuery](
                query_parameters=_MessageQuery(select=list(_CATEGORY_FIELDS)),
                headers=immutable_id_headers(),
            )
        )
    assert current is not None, "Graph answered a message read with no message"
    return merged_categories(
        current.categories or [], add=change.add_categories, remove=change.remove_categories
    )


def _raise_when_nothing_changed(attempts: Sequence[_Attempt]) -> None:
    failures = [attempt.failure for attempt in attempts if attempt.failure is not None]
    if len(failures) == len(attempts):
        raise failures[0]


def _patch_body(change: MarkChange, *, categories: list[str] | None) -> Message:
    status = _status_of(change)
    return Message(
        is_read=change.is_read,
        flag=(
            None
            if status is None
            else FollowupFlag(
                flag_status=status,
                start_date_time=_flag_moment(change.flag_starts_at, change.flag_time_zone),
                due_date_time=_flag_moment(change.flag_due_at, change.flag_time_zone),
            )
        ),
        importance=None if change.importance is None else Importance(change.importance),
        categories=categories,
    )


def _flag_moment(date_time: str | None, time_zone: str | None) -> DateTimeTimeZone | None:
    return None if date_time is None else DateTimeTimeZone(date_time=date_time, time_zone=time_zone)


def _request() -> RequestConfiguration[QueryParameters]:
    return RequestConfiguration[QueryParameters](options=no_retry(), headers=immutable_id_headers())


def _flag_status_of(message: Message | None) -> str | None:
    flag = None if message is None else message.flag
    return spelled(None if flag is None else flag.flag_status)


def _importance_of(message: Message | None) -> str | None:
    return spelled(None if message is None else message.importance)


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
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_mark_mail(
        message_refs: Annotated[
            list[str],
            Field(
                min_length=1,
                description=(
                    "The messages to change: `uri` values from a search, list, read, or thread "
                    "result."
                ),
            ),
        ],
        add_categories: Annotated[
            list[CategoryName],
            Field(
                default=[],
                description=(
                    "The category names to add to each message, exactly as the user names them. "
                    + LIST_CATEGORIES_GUARD
                    + " This tool keeps the other categories of the message. It does not add a "
                    + "name that the message already has. This match ignores case."
                ),
            ),
        ],
        remove_categories: Annotated[
            list[CategoryName],
            Field(
                default=[],
                description=(
                    "The category names to remove from each message. The match ignores case. "
                    + "A name that the message does not have changes nothing. A name cannot be "
                    + "in both this list and `add_categories`."
                ),
            ),
        ],
        ctx: Context,
        is_read: Annotated[
            bool | None,
            Field(description="True marks the messages read, false marks them unread."),
        ] = None,
        flagged: Annotated[
            bool | None,
            Field(
                description=(
                    "True flags the messages for follow-up, and false clears the flag. This is "
                    + "the short form of `flag_status`."
                )
            ),
        ] = None,
        flag_status: Annotated[
            FlagStatus | None,
            Field(
                description=(
                    "The follow-up status to set: `flagged`, `complete`, or `notFlagged`. The "
                    + "status `complete` marks the follow-up as done. Give this argument or "
                    + "`flagged`, but not both."
                )
            ),
        ] = None,
        flag_starts_at: Annotated[
            str | None,
            Field(
                description=(
                    "When the follow-up starts, as a wall-clock time in `flag_time_zone`: "
                    + "`YYYY-MM-DDTHH:MM` or `YYYY-MM-DDTHH:MM:SS`, with no offset and no `Z`. "
                    + "A date sets the status `flagged` and cannot go with `complete` or "
                    + "`notFlagged`."
                )
            ),
        ] = None,
        flag_due_at: Annotated[
            str | None,
            Field(
                description=(
                    "When the follow-up is due, in the same form and zone as `flag_starts_at`, "
                    + "and not before it. A due date needs `flag_starts_at`, because Microsoft "
                    + "365 refuses a due date without a start date."
                )
            ),
        ] = None,
        flag_time_zone: Annotated[
            str | None,
            Field(
                min_length=1,
                pattern=ZONE_NAME,
                description=(
                    "The time zone of `flag_starts_at` and `flag_due_at`. It can be an IANA name "
                    + "such as `Europe/Berlin`, a Windows name such as `W. Europe Standard Time`, "
                    + "or `UTC`. This value reaches Microsoft 365 exactly as written. If you do "
                    + "not know the zone, ask the user."
                ),
            ),
        ] = None,
        importance: Annotated[
            MailImportance | None,
            Field(description="The importance to set: `low`, `normal`, or `high`."),
        ] = None,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> MarkedMail | InputRequiredResult:
        return await mark_mail(
            client,
            message_refs=message_refs,
            change=MarkChange(
                is_read=is_read,
                flagged=flagged,
                flag_status=flag_status,
                flag_starts_at=flag_starts_at,
                flag_due_at=flag_due_at,
                flag_time_zone=flag_time_zone,
                importance=importance,
                add_categories=tuple(add_categories),
                remove_categories=tuple(remove_categories),
            ),
            confirm=a_person_agrees(ctx),
            mailbox=mailbox,
        )
