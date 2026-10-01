import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.tools.outlook_check_availability import (
    TOOL_NAME,
    Availability,
    check_availability,
    register,
)

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


_OFFICE_HOURS: Mapping[str, object] = {
    "daysOfWeek": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "startTime": "08:00:00.0000000",
    "endTime": "17:00:00.0000000",
    "timeZone": {"name": "Pacific Standard Time"},
}


def _schedule_information(
    *,
    address: str = _ADA,
    availability_view: str | None = "022",
    items: Sequence[Mapping[str, object]] = (),
    error: Mapping[str, object] | None = None,
    working_hours: Mapping[str, object] | None = _OFFICE_HOURS,
) -> dict[str, object]:
    return {
        "scheduleId": address,
        "availabilityView": availability_view,
        "scheduleItems": [dict(item) for item in items],
        "workingHours": dict(working_hours) if working_hours is not None else None,
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


def _described(tool: Tool) -> dict[str, str | None]:
    answer = cast("Mapping[str, object]", tool.output_schema)
    definitions = cast("Mapping[str, Mapping[str, object]]", answer.get("$defs", {}))
    models: dict[str, Mapping[str, object]] = {"answer": answer, **definitions}
    return {
        f"{model}.{name}": cast("Mapping[str, str | None]", field).get("description")
        for model, schema in models.items()
        for name, field in cast("Mapping[str, object]", schema["properties"]).items()
    }


@pytest.fixture
async def published(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    register(mcp, transport)
    tool = await mcp.get_tool(TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


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

    async def test_twenty_one_addresses_reach_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        many = [f"guest{index}@example.invalid" for index in range(21)]
        schedule = _gets_schedule(graph, [])

        _ = await _check(client, addresses=many)

        assert _sent(schedule)["Schedules"] == many

    async def test_working_hours_ride_on_the_request_it_already_sends(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        schedule = _gets_schedule(graph, [_schedule_information()])

        _ = await _check(client)

        assert set(_sent(schedule)) == {
            "Schedules",
            "StartTime",
            "EndTime",
            "AvailabilityViewInterval",
        }
        assert schedule.calls.last.request.url.query == b""


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

    async def test_each_row_reports_the_working_hours_of_its_owner(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets_schedule(
            graph,
            [
                _schedule_information(address=_ADA),
                _schedule_information(
                    address=_GRACE,
                    working_hours={
                        "daysOfWeek": ["tuesday", "thursday"],
                        "startTime": "09:30:00.0000000",
                        "endTime": "18:00:00.0000000",
                        "timeZone": {"name": "W. Europe Standard Time"},
                    },
                ),
            ],
        )

        answer = await _check(client, addresses=[_ADA, _GRACE])

        ada, grace = (row.working_hours for row in answer.schedules)
        assert ada is not None
        assert ada.days == ["monday", "tuesday", "wednesday", "thursday", "friday"]
        assert (ada.starts_at, ada.ends_at) == ("08:00:00", "17:00:00")
        assert ada.time_zone == "Pacific Standard Time"
        assert grace is not None
        assert grace.days == ["tuesday", "thursday"]
        assert (grace.starts_at, grace.ends_at) == ("09:30:00", "18:00:00")
        assert grace.time_zone == "W. Europe Standard Time"

    async def test_working_hours_graph_did_not_send_are_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets_schedule(graph, [_schedule_information(working_hours=None)])

        answer = await _check(client)

        assert answer.schedules[0].working_hours is None

    async def test_a_custom_zone_keeps_the_name_graph_gave_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets_schedule(
            graph,
            [
                _schedule_information(
                    working_hours={
                        **_OFFICE_HOURS,
                        "timeZone": {
                            "@odata.type": "#microsoft.graph.customTimeZone",
                            "bias": 480,
                            "name": "Customized Time Zone",
                        },
                    }
                )
            ],
        )

        answer = await _check(client)

        hours = answer.schedules[0].working_hours
        assert hours is not None
        assert hours.time_zone == "Customized Time Zone"

    async def test_working_hours_with_no_fields_report_no_days_and_no_times(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _gets_schedule(graph, [_schedule_information(working_hours={})])

        answer = await _check(client)

        hours = answer.schedules[0].working_hours
        assert hours is not None
        assert hours.days == []
        assert (hours.starts_at, hours.ends_at, hours.time_zone) == (None, None, None)

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


class TestWhatItPublishes:
    def test_every_field_of_the_answer_says_what_it_is(self, published: Tool) -> None:
        described = _described(published)

        assert "WorkingHoursSummary.time_zone" in described
        undescribed = sorted(path for path, text in described.items() if not text)
        assert undescribed == [], "a model is handed these values with nothing to say what they are"

    def test_the_working_hours_field_says_which_zone_its_times_use(self, published: Tool) -> None:
        text = _described(published)["MailboxSchedule.working_hours"] or ""

        assert "`working_hours.time_zone`" in text
        assert "not the zone of the window" in text

    def test_the_description_names_working_hours_and_still_says_that_it_only_reads(
        self, published: Tool
    ) -> None:
        description = published.description or ""

        assert "the free/busy status and the working hours of one or more mailboxes" in description
        assert "This tool only reads, and nothing here books, invites, or changes anything." in (
            description
        )

    def test_the_notes_say_that_working_hours_are_not_free_busy_data(self, published: Tool) -> None:
        notes = (published.description or "").partition("Notes:")[2]

        assert "does not depend on the window" in notes
        assert "does not mark any slot as free or busy" in notes
        assert "compare the slot with `working_hours`" in notes

    def test_the_description_keeps_the_house_shape(self, published: Tool) -> None:
        description = published.description or ""

        lead, separator, notes = description.partition("\n\nNotes:\n")
        assert separator, "a lead paragraph, a blank line, then Notes:"
        assert "\n" not in lead.strip()
        assert 1 <= sum(line.startswith("- ") for line in notes.splitlines()) <= 4
        assert 45 <= len(description.split()) <= 210
