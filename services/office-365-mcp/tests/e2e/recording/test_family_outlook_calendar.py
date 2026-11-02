import asyncio
import base64
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import yaml
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport

from office_365_mcp.tools import TOOL_NAMES
from tests.e2e.recording import stand_in
from tests.e2e.recording.cases import case_entries
from tests.e2e.recording.families import load, merge
from tests.e2e.recording.families import outlook_calendar as family
from tests.e2e.recording.guard import DEFAULT_CAP, Guard
from tests.e2e.recording.lint import lint_files
from tests.e2e.recording.record import Plan, check, guard_for, resolve, tool_of
from tests.e2e.recording.runbook import reads
from tests.e2e.recording.scrub import Hop, Identities, Recording, files_of, scrub
from tests.e2e.test_scenarios import Json, build_server, mapping, select

GRAPH = "https://graph.microsoft.com/v1.0"
CORPUS = Path(__file__).resolve().parents[3] / "scripts/dogfood/seed/corpus/outlook-calendar.yaml"
TOOLS = frozenset(
    {
        "outlook_cancel_event",
        "outlook_check_availability",
        "outlook_create_contact",
        "outlook_create_event",
        "outlook_create_event_on_behalf",
        "outlook_delete_calendar",
        "outlook_delete_event",
        "outlook_find_recipient",
        "outlook_find_rooms",
        "outlook_forward_event",
        "outlook_list_calendar_groups",
        "outlook_list_calendar_shares",
        "outlook_list_calendars",
        "outlook_list_contacts",
        "outlook_list_event_attachments",
        "outlook_list_event_instances",
        "outlook_list_events",
        "outlook_list_group_events",
        "outlook_list_reminders",
        "outlook_list_time_zones",
        "outlook_read_contact",
        "outlook_read_event",
        "outlook_read_event_attachment",
        "outlook_respond_to_invite",
        "outlook_share_calendar",
        "outlook_suggest_meeting_times",
        "outlook_unshare_calendar",
        "outlook_update_contact",
        "outlook_update_event",
    }
)
CASES = {
    case_id: resolve(case_id)
    for case_id, _ in case_entries()
    if tool_of(resolve(case_id).steps[-1]) in TOOLS
}
SEEDED = "AAMkSEEDED"
CREATED = "AAMkCREATED"
CALENDAR = "AAMkCALENDAR"


def guard(**fields: object) -> Guard:
    return Guard(stand_in.UPN, frozenset(stand_in.UPNS), True, **fields)  # pyright: ignore[reportArgumentType]


def request(method: str, path: str, body: str = "") -> httpx.Request:
    return httpx.Request(method, f"{GRAPH}{path}", content=body)


def test_the_family_claims_exactly_its_29_tools() -> None:
    alone = merge([family])
    assert alone.read_tools | set(alone.write_tools) == TOOLS
    assert set(TOOL_NAMES) >= TOOLS
    assert len(TOOLS) == 29
    assert set(alone.read_posts) <= alone.read_tools
    assert alone.external <= set(alone.write_tools)
    assert load().needs.keys() >= family.NEEDS.keys() == family.PROBES.keys()


def test_every_tool_has_a_case_and_every_case_ends_in_its_tool() -> None:
    assert {tool_of(plan.steps[-1]) for plan in CASES.values()} == TOOLS
    for case_id, plan in CASES.items():
        assert case_id.startswith(f"{tool_of(plan.steps[-1])}-")


@pytest.mark.parametrize("case_id", CASES)
def test_a_case_passes_the_guard_plan_and_uses_only_the_three_personas(case_id: str) -> None:
    plan = CASES[case_id]
    assert check(plan, guard_for(stand_in.UPNS, plan, True, DEFAULT_CAP)) == []
    assert plan.persona == 1
    assert plan.cap == 0
    text = json.dumps(plan.steps)
    assert "@" not in text
    for step in plan.steps:
        given = {**mapping(step.get("args", {})), **mapping(step.get("bind", {}))}
        if tool_of(step) in family.WRITE_TOOLS:
            assert not {"attendees", "optional_attendees", "room_addresses", "online_meeting"} & {
                key for key, value in given.items() if value
            }
    if tool_of(plan.steps[-1]) in family.WRITE_TOOLS:
        assert not reads(plan)
    else:
        assert reads(plan)
        assert not {tool_of(step) for step in plan.steps} & set(family.WRITE_TOOLS)


@pytest.mark.parametrize("case_id", CASES)
def test_a_write_case_names_what_it_creates_and_what_it_consumes(case_id: str) -> None:
    plan: Plan = CASES[case_id]
    created = [step for step in plan.steps if tool_of(step) in family.WRITE_TOOLS]
    for step in created:
        args = cast("Json", step.get("args", {}))
        named = [str(args[key]) for key in ("subject", "display_name") if key in args]
        if tool_of(step) in {"outlook_create_event", "outlook_create_contact"} | {
            "outlook_create_event_on_behalf"
        }:
            assert all(f"seed-v1 case-{case_id}" in name for name in named)
            assert named
    assert (plan.destructive, plan.reseed) in {
        (False, ()),
        (True, ("cal-events",)),
        (True, ("cal-calendars",)),
    }
    if plan.destructive:
        assert tool_of(plan.steps[-1]) in {"outlook_cancel_event", "outlook_delete_calendar"}
    assert plan.external == (tool_of(plan.steps[-1]) in family.EXTERNAL)


def test_the_blocked_cases_name_their_needs() -> None:
    needs = {case_id: plan.needs for case_id, plan in CASES.items() if plan.needs}
    assert needs == {
        "outlook_find_rooms-all": ("rooms",),
        "outlook_list_group_events-team": ("group_calendar",),
    }


def test_only_the_find_recipient_case_depends_on_the_search_index() -> None:
    found = {
        case_id
        for case_id, plan in CASES.items()
        if any(tool_of(step) == "outlook_find_recipient" for step in plan.steps)
    }
    assert found == {"outlook_find_recipient-anna"}


def test_a_calendar_index_in_a_bind_is_guarded_by_an_expect_on_the_same_index() -> None:
    pattern = re.compile(r"\$prev\.(calendars\[\d+\])\.uri")
    for case_id, plan in CASES.items():
        for before, step in zip(plan.steps, plan.steps[1:], strict=False):
            for selector in cast("list[str]", pattern.findall(json.dumps(step.get("bind", {})))):
                guard = mapping(mapping(before.get("expect", {})).get("result", {}))
                assert f"{selector}.name" in guard, case_id


def test_the_group_calendar_case_asks_for_the_group_scope() -> None:
    assert CASES["outlook_list_group_events-team"].scopes == ("Group.Read.All",)


def test_a_reminder_link_with_a_slash_in_its_item_id_passes_the_lint() -> None:
    item = "AAMkHBzfVUB3DCJ6GHUkSNgl/TajAMH28+eIRKKdaCijLqob/UhiNSCdQxNfNMI="
    link = f"https://outlook.office365.com/owa/?itemid={quote(item, safe='')}&exvsurl=1"
    body: Json = {"value": [{"eventSubject": "Submit the expense report", "eventWebLink": link}]}
    recording = Recording(
        "outlook-calendar-reminder-link",
        "rec-tool-outlook-calendar-reminder-link",
        "stand-in",
        datetime(2026, 10, 29, tzinfo=UTC),
        (hop("/me/reminders", body),),
        Identities(frozenset({stand_in.USER_ID, stand_in.UPN, stand_in.DOMAIN}), stand_in.TOKEN),
        {},
        frozenset(),
    )
    files = files_of(scrub(recording))
    assert lint_files(files, {stand_in.USER_ID, stand_in.UPN, stand_in.DOMAIN}) == []


@cache
def schemas() -> Mapping[str, Json]:
    async def listed() -> dict[str, Json]:
        async with Client(FastMCPTransport(build_server())) as client:
            return {
                tool.name: {"in": tool.input_schema, "out": tool.output_schema or {}}
                for tool in await client.list_tools()
            }

    return asyncio.run(listed())


def walks(schema: Json, path: str) -> bool:
    for token in cast("list[str]", re.findall(r"\[(?:\d+|\*)\]|[^.\[]+", path)):
        if token.startswith("["):
            schema = cast("Json", schema.get("items", {}))
            continue
        properties = cast("Json", schema.get("properties", {}))
        if token not in properties:
            return False
        schema = cast("Json", properties[token])
        for option in cast("list[Json]", schema.get("anyOf", [])):
            schema = option if option.get("type") in {"object", "array"} else schema
    return True


@pytest.mark.parametrize("case_id", CASES)
def test_a_chain_gives_its_tools_real_arguments_and_reads_real_answer_keys(case_id: str) -> None:
    plan = CASES[case_id]
    for number, step in enumerate(plan.steps, 1):
        tool = schemas()[tool_of(step)]
        arguments = cast("Json", tool["in"])
        given = {**mapping(step.get("args", {})), **mapping(step.get("bind", {}))}
        assert set(given) <= set(cast("Json", arguments["properties"])), tool_of(step)
        assert set(cast("list[str]", arguments.get("required", []))) <= set(given), tool_of(step)
        for value in json.dumps(step.get("bind", {})).split('"'):
            found = re.fullmatch(r"\$(prev|\d+)\.(.+)", value)
            if found:
                earlier = plan.steps[number - 2 if found[1] == "prev" else int(found[1]) - 1]
                assert walks(cast("Json", schemas()[tool_of(earlier)]["out"]), found[2]), value


@pytest.mark.parametrize(
    ("tool", "method", "path", "ok"),
    [
        ("outlook_create_event", "POST", "/me/events", True),
        ("outlook_create_event", "POST", "/me/calendars/x/events", False),
        ("outlook_create_event_on_behalf", "POST", f"/me/calendars/{SEEDED}/events", True),
        ("outlook_create_event_on_behalf", "POST", "/me/calendars/other/events", False),
        ("outlook_update_event", "PATCH", f"/me/calendars/{SEEDED}/events/{CREATED}", True),
        ("outlook_update_event", "PATCH", f"/me/calendars/{SEEDED}/events/{CREATED}/x", False),
        ("outlook_delete_event", "DELETE", f"/me/calendars/{SEEDED}/events/{CREATED}", True),
        ("outlook_delete_event", "DELETE", "/me/calendars/other/events/other", False),
        ("outlook_delete_calendar", "DELETE", f"/me/calendars/{SEEDED}", True),
        ("outlook_delete_calendar", "DELETE", "/me/calendars/other", False),
        ("outlook_cancel_event", "POST", f"/me/calendars/{SEEDED}/events/{CREATED}/cancel", True),
        ("outlook_cancel_event", "POST", f"/me/calendars/{SEEDED}/events/{CREATED}/forward", False),
        ("outlook_forward_event", "POST", f"/me/calendars/{SEEDED}/events/{CREATED}/forward", True),
        (
            "outlook_respond_to_invite",
            "POST",
            f"/me/calendars/{SEEDED}/events/{CREATED}/accept",
            True,
        ),
        (
            "outlook_respond_to_invite",
            "POST",
            f"/me/calendars/{SEEDED}/events/{CREATED}/cancel",
            False,
        ),
        ("outlook_share_calendar", "POST", f"/me/calendars/{SEEDED}/calendarPermissions", True),
        ("outlook_share_calendar", "POST", "/me/calendars/other/calendarPermissions", False),
        (
            "outlook_unshare_calendar",
            "DELETE",
            f"/me/calendars/{SEEDED}/calendarPermissions/{CREATED}",
            True,
        ),
        (
            "outlook_unshare_calendar",
            "DELETE",
            f"/me/calendars/{SEEDED}/calendarPermissions/other",
            False,
        ),
        ("outlook_create_contact", "POST", "/me/contacts", True),
        ("outlook_update_contact", "PATCH", f"/me/contacts/{CREATED}", True),
        ("outlook_update_contact", "PATCH", "/me/contacts/other", False),
        ("outlook_check_availability", "POST", "/me/calendar/getSchedule", True),
        ("outlook_check_availability", "POST", "/me/findMeetingTimes", False),
        ("outlook_suggest_meeting_times", "POST", "/me/findMeetingTimes", True),
        ("outlook_list_events", "POST", "/me/findMeetingTimes", False),
        ("outlook_list_group_events", "GET", "/groups/g1/calendarView", True),
        ("outlook_find_rooms", "GET", "/places/microsoft.graph.room", True),
        ("outlook_list_group_events", "DELETE", "/groups/g1", False),
        ("outlook_find_rooms", "POST", "/places/microsoft.graph.room", False),
        ("outlook_list_events", "GET", "/users/someone-else/calendar", False),
    ],
)
def test_the_guard_allows_the_paths_of_a_tool_and_nothing_else(
    tool: str, method: str, path: str, ok: bool
) -> None:
    made = guard(seen_seed={SEEDED}, created={CREATED})
    assert (made.refuses_request(request(method, path, "{}"), tool) is None) is ok


def test_a_write_to_the_default_calendar_is_refused() -> None:
    made = guard(seen_seed={SEEDED})
    refusal = made.refuses_request(
        request("DELETE", f"/me/calendars/{CALENDAR}/events/{CREATED}"), "outlook_delete_event"
    )
    assert "did not read as seed data" in str(refusal)


def test_a_share_with_an_outside_address_is_refused() -> None:
    made = guard(seen_seed={SEEDED})
    body = json.dumps({"emailAddress": {"address": "a@evil.example"}, "role": "read"})
    path = f"/me/calendars/{SEEDED}/calendarPermissions"
    assert "not a test user" in str(
        made.refuses_request(request("POST", path, body), "outlook_share_calendar")
    )


def test_a_case_with_attendees_in_a_write_is_refused_before_any_request() -> None:
    refused = guard().refuses_call("outlook_create_event", {"attendees": ["x"]})
    assert refused is not None
    assert "invite" in refused


def stamp(day: str = "2026-10-29") -> Json:
    return {"dateTime": f"{day}T09:15:00.0000000", "timeZone": "W. Europe Standard Time"}


def hop(path: str, body: Json, method: str = "GET", status: int = 200) -> Hop:
    asked = {"method": method, "host": "graph.microsoft.com", "path": path}
    asked |= {"query": {}, "headers": {}, "json": None}
    headers = (("content-type", "application/json"),)
    return Hop(asked, f"{GRAPH}{path}", True, status, headers, json.dumps(body).encode())


def test_the_calendar_shapes_scrub_and_pass_the_lint() -> None:
    mia, anna = stand_in.UPNS[0], stand_in.UPNS[1]
    spec = cast("Json", yaml.safe_load(CORPUS.read_text()))
    agenda = cast("Json", cast("Json", spec["attachments"])["agenda"])
    event_id, series_id = (
        stand_in.exchange_id(b"\x00\x03\x24\x00", 7),
        stand_in.exchange_id(b"\x00\x03\x24\x00", 8),
    )
    person = {"name": "Anna Meier", "address": anna}
    event: Json = {
        "id": event_id,
        "@odata.etag": 'W/"DwAAABYAAAAx9pF7Lq1gQ4WmKxTt8p0aBcDeFgHi"',
        "subject": "Daily standup",
        "bodyPreview": "Yesterday, today, blockers.",
        "body": {"contentType": "text", "content": "Yesterday, today, blockers."},
        "start": stamp(),
        "end": stamp(),
        "isAllDay": False,
        "isCancelled": False,
        "type": "occurrence",
        "seriesMasterId": series_id,
        "sensitivity": "normal",
        "showAs": "busy",
        "location": {
            "displayName": "Room Pilatus",
            "locationType": "default",
            "uniqueId": "Room Pilatus",
        },
        "isOnlineMeeting": True,
        "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/l/meetup-join/19%3ameeting_x/0"},
        "organizer": {"emailAddress": {"name": "Mia Keller", "address": mia}},
        "isOrganizer": True,
        "responseStatus": {"response": "organizer", "time": "0001-01-01T00:00:00Z"},
        "attendees": [{"type": "required", "emailAddress": person, "status": {"response": "none"}}],
        "webLink": "https://outlook.office365.com/owa/?itemid=x&exvsurl=1&path=/calendar/item",
        "categories": ["seed-v1"],
        "importance": "normal",
        "hasAttachments": False,
        "responseRequested": True,
        "allowNewTimeProposals": True,
        "hideAttendees": False,
        "isReminderOn": True,
        "reminderMinutesBeforeStart": 15,
        "originalStartTimeZone": "W. Europe Standard Time",
        "transactionId": "5e8d1c3a-94b7-4f20-a6e1-7c2b9d0f4a85",
        "recurrence": {
            "pattern": {
                "type": "daily",
                "interval": 1,
                "firstDayOfWeek": "sunday",
                "index": "first",
            },
            "range": {"type": "numbered", "startDate": "2026-10-28", "numberOfOccurrences": 10},
        },
    }
    calendar: Json = {
        "id": CALENDAR,
        "name": "seed-v1 Shared calendar",
        "owner": {"name": "Mia Keller", "address": mia},
        "canEdit": True,
        "isDefaultCalendar": False,
        "allowedOnlineMeetingProviders": ["teamsForBusiness"],
        "color": "auto",
        "hexColor": "",
        "isRemovable": True,
    }
    share: Json = {
        "id": CREATED,
        "emailAddress": person,
        "role": "freeBusyRead",
        "isRemovable": True,
    }
    share |= {"isInsideOrganization": True, "allowedRoles": ["freeBusyRead", "read"]}
    reminder: Json = {
        "eventId": event_id,
        "eventStartTime": stamp(),
        "eventEndTime": stamp(),
        "eventSubject": "Submit the expense report",
        "eventLocation": {"displayName": "", "locationType": "default"},
        "eventWebLink": "https://outlook.office365.com/owa/?itemid=x",
        "reminderFireTime": stamp(),
    }
    contact: Json = {
        "id": CREATED,
        "displayName": "Lena Fischer",
        "givenName": "Lena",
        "surname": "Fischer",
        "emailAddresses": [person],
        "businessPhones": ["+41 44 555 01 01"],
        "homePhones": [],
        "mobilePhone": None,
        "companyName": "Alpine Print",
        "jobTitle": "Account Manager",
        "categories": ["seed-v1"],
        "birthday": None,
        "imAddresses": [],
        "children": [],
        "businessAddress": {},
    }
    attachment: Json = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "id": CREATED,
        "name": "calendar-agenda.txt",
        "contentType": "text/plain",
        "size": 52,
        "isInline": False,
        "contentBytes": base64.b64encode(str(agenda["text"]).encode()).decode(),
    }
    schedule: Json = {
        "scheduleId": anna,
        "availabilityView": "000220000",
        "workingHours": {"x": 1},
        "scheduleItems": [{"status": "busy", "isPrivate": False, "start": stamp(), "end": stamp()}],
    }
    suggestion: Json = {
        "confidence": 100.0,
        "organizerAvailability": "free",
        "suggestionReason": "Suggested because all attendees are free.",
        "meetingTimeSlot": {"start": stamp(), "end": stamp()},
        "attendeeAvailability": [
            {
                "availability": "free",
                "attendee": {"type": "required", "emailAddress": {"address": anna}},
            }
        ],
    }
    people: Json = {
        "id": CREATED,
        "displayName": "Anna Meier",
        "scoredEmailAddresses": [{"address": anna, "relevanceScore": 10.0}],
        "userPrincipalName": anna,
        "personType": {"class": "Person", "subclass": "OrganizationUser"},
        "jobTitle": "Finance Controller",
    }
    room: Json = {
        "id": CREATED,
        "displayName": "Room Rigi",
        "emailAddress": f"rigi@{stand_in.DOMAIN}",
        "capacity": 8,
        "bookingType": "standard",
        "isWheelChairAccessible": True,
        "address": {"street": "Seestrasse 1"},
    }
    zone: Json = {"alias": "Pacific Standard Time", "displayName": "(UTC-08:00) Pacific Time"}
    group: Json = {"id": CREATED, "name": "My Calendars", "classId": stand_in.TENANT_ID}
    me: Json = {"id": stand_in.USER_ID, "mail": mia, "userPrincipalName": mia}
    hops = (
        hop("/me", me),
        hop("/me/calendars", {"value": [calendar]}),
        hop("/me/calendarGroups", {"value": [group]}),
        hop(f"/me/calendars/{CALENDAR}/calendarView", {"value": [event]}),
        hop(f"/me/calendars/{CALENDAR}/calendarPermissions", {"value": [share]}),
        hop("/me/reminderView(startDateTime='x',endDateTime='y')", {"value": [reminder]}),
        hop("/me/outlook/supportedTimeZones", {"value": [zone]}),
        hop("/me/contacts", {"value": [contact]}),
        hop(f"/me/events/{event_id}/attachments/{CREATED}", attachment),
        hop("/me/calendar/getSchedule", {"value": [schedule]}, "POST"),
        hop("/me/findMeetingTimes", {"meetingTimeSuggestions": [suggestion]}, "POST"),
        hop("/me/people", {"value": [people]}),
        hop("/places/microsoft.graph.room", {"value": [room]}),
    )
    names = dict(zip(stand_in.UPNS, ("mia", "anna", "tom"), strict=True))
    recording = Recording(
        "outlook-calendar-shapes",
        "rec-tool-outlook-calendar-shapes",
        "stand-in",
        datetime(2026, 10, 29, tzinfo=UTC),
        hops,
        Identities(frozenset({stand_in.USER_ID, stand_in.UPN, stand_in.DOMAIN}), stand_in.TOKEN),
        {upn.casefold(): key for upn, key in names.items()},
        frozenset(),
    )
    fixture = scrub(recording)
    assert set(fixture.dropped) == {"workingHours", "address", "status"}
    files = files_of(fixture)
    assert lint_files(files, {stand_in.USER_ID, stand_in.UPN, stand_in.DOMAIN}) == []
    kept = {
        n: cast("object", json.loads(files[f"bodies/{fixture.name}.{n:02d}.json"]))
        for n in range(1, 14)
    }
    expected: dict[tuple[int, str], object] = {
        (1, "mail"): "mia@example.test",
        (2, "value[0].name"): "seed-v1 Shared calendar",
        (2, "value[0].owner.address"): "mia@example.test",
        (4, "value[0].subject"): "Daily standup",
        (4, "value[0].type"): "occurrence",
        (4, "value[0].recurrence.pattern.type"): "daily",
        (4, "value[0].attendees[0].emailAddress.address"): "anna@example.test",
        (5, "value[0].role"): "freeBusyRead",
        (6, "value[0].eventSubject"): "Submit the expense report",
        (8, "value[0].businessPhones"): ["+41 44 555 01 01"],
        (9, "contentBytes"): attachment["contentBytes"],
        (10, "value[0].scheduleItems[0].status"): "busy",
        (10, "value[0].availabilityView"): "000220000",
        (11, "meetingTimeSuggestions[0].confidence"): 100.0,
        (12, "value[0].scoredEmailAddresses[0].address"): "anna@example.test",
        (13, "value[0].capacity"): 8,
    }
    for (number, path), value in expected.items():
        assert select(kept[number], path) == value, (number, path)
    joined = str(select(kept[4], "value[0].onlineMeeting.joinUrl"))
    assert joined.startswith("https://teams.microsoft.com/")
