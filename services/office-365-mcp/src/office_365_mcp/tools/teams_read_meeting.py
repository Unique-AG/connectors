from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.attendance_interval import AttendanceInterval
from msgraph.generated.models.attendance_record import AttendanceRecord
from msgraph.generated.models.meeting_attendance_report import MeetingAttendanceReport
from msgraph.generated.models.meeting_participant_info import MeetingParticipantInfo
from msgraph.generated.models.online_meeting import OnlineMeeting
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors, graph_step
from office_365_mcp.shared.handles import MeetingHandle, meeting_handle
from office_365_mcp.shared.meetings import MEETING_PERMISSION, resolve_meeting, settled
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import as_utc

TOOL_NAME = "teams_read_meeting"

STEP_REPORTS = "attendance_reports"
STEP_RECORDS = "attendance_records"

GRAPH_PERMISSIONS: tuple[str, ...] = (MEETING_PERMISSION, "OnlineMeetingArtifact.Read.All")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "meeting_uri": "teams:///meetings/https%3A%2F%2Fteams.microsoft.invalid%2Fl%2Fmeetup-join"
    + "%2F19%253ameeting_TjAwMDAwMDAwMDAwMA%2540thread.v2%2F0"
}

MAX_REPORTS = 50

AttendanceStatus = Literal["available", "not_ready", "no_report", "meeting_not_found"]

_DESCRIPTION = """\
Reads one Teams meeting of the signed-in user and its attendance, from the `meeting_uri` that \
teams_list_chats reports. It returns the meeting details, the attendance reports newest first, and \
who attended the newest session and for how long. teams_list_meeting_transcripts is the sibling \
tool for the words, and teams_list_meeting_recordings is the sibling tool for the recordings.

Notes:
- Only the meeting organizer can read attendance reports.
- Read `status` before you decide: `not_ready` means wait, not "nobody attended".
- This tool reads one page of records, of the newest report only. Calling it again returns the \
same records.\
"""

_NOT_A_MEETING_HANDLE = (
    "teams_read_meeting takes teams:///meetings/{join_web_url} from teams_list_chats, not this. "
    + "Call teams_list_chats and use its `meeting_uri`. A `teams:///transcripts/...` handle is "
    + "teams_read_transcript's. Retrying this value will fail identically."
)


class MeetingInvitee(BaseModel):
    user_id: str | None = Field(
        description=(
            "This invitee's Microsoft Entra object id, or null if Microsoft named no user. It is "
            + "the same id as `user_id` in get_me."
        )
    )
    upn: str | None = Field(
        description=(
            "This invitee's user principal name, which is the sign-in name, or null if Microsoft "
            + "sent none. It can differ from the email address."
        )
    )

    @classmethod
    def from_participant(cls, participant: MeetingParticipantInfo) -> Self:
        return cls(user_id=_user_id(participant), upn=participant.upn)


class MeetingDetails(BaseModel):
    meeting_uri: str = Field(
        description=(
            "The meeting handle that this tool read. Pass it verbatim to "
            + "teams_list_meeting_transcripts or teams_list_meeting_recordings for the other "
            + "artifacts of this meeting."
        )
    )
    join_web_url: str | None = Field(
        description=(
            "The join URL that Microsoft holds for this meeting, or null if Microsoft sent none. "
            + "A person opens this URL to join the meeting in Teams."
        )
    )
    subject: str | None = Field(
        description=(
            "Meeting subject as Microsoft holds it, or null if none is set. You can compare it "
            + "to make sure that this is the right meeting. It can differ from the chat topic."
        )
    )
    started_at: datetime | None = Field(
        description=(
            "Meeting start, or null if Microsoft reported none. For a recurring series, "
            + "Microsoft's single value for the whole series, not the occurrence asked about."
        )
    )
    ended_at: datetime | None = Field(
        description=(
            "Meeting end, or null on the same terms as `started_at`. Each entry in `reports` has "
            + "the start and end of its own session."
        )
    )
    organizer_user_id: str | None = Field(
        description=(
            "The organizer's Microsoft Entra object id, or null if Microsoft named no organizer. "
            + "Compare it with `user_id` in get_me to learn if the signed-in user is the organizer."
        )
    )
    attendees: list[MeetingInvitee] = Field(
        description=(
            "The invitees that Microsoft lists on the meeting. This list can be empty even when "
            + "people attended. Read `newest_report_attendance` to learn who joined."
        )
    )

    @classmethod
    def from_meeting(cls, handle: MeetingHandle, meeting: OnlineMeeting) -> Self:
        participants = meeting.participants
        organizer = participants.organizer if participants is not None else None
        invitees = (participants.attendees if participants is not None else None) or []
        return cls(
            meeting_uri=handle.uri,
            join_web_url=meeting.join_web_url,
            subject=meeting.subject,
            started_at=meeting.start_date_time,
            ended_at=meeting.end_date_time,
            organizer_user_id=_user_id(organizer) if organizer is not None else None,
            attendees=[MeetingInvitee.from_participant(invitee) for invitee in invitees],
        )


class AttendanceReportSummary(BaseModel):
    report_id: str = Field(
        description=(
            "The attendance report's Graph id. This id is opaque, and no tool here accepts it as "
            + "input."
        )
    )
    started_at: datetime | None = Field(
        description=(
            "When the session of this report started, or null if Microsoft reported none. A "
            + "recurring meeting has one report for each session."
        )
    )
    ended_at: datetime | None = Field(
        description=(
            "When the session of this report ended, or null on the same terms as `started_at`."
        )
    )
    total_participant_count: int | None = Field(
        description=(
            "The number of participants that Microsoft counted in this session, or null if "
            + "Microsoft sent no count."
        )
    )

    @classmethod
    def from_report(cls, report: MeetingAttendanceReport) -> Self:
        assert report.id is not None, "Graph returned an attendance report with no id"
        return cls(
            report_id=report.id,
            started_at=report.meeting_start_date_time,
            ended_at=report.meeting_end_date_time,
            total_participant_count=report.total_participant_count,
        )


class AttendanceSpan(BaseModel):
    joined_at: datetime | None = Field(
        description=(
            "When this person joined the session for this period, or null if Microsoft did not "
            + "report it."
        )
    )
    left_at: datetime | None = Field(
        description=(
            "When this person left the session at the end of this period, or null if Microsoft "
            + "did not report it."
        )
    )

    @classmethod
    def from_interval(cls, interval: AttendanceInterval) -> Self:
        return cls(joined_at=interval.join_date_time, left_at=interval.leave_date_time)


class AttendeeRecord(BaseModel):
    display_name: str | None = Field(
        description=(
            "This person's display name as Microsoft records it, or null if none is set. Two "
            + "people can share one name, so compare `email` too."
        )
    )
    email: str | None = Field(
        description=(
            "The email address that Microsoft records for this person in this report, or null if "
            + "Microsoft records none."
        )
    )
    role: str | None = Field(
        description=(
            "This person's role in the session, as Microsoft records it: `Organizer`, "
            + "`Presenter`, `Attendee`, or the text `None`. Null if Microsoft sent no role."
        )
    )
    total_attendance_seconds: int | None = Field(
        description=(
            "Microsoft's total of the time this person attended the session, in seconds, or null "
            + "if Microsoft sent no total."
        )
    )
    intervals: list[AttendanceSpan] = Field(
        description=(
            "Each period from one join to the next leave, in the order that Microsoft sent them. "
            + "A person who left and joined again has more than one period."
        )
    )

    @classmethod
    def from_record(cls, record: AttendanceRecord) -> Self:
        identity = record.identity
        return cls(
            display_name=identity.display_name if identity is not None else None,
            email=record.email_address,
            role=record.role,
            total_attendance_seconds=record.total_attendance_in_seconds,
            intervals=[
                AttendanceSpan.from_interval(interval)
                for interval in record.attendance_intervals or []
            ],
        )


class MeetingAttendance(BaseModel):
    status: AttendanceStatus = Field(
        description=(
            "What this tool found:\n"
            + "- `available`: at least one report exists.\n"
            + "- `not_ready`: no report exists yet. Wait, then call again.\n"
            + "- `no_report`: the meeting is over, and no report exists. A retry does not change "
            + "this.\n"
            + "- `meeting_not_found`: no meeting that this user can see matched the join URL. "
            + "Do not retry or rebuild the handle."
        )
    )
    meeting: MeetingDetails | None = Field(
        description=(
            "The meeting that the handle resolved to, or null if `status` is "
            + "`meeting_not_found`. These details come from the meeting, not from a report."
        )
    )
    reports: list[AttendanceReportSummary] = Field(
        description=(
            "The meeting's attendance reports, newest first, one for each session that ended. "
            + f"Microsoft returns at most the {MAX_REPORTS} most recent reports, and it keeps a "
            + "report for one year from the meeting date. This list is empty for every status "
            + "other than `available`."
        )
    )
    newest_report_attendance: list[AttendeeRecord] = Field(
        description=(
            "The attendance records of the first entry in `reports`, in the order that Microsoft "
            + "sent them. They include guests and users from other organizations. This tool reads "
            + "no records of an older report."
        )
    )
    more_records: bool = Field(
        description=(
            "True when Microsoft reported more records of the newest report after this page. "
            + "`newest_report_attendance` is then incomplete. False means that the list is "
            + "complete."
        )
    )


async def teams_read_meeting(
    client: GraphServiceClient, *, handle: MeetingHandle
) -> MeetingAttendance:
    with graph_errors(TOOL_NAME):
        meeting = await resolve_meeting(client, handle)
        if meeting is None or meeting.id is None:
            return MeetingAttendance(
                status="meeting_not_found",
                meeting=None,
                reports=[],
                newest_report_attendance=[],
                more_records=False,
            )
        reports_of = client.me.online_meetings.by_online_meeting_id(meeting.id).attendance_reports
        with graph_step(STEP_REPORTS):
            listed = await reports_of.get()
            assert listed is not None, "Graph answered an attendance report listing with no value"
            collected = await collect_pages(listed, client, limit=MAX_REPORTS)
        reports = sorted(
            (AttendanceReportSummary.from_report(report) for report in collected.items),
            key=_began_at,
            reverse=True,
        )
        details = MeetingDetails.from_meeting(handle, meeting)
        if not reports:
            return MeetingAttendance(
                status="no_report" if settled(meeting) else "not_ready",
                meeting=details,
                reports=[],
                newest_report_attendance=[],
                more_records=False,
            )
        with graph_step(STEP_RECORDS):
            records = await reports_of.by_meeting_attendance_report_id(
                reports[0].report_id
            ).attendance_records.get()
            assert records is not None, "Graph answered an attendance record listing with no value"

    return MeetingAttendance(
        status="available",
        meeting=details,
        reports=reports,
        newest_report_attendance=[
            AttendeeRecord.from_record(record) for record in records.value or []
        ],
        more_records=bool(records.odata_next_link),
    )


def _user_id(participant: MeetingParticipantInfo) -> str | None:
    identity = participant.identity
    user = identity.user if identity is not None else None
    return user.id if user is not None else None


def _began_at(report: AttendanceReportSummary) -> datetime:
    began = report.started_at
    return as_utc(began) if began is not None else datetime.min.replace(tzinfo=UTC)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Read a Meeting and Its Attendance",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def read_meeting(
        meeting_uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The meeting handle from teams_list_chats: `teams:///meetings/{join_web_url}`. "
                    + "Copy it verbatim. A `teams:///transcripts/...` handle is not valid here."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> MeetingAttendance:
        handle = meeting_handle(meeting_uri)
        if handle is None:
            raise ToolError(_NOT_A_MEETING_HANDLE)
        return await teams_read_meeting(client, handle=handle)
