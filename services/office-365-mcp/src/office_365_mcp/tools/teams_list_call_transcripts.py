"""Graph's delegated getAllTranscripts route requires the user's object ID and unquoted start and
end bounds, and returns 404 UnknownError when no transcripts exist."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.chats.item.messages.messages_request_builder import MessagesRequestBuilder
from msgraph.generated.models.call_ended_event_message_detail import CallEndedEventMessageDetail
from msgraph.generated.models.call_started_event_message_detail import (
    CallStartedEventMessageDetail,
)
from msgraph.generated.models.call_transcript import CallTranscript
from msgraph.generated.models.call_transcript_event_message_detail import (
    CallTranscriptEventMessageDetail,
)
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.identity_set import IdentitySet
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.generated.organization.organization_request_builder import OrganizationRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    MAX_SCANNED_ITEMS,
    collect_pages,
    graph_errors,
    graph_step,
)
from office_365_mcp.shared.handles import CHAT_PERMISSION, CallTranscriptHandle
from office_365_mcp.shared.identity import GRAPH_PERMISSION as USER_PERMISSION
from office_365_mcp.shared.identity import signed_in_user
from office_365_mcp.shared.meetings import MAX_ARTIFACT_SCAN, newest_of, user_id_of
from office_365_mcp.shared.messages import unknown_enum_headers
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.transcripts import CALL_TRANSCRIPT_PERMISSION
from office_365_mcp.shared.window import as_utc, closes_at, opens_at

TOOL_NAME = "teams_list_call_transcripts"

STEP_TRANSCRIPTS = "call_transcripts"
STEP_TENANT = "home_tenant"
STEP_CHAT = "chat_call_events"

GRAPH_PERMISSIONS: tuple[str, ...] = (USER_PERMISSION, CHAT_PERMISSION, CALL_TRANSCRIPT_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "created_after": "2026-03-02",
    "created_before": "2026-03-08",
    "chat_id": "19:release@thread.v2",
}

DEFAULT_WINDOW = timedelta(days=7)

# Transcripts were seen in the listing 1 to 2 minutes after the call. Microsoft publishes no SLA.
TRANSCRIPT_DELAY = timedelta(minutes=2)

_WIRE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_CHAT_PAGE_SIZE = 50
_CHAT_SLACK = timedelta(days=1)
# Graph takes no `ge` here, and the wire format drops sub-seconds: step back one second.
_WIRE_SECOND = timedelta(seconds=1)

_NOT_FOUND = 404

_MessagesQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters
_OrganizationQuery = OrganizationRequestBuilder.OrganizationRequestBuilderGetQueryParameters

TranscriptStatus = Literal["available", "none_found"]
UnmatchedReason = Literal["other_organization", "not_ready", "not_transcribed", "unknown"]

_DESCRIPTION = """\
Lists transcripts of Teams calls (1:1 and group calls, not meetings) that the signed-in user was \
on, newest first, inside a creation window that defaults to the last 7 days. Pass a row's `uri` \
to teams_read_call_transcript to get the words.

Notes:
- A transcript is readable only when someone in the signed-in user's organization started the \
transcription (a 1:1 call) or started the call (a group call). Otherwise Teams can show the user \
the transcript and this tool does not list it.
- Transcripts appear 1 to 2 minutes after the call.
- Pass the `chat_id` of the call's chat from teams_list_chats to learn why a call in that chat \
has no transcript here, in `unmatched_calls`. On a group chat that can name calls that ended \
without a transcription.\
"""

_RUNS_BACKWARDS = (
    "teams_list_call_transcripts read nothing, because the window ends before it starts. "
    + "`created_before` must not fall before `created_after`, and `created_after` must not be in "
    + "the future when `created_before` is left out. Put the earlier bound in `created_after` and "
    + "the later bound in `created_before`. If you call this tool again with the same arguments, "
    + "the call will fail the same way."
)


class CallTranscriptSummary(BaseModel):
    uri: str = Field(
        description=(
            "Handle for this transcript. Pass it to teams_read_call_transcript to get the words."
        )
    )
    call_id: str = Field(
        description=("Microsoft's id of the call, the same id `unmatched_calls` uses.")
    )
    transcript_id: str = Field(
        description="Transcript Graph id. Use `uri` to identify a transcript, not this alone."
    )
    started_at: datetime | None = Field(
        description="Transcription start, or null if Microsoft did not report one."
    )
    ended_at: datetime | None = Field(
        description="Transcription end, or null on the same terms as `started_at`."
    )
    organizer_id: str | None = Field(
        description=(
            "Microsoft 365 user id of Microsoft's organizer of this transcript, or null. In a 1:1 "
            + "call it is who started transcription. In a group call it is who started the call."
        )
    )
    content_correlation_id: str | None = Field(
        description=(
            "Microsoft's id that links this transcript to the recording of the same call, or "
            + "null if Microsoft assigned none."
        )
    )

    @classmethod
    def from_transcript(cls, transcript: CallTranscript) -> Self:
        assert transcript.id is not None, "Graph returned a call transcript with no id"
        assert transcript.call_id is not None, "Graph returned a call transcript with no callId"
        return cls(
            uri=CallTranscriptHandle(transcript.call_id, transcript.id).uri,
            call_id=transcript.call_id,
            transcript_id=transcript.id,
            started_at=transcript.created_date_time,
            ended_at=transcript.end_date_time,
            organizer_id=user_id_of(transcript.meeting_organizer),
            content_correlation_id=transcript.content_correlation_id,
        )


class UnmatchedCall(BaseModel):
    call_id: str = Field(description="Microsoft's id of the call.")
    occurred_at: datetime | None = Field(
        description="When the chat recorded the call event, or null if Microsoft gave no time."
    )
    organizer_id: str | None = Field(
        description=(
            "Microsoft 365 user id of Microsoft's organizer of the transcript, or of who started "
            + "the call when no transcript event exists. Null if Microsoft named nobody."
        )
    )
    reason: UnmatchedReason = Field(
        description=(
            "Why Microsoft lists no transcript of this call for this user:\n"
            + "- `other_organization`: someone outside this user's organization owns the "
            + "transcript, so Microsoft 365 will not return it. A retry is unlikely to change "
            + "this.\n"
            + "- `not_ready`: the call or its transcript is under about 2 minutes old. Wait, then "
            + "call again.\n"
            + "- `not_transcribed`: the call ended and left no transcript event. In testing, that "
            + "meant nobody started a transcription.\n"
            + "- `unknown`: nothing tells why, for example a call that may still be running."
        )
    )


class CallTranscripts(BaseModel):
    status: TranscriptStatus = Field(
        description=(
            "What this tool found, and what to do next:\n"
            + "- `available`: this tool lists the transcripts, newest first. Pass a `uri` to "
            + "teams_read_call_transcript.\n"
            + "- `none_found`: no readable call transcript in this window. The call was not "
            + "transcribed, someone outside your organization started the transcription, or it "
            + "ended under about 2 minutes ago. Pass `chat_id` to check one conversation, or "
            + "widen the window."
        )
    )
    transcripts: list[CallTranscriptSummary] = Field(
        description=(
            f"The transcripts, newest first. This tool reads up to {MAX_ARTIFACT_SCAN} and sorts "
            + "them before `limit` cuts the list. Empty when `status` is `none_found`."
        )
    )
    unmatched_calls: list[UnmatchedCall] | None = Field(
        description=(
            "Calls in the `chat_id` chat inside the window for which Microsoft lists no "
            + "transcript, newest first. A listed transcript cut by `limit` is in neither list. "
            + "Null when no `chat_id` was passed."
        )
    )
    scan_incomplete: bool = Field(
        description=(
            "True when a read stopped at its cap with more on offer, so older transcripts or "
            + "call events can remain. Narrow the window to read the rest."
        )
    )


async def teams_list_call_transcripts(
    client: GraphServiceClient,
    *,
    created_after: date | datetime | None = None,
    created_before: date | datetime | None = None,
    chat_id: str | None = None,
    limit: int,
) -> CallTranscripts:
    assert limit >= 1, f"limit must be at least 1, got {limit}"
    closes = datetime.now(UTC) if created_before is None else closes_at(created_before)
    opens = closes - DEFAULT_WINDOW if created_after is None else opens_at(created_after)
    if opens > closes:
        raise ToolError(_RUNS_BACKWARDS)

    def in_window(transcript: CallTranscript) -> bool:
        created = transcript.created_date_time
        return created is None or opens <= as_utc(created) <= closes

    with graph_errors(TOOL_NAME):
        user = await signed_in_user(client)
        assert user.id is not None, "signed_in_user returns a user with an id"
        listed, listing_capped = await _listing(client, user.id, opens, closes)
        found = [transcript for transcript in listed if in_window(transcript)]
        unmatched: list[UnmatchedCall] | None = None
        chat_capped = False
        if chat_id is not None:
            events, chat_capped = await _call_events(client, chat_id, opens, closes)
            transcribed = any(
                isinstance(event.event_detail, CallTranscriptEventMessageDetail) for event in events
            )
            tenant = await _home_tenant(client) if transcribed else None
            listed_calls = {t.call_id for t in found if t.call_id is not None}
            unmatched = _unmatched(events, listed_calls, tenant, now=datetime.now(UTC))

    return CallTranscripts(
        status="available" if found else "none_found",
        transcripts=[CallTranscriptSummary.from_transcript(t) for t in found[:limit]],
        unmatched_calls=unmatched,
        scan_incomplete=listing_capped or chat_capped,
    )


async def _listing(
    client: GraphServiceClient, user_id: str, opens: datetime, closes: datetime
) -> tuple[list[CallTranscript], bool]:
    """Every transcript Graph lists for the window, newest first, and whether the scan cap hit."""
    adhoc_calls = client.me.adhoc_calls
    builder = adhoc_calls.get_all_transcriptsuser_id_user_id_with_start_date_time_with_end_date_time
    base_url = builder.request_adapter.base_url  # pyright: ignore[reportUnknownMemberType]
    function = (
        f"getAllTranscripts(userId='{odata_literal(user_id)}',"
        + f"startDateTime={opens.astimezone(UTC):{_WIRE_FORMAT}},"
        + f"endDateTime={closes.astimezone(UTC):{_WIRE_FORMAT}})"
    )
    with graph_step(STEP_TRANSCRIPTS):
        try:
            first_page = await builder.with_url(f"{base_url}/me/adhocCalls/{function}").get()
        except ODataError as refusal:
            if not _has_no_transcripts(refusal):
                raise
            return [], False
        assert first_page is not None, "Graph answered a call transcript listing with nothing"
        collected = await newest_of(first_page, client, limit=MAX_ARTIFACT_SCAN)
    return collected.items, collected.capped


def _has_no_transcripts(refusal: ODataError) -> bool:
    """Graph's answer for a user with no call transcripts, unlike a 404 for a closed route.
    It matches Graph's literal text, so a rewording would turn an empty listing into an error."""
    body = refusal.error
    return (
        refusal.response_status_code == _NOT_FOUND
        and body is not None
        and body.code == "NotFound"
        and body.message == "UnknownError"
    )


async def _home_tenant(client: GraphServiceClient) -> str | None:
    configuration = RequestConfiguration[_OrganizationQuery](
        query_parameters=_OrganizationQuery(select=["id"])
    )
    with graph_step(STEP_TENANT):
        found = await client.organization.get(request_configuration=configuration)
    organizations = [] if found is None else found.value or []
    tenant = organizations[0].id if organizations else None
    return None if tenant is None else tenant.casefold()


async def _call_events(
    client: GraphServiceClient, chat_id: str, opens: datetime, closes: datetime
) -> tuple[list[ChatMessage], bool]:
    """The chat's call events created inside the window. Filtered on `lastModifiedDateTime` because
    `createdDateTime` takes no `gt`; a message edited after its creation is dropped or missed."""
    configuration = RequestConfiguration[_MessagesQuery](
        query_parameters=_MessagesQuery(
            top=_CHAT_PAGE_SIZE,
            orderby=["lastModifiedDateTime desc"],
            # Ending transcription modifies the event: a call running past `closes` needs slack.
            filter=(
                f"lastModifiedDateTime gt {(opens - _WIRE_SECOND).astimezone(UTC):{_WIRE_FORMAT}} "
                + "and "
                + f"lastModifiedDateTime lt {(closes + _CHAT_SLACK).astimezone(UTC):{_WIRE_FORMAT}}"
            ),
        ),
        headers=unknown_enum_headers(),
    )

    def is_call_event(message: ChatMessage) -> bool:
        created = message.created_date_time
        in_window = created is not None and opens <= as_utc(created) <= closes
        return in_window and _call_id(message) is not None

    with graph_step(STEP_CHAT):
        first_page = await client.chats.by_chat_id(chat_id).messages.get(
            request_configuration=configuration
        )
        assert first_page is not None, "Graph answered a chat message listing with no collection"
        collected = await collect_pages(
            first_page,
            client,
            limit=MAX_SCANNED_ITEMS,
            matches=is_call_event,
            headers=unknown_enum_headers(),
        )
    return collected.items, collected.capped


def _unmatched(
    events: list[ChatMessage],
    listed_calls: set[str],
    tenant: str | None,
    *,
    now: datetime,
) -> list[UnmatchedCall]:
    transcribed: dict[str, UnmatchedCall] = {}
    ended: dict[str, UnmatchedCall] = {}
    started: dict[str, UnmatchedCall] = {}
    for message in events:
        detail = message.event_detail
        call_id = _call_id(message)
        if call_id is None or call_id in listed_calls:
            continue
        if isinstance(detail, CallTranscriptEventMessageDetail):
            organizer = detail.meeting_organizer
            reason = _transcript_reason(organizer, message.created_date_time, tenant, now=now)
            seen = transcribed
        # As seen in one test tenant, another organization's transcription still leaves a
        # callTranscript event, and only group chats carry end events.
        elif isinstance(detail, CallEndedEventMessageDetail):
            organizer, seen = detail.initiator, ended
            reason = (
                "not_ready" if _is_recent(message.created_date_time, now) else "not_transcribed"
            )
        # Started and never ended in the window: it may still be running.
        elif isinstance(detail, CallStartedEventMessageDetail):
            organizer, reason, seen = detail.initiator, "unknown", started
        else:
            continue
        _ = seen.setdefault(
            call_id,
            UnmatchedCall(
                call_id=call_id,
                occurred_at=message.created_date_time,
                organizer_id=user_id_of(organizer),
                reason=reason,
            ),
        )
    calls = started | ended | transcribed
    return sorted(calls.values(), key=_occurred, reverse=True)


def _transcript_reason(
    organizer: IdentitySet | None, created: datetime | None, tenant: str | None, *, now: datetime
) -> UnmatchedReason:
    organizer_tenant = _tenant_id(organizer)
    if None not in (organizer_tenant, tenant) and organizer_tenant != tenant:
        return "other_organization"
    return "not_ready" if _is_recent(created, now) else "unknown"


def _is_recent(created: datetime | None, now: datetime) -> bool:
    return created is not None and now - as_utc(created) < TRANSCRIPT_DELAY


def _call_id(message: ChatMessage) -> str | None:
    detail = message.event_detail
    if isinstance(
        detail,
        CallTranscriptEventMessageDetail
        | CallStartedEventMessageDetail
        | CallEndedEventMessageDetail,
    ):
        return detail.call_id
    return None


def _tenant_id(identities: IdentitySet | None) -> str | None:
    """`teamworkUserIdentity` has no `tenantId` field in the SDK, so it lands in `additional_data`,
    where the JSON parser turns a GUID string into a `UUID`."""
    user = None if identities is None else identities.user
    value = None if user is None else user.additional_data.get("tenantId")
    return str(value).casefold() if isinstance(value, str | UUID) else None


def _occurred(call: UnmatchedCall) -> datetime:
    moment = call.occurred_at
    return as_utc(moment) if moment is not None else datetime.min.replace(tzinfo=UTC)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Call Transcripts",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def list_call_transcripts(
        created_after: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only transcripts created at or after this point. A date, `2026-03-02`, opens "
                    + "at the start of that UTC day. A moment, `2026-03-02T09:00:00Z`, opens at "
                    + "that second. A moment with no zone is read as UTC. Defaults to 7 days "
                    + "before `created_before`."
                )
            ),
        ] = None,
        created_before: Annotated[
            date | datetime | None,
            Field(
                description=(
                    "Only transcripts created at or before this point, in the same forms as "
                    + "`created_after`. A date covers that whole UTC day. Defaults to now."
                )
            ),
        ] = None,
        chat_id: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The `chat_id` from teams_list_chats of the chat the call happened in, for "
                    + "example `19:...@thread.v2`. With it, `unmatched_calls` lists that chat's "
                    + "calls in the window that have no transcript here, and why."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    f"How many transcripts to return. This tool reads up to {MAX_ARTIFACT_SCAN} "
                    + "and sorts them before this cuts the list."
                ),
            ),
        ] = 20,
        client: GraphServiceClient = graph,
    ) -> CallTranscripts:
        return await teams_list_call_transcripts(
            client,
            created_after=created_after,
            created_before=created_before,
            chat_id=chat_id,
            limit=limit,
        )
