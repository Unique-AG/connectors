from datetime import datetime

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.activity_history import ActivityDetailResponse, ResourceIdentifierDto
from tests.features.activity_history.conftest import make_get_activity_detail_query
from tests.features.party_resolver.helpers import BASE_URL, collection
from tests.helpers import resource


def _detail_document(resource_id: str, **attributes: object) -> dict[str, object]:
    return {
        "data": {"type": "entity-activity-details", "id": resource_id, "attributes": attributes}
    }


def _specifics_document(resource_id: str, **attributes: object) -> dict[str, object]:
    return {"data": {"type": "meeting-or-calls", "id": resource_id, "attributes": attributes}}


async def _run(client: BackstopClient, activity_id: str) -> ActivityDetailResponse:
    handle = ResourceIdentifierDto.from_activity_id(activity_id)
    return await make_get_activity_detail_query(client).run(activity_id=activity_id, handle=handle)


class TestGetActivityDetailQuery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_run_gathers_meeting_specifics_and_attendees(
        self, client: BackstopClient
    ) -> None:
        activity_id = "meeting-or-calls_76280387"
        respx.get(f"{BASE_URL}/entity-activity-details/76280387").mock(
            return_value=httpx.Response(
                200,
                json=_detail_document(
                    "76280387",
                    type="meeting",
                    title="Quarterly check-in",
                    description="<p>Agenda</p>",
                ),
            )
        )
        respx.get(f"{BASE_URL}/meeting-or-calls/76280387").mock(
            return_value=httpx.Response(
                200,
                json=_specifics_document(
                    "76280387",
                    startTimestamp="2026-01-05T15:00:00Z",
                    location="HQ",
                    timeZone="America/New_York",
                ),
            )
        )
        respx.get(f"{BASE_URL}/meeting-or-calls/76280387/attendees").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("att1", "people", name="Jane Doe")),
            )
        )

        result = await _run(client, activity_id)

        assert result.activity_id == activity_id
        assert result.type == "meeting"
        assert result.location == "HQ"
        assert result.start == datetime.fromisoformat("2026-01-05T15:00:00+00:00")
        assert [attendee.name for attendee in result.attendees] == ["Jane Doe"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_run_skips_meeting_routes_for_a_note_handle(self, client: BackstopClient) -> None:
        activity_id = "notes_555"
        respx.get(f"{BASE_URL}/entity-activity-details/555").mock(
            return_value=httpx.Response(
                200,
                json=_detail_document("555", type="note", title="Follow-up"),
            )
        )
        specifics = respx.get(f"{BASE_URL}/meeting-or-calls/555").mock(
            return_value=httpx.Response(200, json=_specifics_document("555"))
        )
        attendees = respx.get(f"{BASE_URL}/meeting-or-calls/555/attendees").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = await _run(client, activity_id)

        assert specifics.call_count == 0
        assert attendees.call_count == 0
        assert result.type == "note"
        assert result.attendees == []
        assert result.start is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_run_loads_meeting_extras_after_a_bare_id_detail(
        self, client: BackstopClient
    ) -> None:
        activity_id = "75213203"
        respx.get(f"{BASE_URL}/entity-activity-details/{activity_id}").mock(
            return_value=httpx.Response(
                200,
                json=_detail_document(activity_id, type="meeting", title="Review"),
            )
        )
        respx.get(f"{BASE_URL}/meeting-or-calls/{activity_id}").mock(
            return_value=httpx.Response(
                200,
                json=_specifics_document(activity_id, location="Koch HQ"),
            )
        )
        respx.get(f"{BASE_URL}/meeting-or-calls/{activity_id}/attendees").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = await _run(client, activity_id)

        assert result.location == "Koch HQ"
        assert result.attendees == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_run_treats_null_primary_data_as_404(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/entity-activity-details/404404").mock(
            return_value=httpx.Response(200, json={"data": None})
        )

        with pytest.raises(BackstopApiError) as exc_info:
            await _run(client, "notes_404404")

        assert exc_info.value.status_code == 404
