import base64
import datetime as dt
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from model import Context, Step

if TYPE_CHECKING:
    from seed import Graph

TAG = "seed-v1"
CASE = f"{TAG} case-"
KEY_PROP = "String {8c0e3b2a-6f1d-4d6e-9a57-2f3c5b7e9d10} Name SeedKey"
KEY_EXPAND = f"singleValueExtendedProperties($filter=id eq '{KEY_PROP}')"
PHASES: tuple[str, ...] = ("cal-calendars", "cal-events", "cal-contacts", "cal-invites")
OWNER = "mia"
CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "outlook-calendar.yaml"
SPEC: Mapping[str, Any] = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
TAGGED = (("$select", "id,subject"), ("$expand", KEY_EXPAND), ("$top", "100"))

type Spec = Mapping[str, Any]


def _marks(key: str) -> list[dict[str, str]]:
    return [{"id": KEY_PROP, "value": f"{TAG}:{key}"}]


def _owned(items: list[Spec], owner: str) -> list[Spec]:
    return [one for one in items if one.get("owner", OWNER) == owner]


def _event_body(event: Spec, ctx: Context) -> dict[str, Any]:
    day = ctx.anchor + dt.timedelta(days=event["day"])
    zone = event["time_zone"]
    body: dict[str, Any] = {
        "subject": event["subject"],
        "body": {"contentType": "text", "content": event["body"]},
        "start": {"dateTime": f"{day}T{event['start']}:00", "timeZone": zone},
        "end": {"dateTime": f"{day}T{event['end']}:00", "timeZone": zone},
        "isReminderOn": "reminder" in event,
        "categories": [TAG],
        "singleValueExtendedProperties": _marks(f"event:{event['id']}"),
    }
    if "location" in event:
        body["location"] = {"displayName": event["location"]}
    if "reminder" in event:
        body["reminderMinutesBeforeStart"] = event["reminder"]
    if "attendees" in event:
        body["attendees"] = [{**ctx.address(who), "type": "required"} for who in event["attendees"]]
    if "recurrence" in event:
        body["recurrence"] = {
            "pattern": {"type": "daily", "interval": 1},
            "range": {
                "type": "numbered",
                "startDate": day.isoformat(),
                "numberOfOccurrences": event["recurrence"]["count"],
                "recurrenceTimeZone": zone,
            },
        }
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


def _events(ctx: Context, owner: str, phase: str) -> list[Step]:
    events = _owned([e for e in SPEC["events"] if e["phase"] == phase], owner)
    if not events:
        return []
    found = [Step(phase, "lookup", "GET", "/me/events", TAGGED, lookup="tagged")]
    for event in events:
        key = f"event:{event['id']}"
        body = _event_body(event, ctx)
        found.append(Step(phase, "create", "POST", "/me/events", body=body, key=key))
        if "attachment" in event:
            found += _attachment(phase, key, SPEC["attachments"][event["attachment"]])
    return found


def _invitations(owner: str) -> list[Step]:
    received = [
        e
        for e in SPEC["events"]
        if e["phase"] == "cal-invites"
        and owner in e.get("attendees", [])
        and e.get("owner") != owner
    ]
    if not received:
        return []
    found = [Step("cal-invites", "lookup", "GET", "/me/events", TAGGED, lookup="tagged")]
    for event in received:
        params = (
            ("$filter", f"startswith(subject,'{event['subject']}')"),
            ("$select", "id,subject"),
        )
        body = {
            "categories": [TAG],
            "singleValueExtendedProperties": _marks(f"event:{event['id']}"),
        }
        path = f"/me/events/{{subject:{event['subject']}}}"
        found += [
            Step("cal-invites", "lookup", "GET", "/me/events", params, lookup="subject"),
            Step("cal-invites", "create", "PATCH", path, body=body, key=f"event:{event['id']}"),
        ]
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
    contacts = _owned(SPEC["contacts"], owner)
    if not contacts:
        return []
    params = (("$select", "id,displayName"), ("$expand", KEY_EXPAND), ("$top", "100"))
    found = [Step("cal-contacts", "lookup", "GET", "/me/contacts", params, lookup="tagged")]
    for contact in contacts:
        body = _contact_body(contact, ctx)
        key = f"contact:{contact['id']}"
        found.append(Step("cal-contacts", "create", "POST", "/me/contacts", body=body, key=key))
    return found


def _calendars(owner: str) -> list[Step]:
    calendars = _owned(SPEC["calendars"], owner)
    if not calendars:
        return []
    params = (("$select", "id,name"),)
    found = [
        Step("cal-calendars", "lookup", "GET", "/me/calendars", params, lookup="drive-children")
    ]
    for calendar in calendars:
        name = f"{TAG} {calendar['name']}"
        body = {"name": name}
        found.append(
            Step("cal-calendars", "create", "POST", "/me/calendars", body=body, key=f"file:{name}")
        )
    return found


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    return [
        *(_calendars(owner) if "cal-calendars" in phases else []),
        *(_events(ctx, owner, "cal-events") if "cal-events" in phases else []),
        *(_contacts(ctx, owner) if "cal-contacts" in phases else []),
        *(_events(ctx, owner, "cal-invites") if "cal-invites" in phases else []),
        *(_invitations(owner) if "cal-invites" in phases else []),
    ]


def sweep(graph: Graph, owner: str) -> Iterator[tuple[str, str]]:
    calendars = [
        one
        for one in graph.get_all("/me/calendars", {"$select": "id,name"})
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
    for calendar in calendars:
        path = f"/me/calendars/{calendar['id']}/calendarPermissions"
        shares = list(graph.get_all(path, {}))
        yield from (("DELETE", f"{path}/{one['id']}") for one in shares if one.get("isRemovable"))
