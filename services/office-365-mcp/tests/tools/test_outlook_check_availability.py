"""Every payload here is synthesised. No calendar entry in this file was ever created for a real
mailbox, and no address in it resolves anywhere."""

import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.calendar import MAX_ATTENDEES
from office_365_mcp.tools.outlook_check_availability import Availability, check_availability

_SCHEDULE_PATH = "/me/calendar/getSchedule"

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"


def _moment(local: str, zone: str = "UTC") -> dict[str, object]:
    return {"dateTime": local, "timeZone": zone}


def _schedule_item(
    *,
    status: str = "busy",
    subject: str | None = "Lunch",
    location: str | None = None,
    is_private: bool | None = False,
    start: str = "2026-03-02T12:00:00.0000000",
    end: str = "2026-03-02T13:00:00.0000000",
) -> dict[str, object]:
    return {
        "status": status,
        "subject": subject,
        "location": location,
        "isPrivate": is_private,
        "start": _moment(start),
        "end": _moment(end),
    }


def _schedule_information(
    *,
    address: str = _ADA,
    availability_view: str | None = "022",
    items: Sequence[Mapping[str, object]] = (),
    error: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "scheduleId": address,
        "availabilityView": availability_view,
        "scheduleItems": [dict(item) for item in items],
        "workingHours": {
            "daysOfWeek": ["monday", "tuesday", "wednesday", "thursday", "friday"],
            "startTime": "08:00:00.0000000",
            "endTime": "17:00:00.0000000",
            "timeZone": {"name": "Pacific Standard Time"},
        },
        "error": dict(error) if error is not None else None,
    }


def _gets_schedule(graph: respx.MockRouter, rows: Sequence[Mapping[str, object]]) -> respx.Route:
    return graph.post(_SCHEDULE_PATH).mock(
        return_value=httpx.Response(200, json={"value": [dict(row) for row in rows]})
    )


async def _check(
    client: GraphServiceClient,
    *,
    addresses: Sequence[str] = (_ADA,),
    starts_at: str = "2026-03-02T09:00",
    ends_at: str = "2026-03-02T17:00",
    time_zone: str = "UTC",
    interval_minutes: int = 30,
) -> Availability:
    return await check_availability(
        client,
        addresses=addresses,
        starts_at=starts_at,
        ends_at=ends_at,
        time_zone=time_zone,
        interval_minutes=interval_minutes,
    )


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


class TestWhatItSendsToGraph:
    async def test_it_calls_getschedule_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        schedule = _gets_schedule(graph, [_schedule_information()])

        _ = await _check(client)

        assert schedule.call_count == 1
        assert len(graph.calls) == 1

    async def test_the_addresses_the_window_and_the_interval_reach_graph_verbatim(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        schedule = _gets_schedule(
            graph, [_schedule_information(), _schedule_information(address=_GRACE)]
        )

        _ = await _check(
            client,
            addresses=[_ADA, _GRACE],
            starts_at="2026-03-02T09:00",
            ends_at="2026-03-02T17:00",
            time_zone="Europe/Zurich",
            interval_minutes=60,
        )

        sent = _sent(schedule)
        assert sent["Schedules"] == [_ADA, _GRACE]
        assert sent["StartTime"] == {"dateTime": "2026-03-02T09:00", "timeZone": "Europe/Zurich"}
        assert sent["EndTime"] == {"dateTime": "2026-03-02T17:00", "timeZone": "Europe/Zurich"}
        assert sent["AvailabilityViewInterval"] == 60


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "address",
        [
            "Ada Lovelace <ada@example.invalid>",
            "ada@example.invalid, grace@example.invalid",
            "ada@",
        ],
    )
    async def test_a_malformed_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, address: str
    ) -> None:
        with pytest.raises(ToolError, match="not one"):
            _ = await _check(client, addresses=[address])

        assert len(graph.calls) == 0

    async def test_a_repeated_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="twice"):
            _ = await _check(client, addresses=[_ADA, _ADA])

        assert len(graph.calls) == 0

    @pytest.mark.parametrize("starts_at", ["tomorrow at 9", "2026-03-02", "2026-03-02T09"])
    async def test_a_time_it_cannot_read_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, starts_at: str
    ) -> None:
        with pytest.raises(ToolError, match="YYYY-MM-DDTHH:MM"):
            _ = await _check(client, starts_at=starts_at)

        assert len(graph.calls) == 0

    async def test_an_end_that_is_not_after_the_start_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="not after"):
            _ = await _check(client, starts_at="2026-03-02T17:00", ends_at="2026-03-02T09:00")

        assert len(graph.calls) == 0

    async def test_more_addresses_than_the_ceiling_never_reach_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        too_many = [f"guest{index}@example.invalid" for index in range(MAX_ATTENDEES + 1)]

        with pytest.raises(ToolError, match="between them|more than"):
            _ = await _check(client, addresses=too_many)

        assert len(graph.calls) == 0


class TestGraphErrors:
    async def test_a_forbidden_response_propagates_as_graph_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_SCHEDULE_PATH).mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await _check(client)


class TestWhatItAnswers:
    async def test_it_reports_one_row_per_address_in_graphs_own_order(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets_schedule(
            graph,
            [
                _schedule_information(address=_GRACE, availability_view="200"),
                _schedule_information(address=_ADA, availability_view="020"),
            ],
        )

        answer = await _check(client, addresses=[_ADA, _GRACE])

        assert [row.address for row in answer.schedules] == [_GRACE, _ADA]
        assert answer.schedules[0].availability_view == "200"

    async def test_a_schedule_item_reports_status_and_the_converted_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets_schedule(
            graph,
            [
                _schedule_information(
                    items=[
                        _schedule_item(
                            status="busy",
                            subject="Lunch",
                            start="2026-03-02T12:00:00.0000000",
                            end="2026-03-02T13:00:00.0000000",
                        )
                    ]
                )
            ],
        )

        answer = await _check(client)

        item = answer.schedules[0].items[0]
        assert item.status == "busy"
        assert item.subject == "Lunch"
        assert item.start is not None
        assert item.start.local == "2026-03-02T12:00:00.0000000"

    async def test_a_schedule_that_could_not_be_read_reports_an_error_and_no_items(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets_schedule(
            graph,
            [
                _schedule_information(
                    availability_view=None,
                    error={"responseCode": "5006", "message": "too many entries"},
                )
            ],
        )

        answer = await _check(client)

        row = answer.schedules[0]
        assert row.items == []
        assert row.error is not None
        assert row.error.response_code == "5006"
        assert row.error.message == "too many entries"

    async def test_the_window_is_echoed_exactly_as_sent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets_schedule(graph, [_schedule_information()])

        answer = await _check(
            client, starts_at="2026-03-02T09:00", ends_at="2026-03-02T17:00", time_zone="UTC"
        )

        assert answer.window.starts_at == "2026-03-02T09:00"
        assert answer.window.ends_at == "2026-03-02T17:00"
        assert answer.window.time_zone == "UTC"
        assert answer.interval_minutes == 30
