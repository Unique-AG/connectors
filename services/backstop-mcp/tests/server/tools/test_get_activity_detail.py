"""`get_activity_detail`: entity-activity-details + conditional attendees fan-out.

Each test targets one behaviour from the task: a meeting/call `activity_id` returns a
fully-populated response (and hits attendees); a note/document-shaped `activity_id` never
touches the attendees endpoint and returns empty/`None` meeting specifics; the full body is
untruncated even for HTML long enough that the timeline's gist budget would have truncated it;
a 404 propagates as `BackstopApiError`; and missing/unexpected wire fields degrade to
`None`/empty rather than crashing (the defensive `AliasChoices`/`extra="ignore"` parsing —
none of this tool's upstream field names were byte-verified, see
`fetch_activity_detail.py`'s module docstring).
"""

from collections.abc import Callable
from datetime import datetime

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopApiError
from backstop_mcp.features.activity_history import ActivityDetailResponse
from backstop_mcp.server.tools.get_activity_detail import get_activity_detail
from tests.features.party_resolver.helpers import BASE_URL, collection, ctx_never_elicit
from tests.helpers import resource
from tests.server.tools.helpers import tool_model

type ConnectUser = Callable[..., object]


def _detail_document(
    resource_id: str, resource_type: str = "entity-activity-details", **attributes: object
) -> dict[str, object]:
    return {"data": {"type": resource_type, "id": resource_id, "attributes": attributes}}


# Every detail endpoint is keyed by the BARE `resource_id` — the part after the last underscore
# of an `activity_id` handle — never the composite handle itself. See `ResourceIdentifierDto`.
def _details_route(resource_id: str) -> respx.Route:
    return respx.get(f"{BASE_URL}/entity-activity-details/{resource_id}")


def _specifics_route(resource_id: str) -> respx.Route:
    """`/meeting-or-calls/{id}` — where timings and location live, not on the detail record."""
    return respx.get(f"{BASE_URL}/meeting-or-calls/{resource_id}")


def _attendees_route(resource_id: str) -> respx.Route:
    return respx.get(f"{BASE_URL}/meeting-or-calls/{resource_id}/attendees")


def _specifics_document(resource_id: str, **attributes: object) -> dict[str, object]:
    return {"data": {"type": "meeting-or-calls", "id": resource_id, "attributes": attributes}}


class TestMeetingOrCall:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_full_detail_with_attendees(self, connect_user: ConnectUser) -> None:
        await connect_user("user-ad-1", "org-anna")  # pyright: ignore[reportGeneralTypeIssues]

        activity_id = "meeting-or-calls_76280387"
        _details_route("76280387").mock(
            return_value=httpx.Response(
                200,
                json=_detail_document(
                    "76280387",
                    type="meeting",
                    title="Quarterly check-in",
                    description="<table><tr><td>Agenda</td><td>Notes</td></tr></table>",
                ),
            )
        )
        specifics = _specifics_route("76280387").mock(
            return_value=httpx.Response(
                200,
                json=_specifics_document(
                    "76280387",
                    startTimestamp="2026-01-05T15:00:00Z",
                    stopTimestamp="2026-01-05T15:30:00Z",
                    location="HQ Conference Room",
                    timeZone="America/New_York",
                ),
            )
        )
        _attendees_route("76280387").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("att1", "people", name="Jane Doe"),
                    resource("att2", "people", firstName="John", lastName="Smith"),
                    resource("att3", "people"),
                ),
            )
        )

        result = tool_model(
            await get_activity_detail(ctx_never_elicit(), activity_id=activity_id),
            ActivityDetailResponse,
        )

        assert result.activity_id == activity_id
        assert result.type == "meeting"
        assert result.title == "Quarterly check-in"
        assert "Agenda" in result.body
        assert "Notes" in result.body
        assert "<table>" not in result.body
        assert result.start == datetime.fromisoformat("2026-01-05T15:00:00+00:00")
        assert result.stop == datetime.fromisoformat("2026-01-05T15:30:00+00:00")
        assert result.location == "HQ Conference Room"
        assert result.time_zone == "America/New_York"
        assert [attendee.name for attendee in result.attendees] == [
            "Jane Doe",
            "John Smith",
            None,
        ]
        # Only the four fields that actually live on this endpoint are requested.
        assert specifics.calls.last.request.url.params["fields"] == (
            "startTimestamp,stopTimestamp,location,timeZone"
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_full_body_is_untruncated_even_for_long_html(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ad-2", "org-bea")  # pyright: ignore[reportGeneralTypeIssues]

        activity_id = "meeting-or-calls_99999"
        # Comfortably longer than the activity-history gist budget (a few hundred chars) used
        # elsewhere in this feature, so truncation here would be obviously wrong.
        long_paragraph = " ".join(f"word{i}" for i in range(5_000))
        html = f"<p>{long_paragraph}</p>"
        _details_route("99999").mock(
            return_value=httpx.Response(200, json=_detail_document("99999", description=html))
        )
        _specifics_route("99999").mock(
            return_value=httpx.Response(200, json=_specifics_document("99999"))
        )
        _attendees_route("99999").mock(return_value=httpx.Response(200, json=collection()))

        result = tool_model(
            await get_activity_detail(ctx_never_elicit(), activity_id=activity_id),
            ActivityDetailResponse,
        )

        assert result.body.startswith("word0")
        assert "word4999" in result.body
        assert "<p>" not in result.body
        assert len(result.body) > 10_000


class TestNoteOrDocument:
    @pytest.mark.asyncio
    @respx.mock
    async def test_leaves_meeting_specifics_empty_and_skips_attendees(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ad-3", "org-cara")  # pyright: ignore[reportGeneralTypeIssues]

        activity_id = "activities_555"
        _details_route("555").mock(
            return_value=httpx.Response(
                200,
                json=_detail_document(
                    "555",
                    type="note",
                    title="Follow-up note",
                    description="<p>Called about renewal.</p>",
                ),
            )
        )
        specifics = _specifics_route("555").mock(
            return_value=httpx.Response(200, json=_specifics_document("555"))
        )
        attendees = _attendees_route("555").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = tool_model(
            await get_activity_detail(ctx_never_elicit(), activity_id=activity_id),
            ActivityDetailResponse,
        )

        # Both meeting endpoints 404 for a note's resource id, so skipping them is correctness,
        # not just economy.
        assert attendees.call_count == 0
        assert specifics.call_count == 0
        assert result.activity_id == activity_id
        assert result.type == "note"
        assert result.title == "Follow-up note"
        assert "Called about renewal" in result.body
        assert "<p>" not in result.body
        assert result.start is None
        assert result.stop is None
        assert result.location is None
        assert result.time_zone is None
        assert result.attendees == []


class TestErrorPropagation:
    @pytest.mark.asyncio
    @respx.mock
    async def test_404_propagates_as_backstop_api_error(self, connect_user: ConnectUser) -> None:
        await connect_user("user-ad-4", "org-dina")  # pyright: ignore[reportGeneralTypeIssues]

        activity_id = "meeting-or-calls_missing"
        _details_route("missing").mock(
            return_value=httpx.Response(404, json={"errors": [{"detail": "not found"}]})
        )
        # A meeting handle fans all three fetches out concurrently, so the siblings need mocks
        # for the 404 to be the only failure under test.
        _specifics_route("missing").mock(
            return_value=httpx.Response(200, json=_specifics_document("missing"))
        )
        _attendees_route("missing").mock(return_value=httpx.Response(200, json=collection()))

        with pytest.raises(BackstopApiError):
            await get_activity_detail(ctx_never_elicit(), activity_id=activity_id)

    @pytest.mark.asyncio
    @respx.mock
    async def test_null_primary_data_is_a_404_not_a_schema_error(
        self, connect_user: ConnectUser
    ) -> None:
        """`/entity-activity-details` answers `200 {"data": null}` for an id it cannot resolve."""
        await connect_user("user-ad-8", "org-dina-null")  # pyright: ignore[reportGeneralTypeIssues]

        _details_route("404404").mock(return_value=httpx.Response(200, json={"data": None}))

        with pytest.raises(BackstopApiError) as exc_info:
            await get_activity_detail(ctx_never_elicit(), activity_id="notes_404404")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_bare_id_is_rejected_without_reaching_backstop(
        self, connect_user: ConnectUser
    ) -> None:
        """The composite handle is the only accepted form, and it is checked locally.

        A bare id has no resource type, so there is no collection to send it to — failing here
        beats guessing `/entity-activity-details` and reporting whatever that returns.
        """
        await connect_user("user-ad-9", "org-dina-bare")  # pyright: ignore[reportGeneralTypeIssues]

        with pytest.raises(ToolError, match="not a valid activity_id"):
            await get_activity_detail(ctx_never_elicit(), activity_id="76280387")

        assert len(respx.calls) == 0


class TestDefensiveParsing:
    @pytest.mark.asyncio
    @respx.mock
    async def test_unexpected_field_names_degrade_to_none_rather_than_crash(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ad-5", "org-elle")  # pyright: ignore[reportGeneralTypeIssues]

        activity_id = "meeting-or-calls_777"
        _details_route("777").mock(
            return_value=httpx.Response(
                200,
                json=_detail_document(
                    "777",
                    kind="meeting",
                    heading="Unread",
                    somethingBackstopMightAdd="ignored",
                ),
            )
        )
        _specifics_route("777").mock(
            return_value=httpx.Response(
                200,
                json=_specifics_document(
                    "777",
                    # None of this feature's field names match — every wire spelling here is one
                    # this tool never asked for.
                    startsAt="2026-01-01T00:00:00Z",
                    endsAt="2026-01-01T00:30:00Z",
                    room="Nowhere",
                    tz="UTC",
                ),
            )
        )
        _attendees_route("777").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("att1", "people", nickname="Jay", surname="Only"),
                ),
            )
        )

        result = tool_model(
            await get_activity_detail(ctx_never_elicit(), activity_id=activity_id),
            ActivityDetailResponse,
        )

        assert result.type is None
        assert result.title is None
        assert result.body == ""
        assert result.start is None
        assert result.stop is None
        assert result.location is None
        assert result.time_zone is None
        # The attendee resource still exists (Backstop returned one row) — only its display
        # name resolves to None, since neither `name` nor `firstName`/`lastName` matched.
        assert len(result.attendees) == 1
        assert result.attendees[0].name is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_walks_attendee_pages(self, connect_user: ConnectUser) -> None:
        await connect_user("user-ad-7", "org-gina-ad")  # pyright: ignore[reportGeneralTypeIssues]

        activity_id = "meeting-or-calls_888"
        _details_route("888").mock(
            return_value=httpx.Response(200, json=_detail_document("888", type="meeting"))
        )
        _specifics_route("888").mock(
            return_value=httpx.Response(200, json=_specifics_document("888"))
        )
        _attendees_route("888").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        **collection(resource("att1", "people", name="Jane Doe")),
                        "links": {"next": "/meeting-or-calls/888/attendees?page[offset]=100"},
                    },
                ),
                httpx.Response(
                    200,
                    json=collection(resource("att2", "people", name="John Smith")),
                ),
            ]
        )

        result = tool_model(
            await get_activity_detail(ctx_never_elicit(), activity_id=activity_id),
            ActivityDetailResponse,
        )

        assert [attendee.name for attendee in result.attendees] == ["Jane Doe", "John Smith"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_activity_id_path_segment_is_percent_encoded(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-ad-6", "org-frank-ad")  # pyright: ignore[reportGeneralTypeIssues]

        # `notes_1/../2` splits on the LAST underscore, so the bare id is `1/../2`.
        activity_id = "notes_1/../2"
        details = respx.get(f"{BASE_URL}/entity-activity-details/1%2F..%2F2").mock(
            return_value=httpx.Response(
                200,
                json=_detail_document("1/../2", type="note", title="Safe"),
            )
        )
        attendees = respx.get(url__regex=rf"{BASE_URL}/meeting-or-calls/.+/attendees").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = tool_model(
            await get_activity_detail(ctx_never_elicit(), activity_id=activity_id),
            ActivityDetailResponse,
        )

        assert result.title == "Safe"
        assert details.call_count == 1
        assert attendees.call_count == 0
        assert "/entity-activity-details/1%2F..%2F2" in str(details.calls.last.request.url)
