from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared import handles
from office_365_mcp.shared.seam import READ_ONLY
from office_365_mcp.tools import teams_read_meeting as reader

from .conftest import (
    GRAPH_V1,
    JOIN_WEB_URL,
    MEETING_ID,
    OTHER_USER_ID,
    SIGNED_IN_USER_ID,
    meeting_payload,
)

_MEETINGS = "/me/onlineMeetings"
_REPORTS = f"/me/onlineMeetings/{MEETING_ID}/attendanceReports"
_NEWEST_REPORT_ID = "c9b6db1c-d5eb-427d-a5c0-20088d9b22d7"
_OLDER_REPORT_ID = "2c2c2454-7613-4d6e-9c7c-4cf7a6cdce89"
_NEWEST_RECORDS = f"{_REPORTS}/{_NEWEST_REPORT_ID}/attendanceRecords"
_OLDER_RECORDS = f"{_REPORTS}/{_OLDER_REPORT_ID}/attendanceRecords"
_SKIPTOKEN = "synthetic"

_ORGANIZER_UPN = "ada@corp.example.invalid"
_ATTENDEE_UPN = "grace@corp.example.invalid"

_PARTICIPANTS: dict[str, object] = {
    "organizer": {
        "upn": _ORGANIZER_UPN,
        "role": "presenter",
        "identity": {
            "user": {
                "id": SIGNED_IN_USER_ID,
                "displayName": None,
                "tenantId": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
                "identityProvider": "AAD",
            }
        },
    },
    "attendees": [
        {
            "upn": _ATTENDEE_UPN,
            "role": "attendee",
            "identity": {"user": {"id": OTHER_USER_ID, "displayName": "Grace Hopper"}},
        }
    ],
}

_REFUSED = {"error": {"code": "Forbidden", "message": "denied"}}
_MISSING = {"error": {"code": "NotFound", "message": "no"}}


def _handle() -> handles.MeetingHandle:
    handle = handles.meeting_handle(handles.meeting_uri_for(JOIN_WEB_URL) or "")
    assert handle is not None
    return handle


def _resolved(
    graph: respx.MockRouter,
    *,
    end: str | None = "2026-02-10T15:00:00Z",
    participants: Mapping[str, object] | None = None,
) -> respx.Route:
    meeting = {
        **meeting_payload(end=end),
        "participants": dict(participants) if participants is not None else _PARTICIPANTS,
    }
    return graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": [meeting]}))


def _report(report_id: str, *, started: str, ended: str, count: int = 2) -> dict[str, object]:
    return {
        "id": report_id,
        "totalParticipantCount": count,
        "meetingStartDateTime": started,
        "meetingEndDateTime": ended,
        "attendanceRecords": [],
    }


_NEWEST = _report(
    _NEWEST_REPORT_ID, started="2026-02-10T14:00:23.945Z", ended="2026-02-10T14:43:49.77Z"
)
_OLDER = _report(
    _OLDER_REPORT_ID, started="2026-02-03T14:00:31.658Z", ended="2026-02-03T14:18:57.563Z", count=1
)


def _record(
    *,
    email: str | None = "frederick.cormier@contoso.invalid",
    display_name: str | None = "Frederick Cormier",
    role: str | None = "Organizer",
) -> dict[str, object]:
    return {
        "emailAddress": email,
        "totalAttendanceInSeconds": 1152,
        "role": role,
        "identity": {
            "id": "dc17674c-81d9-4adb-bfb2-8f6a442e4623",
            "displayName": display_name,
            "tenantId": None,
        },
        "attendanceIntervals": [
            {
                "joinDateTime": "2026-02-10T14:00:52.2782182Z",
                "leaveDateTime": "2026-02-10T14:07:47.7218491Z",
                "durationInSeconds": 415,
            },
            {
                "joinDateTime": "2026-02-10T14:09:23.9834702Z",
                "leaveDateTime": "2026-02-10T14:16:31.1381195Z",
                "durationInSeconds": 427,
            },
        ],
    }


def _page(*rows: Mapping[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": [dict(row) for row in rows]}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _reports(graph: respx.MockRouter, *reports: Mapping[str, object]) -> respx.Route:
    return graph.get(_REPORTS).mock(return_value=_page(*reports))


def _records(
    graph: respx.MockRouter, path: str = _NEWEST_RECORDS, *, next_link: str | None = None
) -> respx.Route:
    return graph.get(path).mock(return_value=_page(_record(), next_link=next_link))


def _published(*path: str) -> Mapping[str, object]:
    found: Mapping[str, object] = reader.MeetingAttendance.model_json_schema()
    for key in path:
        step = found.get(key)
        assert isinstance(step, dict), f"expected an object at {key!r}, got {step!r}"
        found = cast("Mapping[str, object]", step)
    return found


async def _registered(transport: httpx.AsyncClient) -> FunctionTool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    reader.register(mcp, transport)
    tool = await mcp.get_tool(reader.TOOL_NAME)
    assert isinstance(tool, FunctionTool), "register left the tool off the server"
    return tool


def _property(parameters: Mapping[str, object], name: str) -> Mapping[str, object]:
    return cast(
        "Mapping[str, object]", cast("Mapping[str, object]", parameters["properties"])[name]
    )


class TestTheRequestsItSends:
    async def test_the_join_url_reaches_the_resolve_filter_encoded_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _resolved(graph)
        _ = _reports(graph)

        _ = await reader.teams_read_meeting(client, handle=_handle())

        url = route.calls.last.request.url
        assert url.params["$filter"] == f"JoinWebUrl eq '{JOIN_WEB_URL}'"
        raw = url.query.decode()
        assert "%253ameeting" in raw
        assert "%26anon%3Dtrue" in raw
        assert "%2525" not in raw

    async def test_it_reads_the_reports_then_the_records_of_the_newest_report_only(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolved(graph)
        reports = _reports(graph, _OLDER, _NEWEST)
        newest = _records(graph)
        older = _records(graph, _OLDER_RECORDS)

        _ = await reader.teams_read_meeting(client, handle=_handle())

        assert len(graph.calls) == 3, "resolve, list the reports, list the newest records"
        assert str(reports.calls.last.request.url) == f"{GRAPH_V1}{_REPORTS}"
        assert str(newest.calls.last.request.url) == f"{GRAPH_V1}{_NEWEST_RECORDS}"
        assert newest.call_count == 1
        assert not older.called, "the records of an older report are never read"

    async def test_microsofts_cursor_on_the_records_is_read_and_never_followed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolved(graph)
        _ = _reports(graph, _NEWEST)
        second_page = graph.get(_NEWEST_RECORDS, params={"$skiptoken": _SKIPTOKEN}).mock(
            return_value=_page(_record(email="lisa.adkins@contoso.invalid"))
        )
        _ = _records(graph, next_link=f"{GRAPH_V1}{_NEWEST_RECORDS}?$skiptoken={_SKIPTOKEN}")

        found = await reader.teams_read_meeting(client, handle=_handle())

        assert not second_page.called
        assert found.more_records is True
        assert [record.email for record in found.newest_report_attendance] == [
            "frederick.cormier@contoso.invalid"
        ]

    async def test_a_records_page_with_no_cursor_says_the_list_is_complete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolved(graph)
        _ = _reports(graph, _NEWEST)
        _ = _records(graph)

        found = await reader.teams_read_meeting(client, handle=_handle())

        assert found.more_records is False

    async def test_the_newest_report_is_found_even_when_it_is_on_a_later_page(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolved(graph)
        _ = graph.get(_REPORTS).mock(
            side_effect=[
                _page(_OLDER, next_link=f"{GRAPH_V1}{_REPORTS}?$skiptoken={_SKIPTOKEN}"),
                _page(_NEWEST),
            ]
        )
        newest = _records(graph)
        older = _records(graph, _OLDER_RECORDS)

        found = await reader.teams_read_meeting(client, handle=_handle())

        assert [report.report_id for report in found.reports] == [
            _NEWEST_REPORT_ID,
            _OLDER_REPORT_ID,
        ]
        assert newest.called
        assert not older.called


class TestWhatItAnswers:
    async def test_the_meeting_details_come_from_the_resolved_meeting(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolved(graph)
        _ = _reports(graph, _NEWEST)
        _ = _records(graph)

        found = await reader.teams_read_meeting(client, handle=_handle())

        assert found.meeting is not None
        assert found.meeting.model_dump() == {
            "meeting_uri": _handle().uri,
            "join_web_url": JOIN_WEB_URL,
            "subject": "Pricing review",
            "started_at": datetime(2026, 2, 10, 14, 0, tzinfo=UTC),
            "ended_at": datetime(2026, 2, 10, 15, 0, tzinfo=UTC),
            "organizer_user_id": SIGNED_IN_USER_ID,
            "attendees": [{"user_id": OTHER_USER_ID, "upn": _ATTENDEE_UPN}],
        }

    async def test_a_meeting_with_no_participants_names_no_organizer_and_no_invitee(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolved(graph, participants={"organizer": None, "attendees": None})
        _ = _reports(graph, _NEWEST)
        _ = _records(graph)

        found = await reader.teams_read_meeting(client, handle=_handle())

        assert found.meeting is not None
        assert found.meeting.organizer_user_id is None
        assert found.meeting.attendees == []

    async def test_reports_come_back_newest_first_with_their_sessions_and_counts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolved(graph)
        _ = _reports(graph, _OLDER, _NEWEST)
        _ = _records(graph)

        found = await reader.teams_read_meeting(client, handle=_handle())

        assert found.status == "available"
        assert [report.model_dump() for report in found.reports] == [
            {
                "report_id": _NEWEST_REPORT_ID,
                "started_at": datetime(2026, 2, 10, 14, 0, 23, 945000, tzinfo=UTC),
                "ended_at": datetime(2026, 2, 10, 14, 43, 49, 770000, tzinfo=UTC),
                "total_participant_count": 2,
            },
            {
                "report_id": _OLDER_REPORT_ID,
                "started_at": datetime(2026, 2, 3, 14, 0, 31, 658000, tzinfo=UTC),
                "ended_at": datetime(2026, 2, 3, 14, 18, 57, 563000, tzinfo=UTC),
                "total_participant_count": 1,
            },
        ]

    async def test_a_record_maps_every_field_and_keeps_each_join_and_leave(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolved(graph)
        _ = _reports(graph, _NEWEST)
        _ = _records(graph)

        found = await reader.teams_read_meeting(client, handle=_handle())

        assert [record.model_dump() for record in found.newest_report_attendance] == [
            {
                "display_name": "Frederick Cormier",
                "email": "frederick.cormier@contoso.invalid",
                "role": "Organizer",
                "total_attendance_seconds": 1152,
                "intervals": [
                    {
                        "joined_at": datetime(2026, 2, 10, 14, 0, 52, 278218, tzinfo=UTC),
                        "left_at": datetime(2026, 2, 10, 14, 7, 47, 721849, tzinfo=UTC),
                    },
                    {
                        "joined_at": datetime(2026, 2, 10, 14, 9, 23, 983470, tzinfo=UTC),
                        "left_at": datetime(2026, 2, 10, 14, 16, 31, 138119, tzinfo=UTC),
                    },
                ],
            }
        ]

    async def test_a_record_with_no_identity_has_no_display_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolved(graph)
        _ = _reports(graph, _NEWEST)
        _ = graph.get(_NEWEST_RECORDS).mock(
            return_value=_page({**_record(), "identity": None, "role": None})
        )

        found = await reader.teams_read_meeting(client, handle=_handle())

        assert found.newest_report_attendance[0].display_name is None
        assert found.newest_report_attendance[0].role is None
        assert found.newest_report_attendance[0].email == "frederick.cormier@contoso.invalid"


class TestTheKindsOfAbsence:
    async def test_no_matching_meeting_is_a_status_and_costs_no_listing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_MEETINGS).mock(return_value=httpx.Response(200, json={"value": []}))
        reports = _reports(graph, _NEWEST)

        found = await reader.teams_read_meeting(client, handle=_handle())

        assert found.status == "meeting_not_found"
        assert found.meeting is None
        assert found.reports == []
        assert found.newest_report_attendance == []
        assert found.more_records is False
        assert not reports.called

    async def test_a_meeting_long_over_with_no_report_has_none(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _resolved(graph, end=(datetime.now(UTC) - timedelta(days=9)).isoformat())
        _ = _reports(graph)
        records = _records(graph)

        found = await reader.teams_read_meeting(client, handle=_handle())

        assert found.status == "no_report"
        assert found.meeting is not None, "the meeting resolved, and it has no report"
        assert found.reports == []
        assert found.newest_report_attendance == []
        assert not records.called

    @pytest.mark.parametrize(
        "ended",
        [
            datetime.now(UTC) - timedelta(minutes=5),
            datetime.now(UTC) + timedelta(hours=1),
            None,
        ],
        ids=["just-ended", "still-running", "no-end-time"],
    )
    async def test_a_meeting_that_just_ended_is_not_ready_rather_than_without_a_report(
        self, client: GraphServiceClient, graph: respx.MockRouter, ended: datetime | None
    ) -> None:
        _ = _resolved(graph, end=ended.isoformat() if ended is not None else None)
        _ = _reports(graph)

        found = await reader.teams_read_meeting(client, handle=_handle())

        assert found.status == "not_ready"

    def test_the_four_answers_reach_the_schema_as_an_enum_and_not_only_as_prose(self) -> None:
        status = _published("properties", "status")

        assert status["enum"] == ["available", "not_ready", "no_report", "meeting_not_found"]
        assert status["type"] == "string"
        assert "$ref" not in status
        described = str(status["description"])
        assert "A retry does not change this." in described
        assert "Do not retry or rebuild the handle." in described


class TestGraphFailures:
    @pytest.mark.parametrize("path", [_REPORTS, _NEWEST_RECORDS], ids=["reports", "records"])
    async def test_a_refusal_arrives_classified_for_the_seam_to_explain(
        self, client: GraphServiceClient, graph: respx.MockRouter, path: str
    ) -> None:
        _ = _resolved(graph)
        _ = _reports(graph, _NEWEST)
        _ = graph.get(path).mock(return_value=httpx.Response(403, json=_REFUSED))

        with pytest.raises(GraphForbidden):
            _ = await reader.teams_read_meeting(client, handle=_handle())

    @pytest.mark.parametrize("path", [_MEETINGS, _REPORTS], ids=["resolve", "reports"])
    async def test_a_404_is_still_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter, path: str
    ) -> None:
        _ = _resolved(graph)
        _ = graph.get(path).mock(return_value=httpx.Response(404, json=_MISSING))

        with pytest.raises(GraphNotFound):
            _ = await reader.teams_read_meeting(client, handle=_handle())


class TestHowItDeclaresItself:
    def test_the_permissions_are_the_meeting_read_then_the_artifact_read(self) -> None:
        assert reader.GRAPH_PERMISSIONS == ("OnlineMeetings.Read", "OnlineMeetingArtifact.Read.All")

    async def test_it_announces_itself_as_read_only(self, transport: httpx.AsyncClient) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is READ_ONLY["readOnlyHint"]
        assert annotations.open_world_hint is READ_ONLY["openWorldHint"]

    async def test_the_only_argument_is_a_required_meeting_uri(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)
        parameters = cast("Mapping[str, object]", tool.parameters)

        assert set(cast("Mapping[str, object]", parameters["properties"])) == {"meeting_uri"}
        assert list(cast("Sequence[str]", parameters["required"])) == ["meeting_uri"]
        meeting_uri = _property(parameters, "meeting_uri")
        assert meeting_uri["minLength"] == 1
        assert "`teams:///meetings/{join_web_url}`. Copy it verbatim." in str(
            meeting_uri["description"]
        )

    @pytest.mark.parametrize(
        "uri",
        ["teams:///transcripts/a/b", "19:meeting_x@thread.v2", "teams:///meetings/%20"],
        ids=["transcript-handle", "thread-id", "blank-join-url"],
    )
    async def test_it_refuses_what_is_not_a_meeting_handle_before_graph(
        self,
        transport: httpx.AsyncClient,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        uri: str,
    ) -> None:
        tool = await _registered(transport)

        with pytest.raises(ToolError) as refused:
            _ = cast("reader.MeetingAttendance", await tool.fn(meeting_uri=uri, client=client))

        message = str(refused.value)
        assert "teams_read_meeting takes teams:///meetings/{join_web_url}" in message
        assert "Call teams_list_chats and use its `meeting_uri`." in message
        assert "Retrying this value will fail identically." in message
        assert not graph.calls

    async def test_the_description_names_its_siblings_and_the_organizer_rule(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert "from the `meeting_uri` that teams_list_chats reports." in description
        assert "teams_list_meeting_transcripts is the sibling tool for the words" in description
        assert "teams_list_meeting_recordings is the sibling tool for the recordings." in (
            description
        )
        assert "\n\nNotes:\n- " in description
        assert "- Only the meeting organizer can read attendance reports." in description
        assert "`not_ready` means wait" in description
        assert "Calling it again returns the same records." in description
        assert 45 <= len(description.split()) <= 210

    def test_the_answer_bounds_what_it_promises_to_what_microsoft_returns(self) -> None:
        reports = str(reader.MeetingAttendance.model_fields["reports"].description)
        records = str(reader.MeetingAttendance.model_fields["newest_report_attendance"].description)

        assert f"at most the {reader.MAX_REPORTS} most recent reports" in reports
        assert "keeps a report for one year" in reports
        assert "This tool reads no records of an older report." in records
