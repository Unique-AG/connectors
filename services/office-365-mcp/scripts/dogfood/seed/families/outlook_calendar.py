import base64
import datetime as dt
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from model import ConfigError, Context, Step

if TYPE_CHECKING:
    from seed import Graph

TAG = "seed-v1"
CASE = f"{TAG} case-"
KEY_PROP = "String {8c0e3b2a-6f1d-4d6e-9a57-2f3c5b7e9d10} Name SeedKey"
KEY_EXPAND = f"singleValueExtendedProperties($filter=id eq '{KEY_PROP}')"
PHASES: tuple[str, ...] = (
    "cal-calendars",
    "cal-events",
    "cal-contacts",
    "cal-invites",
    "cal-answers",
    "cal-series",
    "cal-bulk",
    "cal-settings",
    "cal-shared",
    "cal-group",
)
OWNER = "mia"
CORE_PHASES = frozenset({"folders", "mail", "events", "files"})
TEAM_NAME = f"{TAG} team"
CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "outlook-calendar.yaml"
SPEC: Mapping[str, Any] = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
TAGGED = (("$select", "id,subject"), ("$expand", KEY_EXPAND), ("$top", "100"))
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_WORD = re.compile(r"next([A-Za-z]+)([+-]\d+)?")
_FIXED: tuple[str, ...] = (
    "Overlap",
    "Slot",
    "(UTC-12:00) International Date Line West",
    "(UTC-08:00) Pacific Time (US & Canada)",
    "(UTC-07:00) Mountain Time (US & Canada)",
    "(UTC-06:00) Central Time (US & Canada)",
    "(UTC-05:00) Eastern Time (US & Canada)",
    "(UTC-03:00) Brasilia",
    "(UTC) Coordinated Universal Time",
    "(UTC+00:00) Dublin, Edinburgh, Lisbon, London",
    "(UTC+01:00) Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna",
    "(UTC+01:00) Brussels, Copenhagen, Madrid, Paris",
    "(UTC+01:00) Belgrade, Bratislava, Budapest, Ljubljana, Prague",
    "(UTC+02:00) Athens, Bucharest",
    "(UTC+02:00) Helsinki, Kyiv, Riga, Sofia, Tallinn, Vilnius",
    "(UTC+03:00) Moscow, St. Petersburg",
    "(UTC+04:00) Abu Dhabi, Muscat",
    "(UTC+05:30) Chennai, Kolkata, Mumbai, New Delhi",
    "(UTC+08:00) Beijing, Chongqing, Hong Kong, Urumqi",
    "(UTC+08:00) Perth",
    "(UTC+09:00) Osaka, Sapporo, Tokyo",
    "(UTC+10:00) Canberra, Melbourne, Sydney",
    "(UTC+12:00) Auckland, Wellington",
)

type Spec = Mapping[str, Any]


def _marks(key: str) -> list[dict[str, str]]:
    return [{"id": KEY_PROP, "value": f"{TAG}:{key}"}]


def _day(word: int | str, anchor: dt.date) -> dt.date:
    if isinstance(word, int):
        return anchor + dt.timedelta(days=word)
    found = DAY_WORD.fullmatch(word)
    if found is None:
        raise ConfigError(f"{word} is not a day number or a day word such as nextMonday+1")
    first = anchor + dt.timedelta(days=1)
    wanted = WEEKDAYS.index(found[1].lower())
    return first + dt.timedelta(days=(wanted - first.weekday()) % 7 + int(found[2] or 0))


def _bulk() -> list[Spec]:
    spec = SPEC["bulk"]
    opens = dt.datetime.strptime(spec["start"], "%H:%M")
    slots = [
        (opens + dt.timedelta(minutes=spec["step_minutes"] * n)).time()
        for n in range(spec["per_day"])
    ]
    return [
        {
            "id": f"bulk-{number:02d}",
            "phase": spec["phase"],
            "subject": f"{spec['subject']} {number:02d}",
            "body": spec["body"],
            "time_zone": spec["time_zone"],
            "day": f"nextMonday+{spec['week_shift'] + offset}",
            "start": slot.strftime("%H:%M"),
            "end": (
                dt.datetime.combine(dt.date.min, slot)
                + dt.timedelta(minutes=spec["length_minutes"])
            ).strftime("%H:%M"),
        }
        for number, (offset, slot) in enumerate(
            ((day, slot) for day in range(spec["days"]) for slot in slots), 1
        )
    ]


EVENTS: tuple[Spec, ...] = (*SPEC["events"], *_bulk())
STRINGS: tuple[str, ...] = (
    *_FIXED,
    *(one[key] for one in SPEC["group_events"] for key in ("subject", "body")),
    *(answer["comment"] for event in EVENTS for answer in event.get("answers", [])),
)


def _owner_of(item: Spec) -> str:
    return item.get("owner", OWNER)


def _answer_of(event: Spec, who: str) -> Spec | None:
    return next((one for one in event.get("answers", []) if one["who"] == who), None)


def _holds_copy(event: Spec, who: str) -> bool:
    attends = who in event.get("attendees", []) and _owner_of(event) != who
    return attends and (who == OWNER or _answer_of(event, who) is not None)


def _recurrence(spec: Spec, day: dt.date, zone: str) -> dict[str, Any]:
    pattern: dict[str, Any] = {"type": "daily", "interval": 1}
    if spec.get("type") == "weekly":
        pattern = {
            "type": "weekly",
            "interval": 1,
            "daysOfWeek": spec["days"],
            "firstDayOfWeek": "monday",
        }
    return {
        "pattern": pattern,
        "range": {
            "type": "numbered",
            "startDate": day.isoformat(),
            "numberOfOccurrences": spec["count"],
            "recurrenceTimeZone": zone,
        },
    }


def _stamp(day: dt.date, clock: str, zone: str) -> dict[str, str]:
    return {"dateTime": f"{day}T{clock}:00", "timeZone": zone}


def _event_body(event: Spec, ctx: Context) -> dict[str, Any]:
    day = _day(event["day"], ctx.anchor)
    zone = event["time_zone"]
    body: dict[str, Any] = {
        "subject": event["subject"],
        "body": {"contentType": "text", "content": event["body"]},
        "start": _stamp(day, event["start"], zone),
        "end": _stamp(day, event["end"], zone),
        "isReminderOn": "reminder" in event,
        "categories": [TAG],
        "singleValueExtendedProperties": _marks(f"event:{event['id']}"),
    }
    if "location" in event:
        body["location"] = {"displayName": event["location"]}
    if "reminder" in event:
        body["reminderMinutesBeforeStart"] = event["reminder"]
    if "allow_new_time_proposals" in event:
        body["allowNewTimeProposals"] = event["allow_new_time_proposals"]
    if "attendees" in event:
        body["attendees"] = [{**ctx.address(who), "type": "required"} for who in event["attendees"]]
    if "recurrence" in event:
        body["recurrence"] = _recurrence(event["recurrence"], day, zone)
    return body


def _attachment(phase: str, event_key: str, attachment: Spec) -> list[Step]:
    path = f"/me/events/{{{event_key}}}/attachments"
    body = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": attachment["name"],
        "contentType": attachment["content_type"],
        "contentBytes": base64.b64encode(attachment["text"].encode("utf-8")).decode("ascii"),
    }
    return [
        Step(phase, "lookup", "GET", path, (("$select", "id,name"),), lookup="drive-children"),
        Step(phase, "create", "POST", path, body=body, key=f"file:{attachment['name']}"),
    ]


def _events(
    ctx: Context, owner: str, phase: str, path: str = "/me/events", items: list[Spec] | None = None
) -> list[Step]:
    pool = EVENTS if items is None else items
    events = [one for one in pool if one.get("phase", phase) == phase and _owner_of(one) == owner]
    if not events:
        return []
    found = [Step(phase, "lookup", "GET", path, TAGGED, lookup="tagged")]
    for event in events:
        key = f"event:{event['id']}"
        found.append(Step(phase, "create", "POST", path, body=_event_body(event, ctx), key=key))
        if "attachment" in event:
            found += _attachment(phase, key, SPEC["attachments"][event["attachment"]])
    return found


def _subject_params(subject: str) -> tuple[tuple[str, str], ...]:
    return (("$filter", f"startswith(subject,'{subject}')"), ("$select", "id,subject"))


def _received(owner: str, phase: str) -> list[Step]:
    mine = [e for e in EVENTS if e["phase"] == phase and _holds_copy(e, owner)]
    if not mine:
        return []
    found = [Step(phase, "lookup", "GET", "/me/events", TAGGED, lookup="tagged")]
    for event in mine:
        key, path = f"event:{event['id']}", f"/me/events/{{subject:{event['subject']}}}"
        found.append(
            Step(
                phase,
                "lookup",
                "GET",
                "/me/events",
                _subject_params(event["subject"]),
                lookup="subject",
            )
        )
        answer = _answer_of(event, owner)
        if answer is not None:
            body = {"comment": answer["comment"], "sendResponse": True}
            found.append(
                Step(phase, "create", "POST", f"{path}/{answer['response']}", body=body, key=key)
            )
        if answer is not None and answer["response"] == "decline":
            continue
        tagging = {"categories": [TAG], "singleValueExtendedProperties": _marks(key)}
        tag = key if answer is None else f"tag:{event['id']}"
        found.append(Step(phase, "create", "PATCH", path, body=tagging, key=tag))
    return found


def _occurrence(master: Spec, key: str, number: int, first: dt.date) -> tuple[dt.date, Step]:
    day = first + dt.timedelta(weeks=number - 1)
    window = (
        ("startDateTime", f"{day}T00:00:00Z"),
        ("endDateTime", f"{day + dt.timedelta(days=1)}T00:00:00Z"),
        ("$select", "id,subject"),
    )
    path = f"/me/events/{{{key}}}/instances"
    return day, Step(
        "cal-series",
        "lookup",
        "GET",
        path,
        window,
        key=f"occurrence-{number}",
        lookup="attachments",
    )


def _series(ctx: Context, owner: str) -> list[Step]:
    found: list[Step] = []
    for master in (e for e in EVENTS if e["phase"] == "cal-series" and _owner_of(e) == owner):
        subject, key = master["subject"], f"event:{master['id']}"
        move, cancel = master["edits"]["move"], master["edits"]["cancel"]
        zone, first = master["time_zone"], _day(master["day"], ctx.anchor)
        asked = _subject_params(subject)
        moved_day, find_moved = _occurrence(master, key, move["occurrence"], first)
        _, find_cancelled = _occurrence(master, key, cancel["occurrence"], first)
        later = moved_day + dt.timedelta(days=move["days"])
        moving = {
            "start": _stamp(later, master["start"], zone),
            "end": _stamp(later, master["end"], zone),
        }
        found += [
            Step("cal-series", "lookup", "GET", "/me/events", asked, lookup="subject"),
            Step(
                "cal-series",
                "lookup",
                "GET",
                "/me/events",
                asked,
                key="series-edited",
                lookup="attachments",
            ),
            *_events(ctx, owner, "cal-series"),
            find_moved,
            Step(
                "cal-series",
                "create",
                "PATCH",
                f"/me/events/{{attachment:occurrence-{move['occurrence']}:None}}",
                body=moving,
                key=f"subject:{subject}",
            ),
            find_cancelled,
            Step(
                "cal-series",
                "create",
                "POST",
                f"/me/events/{{attachment:occurrence-{cancel['occurrence']}:None}}/cancel",
                body={"comment": cancel["comment"]},
                key="attachment:series-edited:None",
            ),
        ]
    return found


def _hours(days: list[str], start: str, end: str) -> dict[str, Any]:
    return {
        "workingHours": {
            "daysOfWeek": days,
            "startTime": f"{start}:00.0000000",
            "endTime": f"{end}:00.0000000",
            "timeZone": {"name": SPEC["settings"]["time_zone"]},
        }
    }


def _settings(owner: str) -> list[Step]:
    return [
        Step(
            "cal-settings",
            "create",
            "PATCH",
            "/me/mailboxSettings",
            body=_hours(one["days"], one["start"], one["end"]),
            key=f"settings:{owner}",
        )
        for one in SPEC["settings"]["users"]
        if one["owner"] == owner
    ]


def _calendars(ctx: Context, owner: str, phase: str) -> list[Step]:
    calendars = [
        one
        for one in SPEC["calendars"]
        if one.get("phase", "cal-calendars") == phase and _owner_of(one) == owner
    ]
    if not calendars:
        return []
    params = (("$select", "id,name"),)
    found = [Step(phase, "lookup", "GET", "/me/calendars", params, lookup="drive-children")]
    for calendar in calendars:
        name = f"{TAG} {calendar['name']}"
        key = f"file:{name}"
        path = f"/me/calendars/{{{key}}}"
        found.append(Step(phase, "create", "POST", "/me/calendars", body={"name": name}, key=key))
        zone = SPEC["settings"]["time_zone"]
        events = [
            {"time_zone": zone, "owner": owner, "phase": phase, **one}
            for one in calendar.get("events", [])
        ]
        if "share" in calendar:
            first = events[0]["subject"]
            share = {**ctx.address(calendar["share"]["with"]), "role": calendar["share"]["role"]}
            found += [
                Step(
                    phase,
                    "lookup",
                    "GET",
                    f"{path}/events",
                    _subject_params(first),
                    lookup="subject",
                ),
                Step(
                    phase,
                    "create",
                    "POST",
                    f"{path}/calendarPermissions",
                    body=share,
                    key=f"subject:{first}",
                ),
            ]
        found += _events(ctx, owner, phase, f"{path}/events", events)
    return found


def _contact_body(contact: Spec, ctx: Context) -> dict[str, Any]:
    body: dict[str, Any] = {
        "displayName": contact["display_name"],
        "givenName": contact["given_name"],
        "surname": contact["surname"],
        "companyName": contact["company"],
        "jobTitle": contact["job_title"],
        "businessPhones": [contact["phone"]],
        "categories": [TAG],
        "singleValueExtendedProperties": _marks(f"contact:{contact['id']}"),
    }
    if "email" in contact:
        body["emailAddresses"] = [ctx.address(contact["email"])["emailAddress"]]
    return body


def _contacts(ctx: Context, owner: str) -> list[Step]:
    contacts = [one for one in SPEC["contacts"] if _owner_of(one) == owner]
    if not contacts:
        return []
    params = (("$select", "id,displayName"), ("$expand", KEY_EXPAND), ("$top", "100"))
    found = [Step("cal-contacts", "lookup", "GET", "/me/contacts", params, lookup="tagged")]
    for contact in contacts:
        body = _contact_body(contact, ctx)
        key = f"contact:{contact['id']}"
        found.append(Step("cal-contacts", "create", "POST", "/me/contacts", body=body, key=key))
    return found


def _group(ctx: Context, owner: str) -> list[Step]:
    if owner != OWNER:
        return []
    teams = (("$select", "id,displayName"),)
    key = f"cal-group:{TEAM_NAME}"
    path = f"/groups/{{{key}}}/events"
    found = [
        Step("cal-group", "lookup", "GET", "/me/joinedTeams", teams, lookup="named", learns="team"),
        Step(
            "cal-group",
            "lookup",
            "GET",
            path,
            (("$select", "id,subject"), ("$top", "100")),
            lookup="subject",
        ),
    ]
    for event in SPEC["group_events"]:
        day = _day(event["day"], ctx.anchor)
        body = {
            "subject": event["subject"],
            "body": {"contentType": "text", "content": event["body"]},
            "start": _stamp(day, event["start"], event["time_zone"]),
            "end": _stamp(day, event["end"], event["time_zone"]),
            "categories": [TAG],
        }
        found.append(
            Step("cal-group", "create", "POST", path, body=body, key=f"subject:{event['subject']}")
        )
    return found


def _named(phases: set[str]) -> bool:
    return not phases >= CORE_PHASES


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    return [
        *(_calendars(ctx, owner, "cal-calendars") if "cal-calendars" in phases else []),
        *(_events(ctx, owner, "cal-events") if "cal-events" in phases else []),
        *(_contacts(ctx, owner) if "cal-contacts" in phases else []),
        *(_series(ctx, owner) if "cal-series" in phases else []),
        *(_events(ctx, owner, "cal-bulk") if "cal-bulk" in phases else []),
        *(_settings(owner) if "cal-settings" in phases else []),
        *(_calendars(ctx, owner, "cal-shared") if "cal-shared" in phases else []),
        *(_group(ctx, owner) if "cal-group" in phases and _named(phases) else []),
        *(_events(ctx, owner, "cal-answers") if "cal-answers" in phases else []),
        *(_received(owner, "cal-answers") if "cal-answers" in phases and _named(phases) else []),
        *(_events(ctx, owner, "cal-invites") if "cal-invites" in phases else []),
        *(_received(owner, "cal-invites") if "cal-invites" in phases else []),
    ]


def _key(item: Mapping[str, Any]) -> str | None:
    for prop in item.get("singleValueExtendedProperties") or []:
        value = str(prop.get("value", ""))
        if prop.get("id", "").lower() == KEY_PROP.lower() and value.startswith(f"{TAG}:"):
            return value[len(TAG) + 1 :]
    return None


def cleanup(
    graph: Graph, ctx: Context, owner: str, phases: set[str]
) -> Iterator[tuple[str, str, Any]]:
    events = {
        f"event:{one['id']}"
        for one in EVENTS
        if one["phase"] in phases and (_owner_of(one) == owner or _holds_copy(one, owner))
    }
    if events:
        for item in graph.get_all("/me/events", dict(TAGGED)):
            if _key(item) in events:
                yield "DELETE", f"/me/events/{item['id']}", None
    names = {
        f"{TAG} {one['name']}"
        for one in SPEC["calendars"]
        if one.get("phase", "cal-calendars") in phases and _owner_of(one) == owner
    }
    if names:
        for item in graph.get_all("/me/calendars", {"$select": "id,name"}):
            if item.get("name") in names:
                yield "DELETE", f"/me/calendars/{item['id']}", None
    if "cal-contacts" in phases:
        wanted = {f"contact:{one['id']}" for one in SPEC["contacts"] if _owner_of(one) == owner}
        params = {"$select": "id,displayName", "$expand": KEY_EXPAND, "$top": "100"}
        for item in graph.get_all("/me/contacts", params):
            if _key(item) in wanted:
                yield "DELETE", f"/me/contacts/{item['id']}", None
    if "cal-settings" in phases and any(one["owner"] == owner for one in SPEC["settings"]["users"]):
        default = SPEC["settings"]["default"]
        yield (
            "PATCH",
            "/me/mailboxSettings",
            _hours(default["days"], default["start"], default["end"]),
        )
    if "cal-group" in phases and owner == OWNER:
        for team in graph.get_all("/me/joinedTeams", {"$select": "id,displayName"}):
            if team.get("displayName") != TEAM_NAME:
                continue
            graph.learn("team", str(team["id"]))
            subjects = {one["subject"] for one in SPEC["group_events"]}
            path = f"/groups/{team['id']}/events"
            for item in graph.get_all(path, {"$select": "id,subject", "$top": "100"}):
                if item.get("subject") in subjects:
                    yield "DELETE", f"{path}/{item['id']}", None


def sweep(graph: Graph, owner: str) -> Iterator[tuple[str, str]]:
    calendars = [
        one
        for one in graph.get_all("/me/calendars", {"$select": "id,name,canShare"})
        if str(one.get("name")).startswith(f"{TAG} ")
    ]
    for path in ("/me/events", *(f"/me/calendars/{one['id']}/events" for one in calendars)):
        events = list(graph.get_all(path, {"$select": "id,subject", "$top": "100"}))
        yield from (
            ("DELETE", f"{path}/{one['id']}") for one in events if CASE in str(one.get("subject"))
        )
    contacts = list(graph.get_all("/me/contacts", {"$select": "id,displayName", "$top": "100"}))
    yield from (
        ("DELETE", f"/me/contacts/{one['id']}")
        for one in contacts
        if CASE in str(one.get("displayName"))
    )
    for calendar in (one for one in calendars if owner == OWNER and one.get("canShare")):
        path = f"/me/calendars/{calendar['id']}/calendarPermissions"
        shares = list(graph.get_all(path, {}))
        yield from (("DELETE", f"{path}/{one['id']}") for one in shares if one.get("isRemovable"))
