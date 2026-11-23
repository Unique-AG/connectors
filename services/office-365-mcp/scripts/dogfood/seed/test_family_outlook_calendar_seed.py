"""Offline tests for the outlook-calendar seed family. The data is synthetic."""

import base64
import datetime as dt
import json
import re
import sys
from collections import Counter
from collections.abc import Iterator, Mapping
from itertools import count
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import seed
from families import outlook_calendar as family
from model import ConfigError, Context, Step
from test_seed import UPNS

ANCHOR = dt.date(2026, 10, 23)
PERSONAS = {1: "mia", 2: "anna", 3: "tom"}
FIRST_PASS = ("cal-calendars", "cal-events", "cal-contacts", "cal-series", "cal-bulk")
SECOND_PASS = ("cal-settings", "cal-shared", "cal-group")
ANSWERS = ("cal-answers", "cal-invites")
ACTIONS = ("accept", "decline", "tentativelyAccept", "cancel")


def context() -> Context:
    return Context(seed.load_corpus(seed.CORPUS_DIR), UPNS, ANCHOR, "extprops")


def plan(index: int, *phases: str) -> list[Step]:
    wanted = set(phases or family.PHASES)
    return [s for s in seed.build_steps(context(), index, wanted) if s.phase in family.PHASES]


class Mailbox:
    """One mailbox of a fake Graph: collections by path, answers like Graph answers."""

    def __init__(self, upn: str, bodiless: bool = False) -> None:
        self.upn = upn
        self.bodiless = bodiless
        self.lists: dict[str, list[dict[str, Any]]] = {
            "/me/joinedTeams": [{"id": "team-1", "displayName": "seed-v1 team"}]
        }
        self.sent: list[tuple[str, str]] = []
        self.ids = count(1)

    def graph(self) -> seed.Graph:
        return seed.Graph("synthetic-token", transport=httpx.MockTransport(self.handle))

    def find(self, path: str) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
        parent, _, last = path.rpartition("/")
        if parent == "/me/events" and re.fullmatch(r"id\d+-\d{4}-\d{2}-\d{2}", last):
            return [], {"id": last}
        return next(
            ((self.lists[parent], i) for i in self.lists.get(parent, []) if i["id"] == last), None
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.0")
        query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        if request.method != "GET":
            self.sent.append((request.method, path))
        if request.method == "GET" and path.endswith("/instances"):
            master = path.removesuffix("/instances")
            held = self.find(master)
            rows = [{"id": f"{held[1]['id']}-{query['startDateTime'][:10]}"}] if held else []
            return httpx.Response(200, json={"value": rows})
        if request.method == "GET":
            rows = list(self.lists.get(path, []))
            asked = re.search(r"startswith\(subject,'([^']*)'\)", query.get("$filter", ""))
            rows = [r for r in rows if not asked or r.get("subject", "").startswith(asked[1])]
            return httpx.Response(200, json={"value": rows})
        if request.method == "POST" and path.rpartition("/")[2] in ACTIONS:
            held = self.find(path.rpartition("/")[0])
            if held is None:
                return httpx.Response(404, json={"error": {"message": "gone"}})
            return httpx.Response(202, content=b"" if self.bodiless else b'{"id": "answered"}')
        if request.method == "POST":
            made = {"id": f"id{next(self.ids)}", **body}
            self.lists.setdefault(path, []).append(made)
            return httpx.Response(201, json=made)
        held = self.find(path)
        if held is None and request.method == "PATCH" and path == "/me/mailboxSettings":
            return httpx.Response(200, json={"id": "settings", **body})
        if held is None:
            return httpx.Response(404, json={"error": {"message": "gone"}})
        if request.method == "PATCH":
            held[1].update(body)
            return httpx.Response(200, json=held[1])
        held[0].remove(held[1])
        return httpx.Response(204)


def run(box: Mailbox, index: int, *phases: str) -> list[str]:
    done: list[str] = []
    steps = plan(index, *phases)
    _ = seed.apply(box.graph(), steps, context(), done.append)
    return [line.removeprefix("created ") for line in done]


def deliver(box: Mailbox, *subjects: str) -> None:
    box.lists.setdefault("/me/events", []).extend(
        {"id": f"copy-{n}", "subject": subject} for n, subject in enumerate(subjects)
    )


def test_a_full_run_leaves_out_the_steps_that_need_an_earlier_run_of_another_user_or_phase() -> (
    None
):
    everything = set(seed.PHASES)
    full = [s for i in PERSONAS for s in seed.build_steps(context(), i, everything)]
    assert not [s for s in full if s.phase == "cal-group"]
    assert not [s for s in full if s.phase == "cal-answers" and "{subject:" in s.path]
    assert [s.key for s in full if s.phase == "cal-answers" and s.kind == "create"] == [
        "event:c06",
        "event:c07",
    ]
    assert [s.key for s in plan(2, "cal-answers") if "{subject:" in s.path]
    assert plan(1, "cal-group")


def test_the_family_adds_ten_phases_to_the_seed() -> None:
    assert len(family.PHASES) == 10
    assert set(family.PHASES) <= set(seed.PHASES)
    assert len(set(family.PHASES)) == 10


def test_each_persona_creates_what_the_corpus_gives_it() -> None:
    created = {
        index: Counter(s.phase for s in plan(index) if s.kind == "create") for index in PERSONAS
    }
    assert created[1] == {
        "cal-calendars": 2,
        "cal-events": 9,
        "cal-contacts": 2,
        "cal-series": 3,
        "cal-bulk": 40,
        "cal-group": 4,
        "cal-answers": 2,
        "cal-invites": 12,
    }
    assert created[2] == {
        "cal-events": 2,
        "cal-settings": 1,
        "cal-shared": 5,
        "cal-answers": 4,
        "cal-invites": 9,
    }
    assert created[3] == {
        "cal-events": 1,
        "cal-settings": 1,
        "cal-shared": 4,
        "cal-answers": 1,
        "cal-invites": 2,
    }


def test_a_step_names_only_keys_that_an_earlier_step_makes() -> None:
    for index in PERSONAS:
        made: set[str] = set()
        for step in plan(index):
            assert set(re.findall(r"\{([^}]+)\}", step.path)) <= made, step.path
            made |= {step.key} if step.key else set()
            asked = re.search(
                r"startswith\(subject,'([^']*)'\)", dict(step.params).get("$filter", "")
            )
            made |= {f"subject:{asked[1]}"} if step.lookup == "subject" and asked else set()
            made |= {f"attachment:{step.key}:None"} if step.lookup == "attachments" else set()
            made |= {f"{step.phase}:seed-v1 team"} if step.lookup == "named" else set()


def test_a_day_word_is_the_first_such_day_from_tomorrow() -> None:
    friday = dt.date(2026, 10, 23)
    assert friday.weekday() == 4
    assert family._day("nextMonday", friday) == dt.date(2026, 10, 26)  # pyright: ignore[reportPrivateUsage]
    assert family._day("nextFriday", friday) == dt.date(2026, 10, 30)  # pyright: ignore[reportPrivateUsage]
    assert family._day("nextWednesday+2", friday) == dt.date(2026, 10, 30)  # pyright: ignore[reportPrivateUsage]
    assert family._day("nextMonday-7", friday) == dt.date(2026, 10, 19)  # pyright: ignore[reportPrivateUsage]
    assert family._day(1, friday) == dt.date(2026, 10, 24)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(ConfigError, match="not a day number"):
        _ = family._day("someday", friday)  # pyright: ignore[reportPrivateUsage]


def test_the_corpus_days_agree_with_the_recorder_words() -> None:
    body = {
        s.key: s.body for s in plan(1, "cal-events", "cal-series", "cal-bulk") if s.kind == "create"
    }
    assert body["event:c11"]["start"]["dateTime"] == "2026-10-26T09:00:00"
    assert body["event:c09"]["start"]["dateTime"] == "2026-10-27T10:00:00"
    assert body["event:c08"]["start"]["dateTime"] == "2026-10-19T09:00:00"
    assert body["event:bulk-01"]["start"]["dateTime"] == "2026-11-09T08:00:00"
    assert body["event:bulk-40"]["start"]["dateTime"] == "2026-11-13T16:45:00"
    assert body["event:bulk-40"]["end"]["dateTime"] == "2026-11-13T17:05:00"
    assert body["event:c08"]["recurrence"]["pattern"]["daysOfWeek"] == ["monday"]
    assert body["event:c08"]["recurrence"]["range"]["numberOfOccurrences"] == 6


def test_every_item_is_tagged_and_none_is_swept_before_a_case() -> None:
    for index in PERSONAS:
        for step in (one for one in plan(index) if one.kind == "create"):
            assert "case-" not in repr(step.body)
            tagged = step.method == "POST" and step.path.endswith(("/events", "/contacts"))
            if step.path == "/me/calendars":
                assert step.body["name"].startswith("seed-v1 ")
            elif tagged and not step.path.startswith("/groups/"):
                assert step.body["categories"] == ["seed-v1"]
                assert (
                    step.body["singleValueExtendedProperties"][0]["value"] == f"seed-v1:{step.key}"
                )
            elif tagged:
                assert step.body["categories"] == ["seed-v1"]


def test_an_invitation_goes_to_a_persona_only_and_a_share_names_mia() -> None:
    steps = [s for index in PERSONAS for s in plan(index)]
    seed.check_recipients(steps, UPNS)
    people = Counter(
        a["emailAddress"]["address"]
        for s in steps
        for a in (s.body or {}).get("attendees", [])
        if isinstance(s.body, Mapping)
    )
    assert set(people) == {UPNS[0], UPNS[1], UPNS[2]}
    shares = [s for s in steps if s.path.endswith("/calendarPermissions")]
    assert [(s.body["emailAddress"]["address"], s.body["role"]) for s in shares] == [
        (UPNS[0], "write"),
        (UPNS[0], "read"),
    ]


def test_every_seed_text_reaches_the_corpus_manifest() -> None:
    strings = set(seed.corpus_manifest(context())["strings"])
    spec = family.SPEC
    wanted = [e["subject"] for e in family.EVENTS] + [e["body"] for e in family.EVENTS]
    wanted += [c["display_name"] for c in spec["contacts"]] + [
        c["company"] for c in spec["contacts"]
    ]
    wanted += [f"seed-v1 {c['name']}" for c in spec["calendars"]]
    wanted += [e["subject"] for c in spec["calendars"] for e in c.get("events", [])]
    wanted += [e["subject"] for e in spec["group_events"]]
    wanted += [a["comment"] for e in family.EVENTS for a in e.get("answers", [])]
    wanted += [e["edits"]["cancel"]["comment"] for e in family.EVENTS if "edits" in e]
    wanted += [base64.b64encode(a["text"].encode()).decode() for a in spec["attachments"].values()]
    assert set(wanted) <= strings
    assert {"Overlap", "Slot", "(UTC+05:30) Chennai, Kolkata, Mumbai, New Delhi"} <= strings


def test_the_family_names_each_subject_once_and_each_id_once() -> None:
    inside = [e for c in family.SPEC["calendars"] for e in c.get("events", [])]
    ids = [e["id"] for e in [*family.EVENTS, *inside, *family.SPEC["group_events"]]]
    assert len(ids) == len(set(ids))
    subjects = [e["subject"] for e in family.EVENTS if e["phase"] != "cal-bulk"]
    assert len(subjects) == len(set(subjects))
    found = [e["subject"] for e in family.EVENTS if e["phase"] in ("cal-answers", "cal-invites")]
    assert not [s for s in found if any(o != s and o.startswith(s) for o in subjects)]


def test_apply_twice_sends_nothing_but_the_steps_that_are_harmless_to_repeat() -> None:
    boxes = {index: Mailbox(UPNS[index - 1]) for index in PERSONAS}
    for index in PERSONAS:
        _ = run(boxes[index], index, *FIRST_PASS, *SECOND_PASS)
    deliver(boxes[2], "Design workshop", "Content review")
    deliver(boxes[3], "Design workshop")
    for index in (2, 3):
        _ = run(boxes[index], index, "cal-answers")
    for index in (2, 3):
        _ = run(boxes[index], index, "cal-invites")
    deliver(boxes[1], *(e["subject"] for e in family.EVENTS if e["phase"] == "cal-invites"))
    _ = run(boxes[1], 1, "cal-answers", "cal-invites")
    again = {i: run(boxes[i], i, *FIRST_PASS, *SECOND_PASS, *ANSWERS) for i in PERSONAS}
    assert again == {
        1: ["tag:t-a01"],
        2: ["settings:anna", "tag:c06", "tag:c07"],
        3: ["settings:tom", "event:c06"],
    }


def test_the_edits_of_the_series_are_made_once_and_not_repeated() -> None:
    box = Mailbox(UPNS[0])
    _ = run(box, 1, "cal-series")
    assert [call for call in box.sent if call[0] != "POST" or "cancel" in call[1]] == [
        ("PATCH", "/me/events/id1-2026-11-02"),
        ("POST", "/me/events/id1-2026-11-16/cancel"),
    ]
    box.sent.clear()
    assert run(box, 1, "cal-series") == []
    assert box.sent == []


def test_the_permission_is_made_once_and_before_the_events() -> None:
    box = Mailbox(UPNS[1])
    _ = run(box, 2, "cal-shared")
    assert [call[1].rpartition("/")[2] for call in box.sent] == [
        "calendars",
        "calendarPermissions",
        "events",
        "events",
        "events",
    ]
    box.sent.clear()
    assert run(box, 2, "cal-shared") == []
    assert box.sent == []


def test_the_group_events_are_made_for_the_team_of_the_seed_only() -> None:
    box = Mailbox(UPNS[0])
    box.lists["/me/joinedTeams"].append({"id": "team-2", "displayName": "Other team"})
    assert run(box, 1, "cal-group") == [
        f"subject:{e['subject']}" for e in family.SPEC["group_events"]
    ]
    assert set(box.lists) >= {"/groups/team-1/events"}
    assert "/groups/team-2/events" not in box.lists
    box.sent.clear()
    assert run(box, 1, "cal-group") == []


def test_an_answer_without_a_delivered_invitation_stops_and_names_the_earlier_phase() -> None:
    with pytest.raises(ConfigError, match="earlier phase"):
        _ = run(Mailbox(UPNS[1]), 2, "cal-answers")


def test_a_decline_is_not_tagged_because_the_copy_leaves_the_calendar() -> None:
    tom = plan(3, "cal-answers")
    assert [(s.method, s.path.rpartition("/")[2]) for s in tom if s.kind == "create"] == [
        ("POST", "decline")
    ]
    anna = [
        (s.method, s.path.rpartition("/")[2]) for s in plan(2, "cal-answers") if s.kind == "create"
    ]
    assert anna == [
        ("POST", "accept"),
        ("PATCH", "{subject:Design workshop}"),
        ("POST", "tentativelyAccept"),
        ("PATCH", "{subject:Content review}"),
    ]
    assert [s.body["sendResponse"] for s in tom if s.kind == "create"] == [True]


def test_mia_accepts_one_invitation_and_tags_every_copy() -> None:
    made = [
        (s.method, s.key)
        for s in plan(1, "cal-invites")
        if s.method != "POST" or "accept" in s.path
    ]
    tagged = [key for method, key in made if method == "PATCH"]
    assert len(tagged) == 11
    assert ("POST", "event:t-a01") in made
    assert "tag:t-a01" in tagged
    proposals = {
        e["subject"]: e["allow_new_time_proposals"]
        for e in family.EVENTS
        if "allow_new_time_proposals" in e
    }
    assert proposals == {"Workshop prep": True, "Fixed slot": False}


def test_a_shared_calendar_is_named_for_its_owner_and_holds_events() -> None:
    anna = [(s.key, s.path) for s in plan(2, "cal-shared") if s.kind == "create"]
    assert anna[0] == ("file:seed-v1 Anna Planning", "/me/calendars")
    assert {p for _, p in anna[2:]} == {"/me/calendars/{file:seed-v1 Anna Planning}/events"}
    assert [k for k, _ in anna[2:]] == ["event:s01", "event:s02", "event:s03"]
    assert [s.key for s in plan(1, "cal-shared")] == []


def test_the_working_hours_differ_between_the_two_colleagues() -> None:
    hours = {index: plan(index, "cal-settings")[0].body["workingHours"] for index in (2, 3)}
    assert hours[2]["daysOfWeek"] == ["monday", "tuesday", "wednesday", "thursday"]
    assert hours[3]["daysOfWeek"][-1] == "friday"
    assert (hours[2]["endTime"], hours[3]["startTime"]) == ("16:00:00.0000000", "07:00:00.0000000")
    assert plan(1, "cal-settings") == []


class Listing:
    def __init__(self, held: Mapping[str, list[dict[str, Any]]]) -> None:
        self.held = held
        self.learned: list[tuple[str, str]] = []

    def get_all(self, path: str, params: Mapping[str, str]) -> Iterator[dict[str, Any]]:
        yield from self.held.get(path, [])

    def learn(self, kind: str, identifier: str) -> None:
        self.learned.append((kind, identifier))


def keyed(identifier: str, key: str | None, **fields: Any) -> dict[str, Any]:
    marks = [] if key is None else [{**family._marks(key)[0]}]  # pyright: ignore[reportPrivateUsage]
    return {"id": identifier, "singleValueExtendedProperties": marks, **fields}


def test_cleanup_deletes_only_the_items_of_the_asked_phases_and_owner() -> None:
    graph = Listing(
        {
            "/me/events": [
                keyed("e1", "event:c06"),
                keyed("e2", "event:c08"),
                keyed("e3", "event:a11"),
                keyed("e4", None, subject="Design workshop"),
                keyed("e5", "event:zz9"),
            ],
            "/me/calendars": [
                {"id": "k1", "name": "seed-v1 Shared calendar"},
                {"id": "k2", "name": "Calendar"},
                {"id": "k3", "name": "seed-v1 Anna Planning"},
            ],
            "/me/contacts": [keyed("c1", "contact:k01"), keyed("c2", "contact:other")],
        }
    )
    got = list(
        family.cleanup(graph, context(), "mia", {"cal-answers", "cal-calendars", "cal-contacts"})
    )  # pyright: ignore[reportArgumentType]
    assert got == [
        ("DELETE", "/me/events/e1", None),
        ("DELETE", "/me/calendars/k1", None),
        ("DELETE", "/me/contacts/c1", None),
    ]
    anna = list(family.cleanup(graph, context(), "anna", {"cal-events", "cal-shared"}))  # pyright: ignore[reportArgumentType]
    assert anna == [("DELETE", "/me/events/e3", None), ("DELETE", "/me/calendars/k3", None)]


def test_cleanup_of_the_answers_removes_the_copy_that_an_attendee_tagged() -> None:
    graph = Listing({"/me/events": [keyed("e1", "event:c06"), keyed("e2", "event:c08")]})
    assert list(family.cleanup(graph, context(), "anna", {"cal-answers"})) == [  # pyright: ignore[reportArgumentType]
        ("DELETE", "/me/events/e1", None)
    ]
    assert list(family.cleanup(graph, context(), "tom", {"cal-answers"})) == [  # pyright: ignore[reportArgumentType]
        ("DELETE", "/me/events/e1", None)
    ]


def test_cleanup_writes_the_default_hours_back_and_asks_for_no_other_settings() -> None:
    graph = Listing({})
    anna = list(family.cleanup(graph, context(), "anna", {"cal-settings"}))  # pyright: ignore[reportArgumentType]
    hours = anna[0][2]["workingHours"]
    assert anna[0][:2] == ("PATCH", "/me/mailboxSettings")
    assert hours["daysOfWeek"][-1] == "friday"
    assert (hours["startTime"], hours["endTime"]) == ("08:00:00.0000000", "17:00:00.0000000")
    assert list(family.cleanup(graph, context(), "mia", {"cal-settings"})) == []  # pyright: ignore[reportArgumentType]


def test_cleanup_of_the_group_events_learns_the_team_and_deletes_the_four() -> None:
    graph = Listing(
        {
            "/me/joinedTeams": [
                {"id": "t9", "displayName": "Other team"},
                {"id": "t1", "displayName": "seed-v1 team"},
            ],
            "/groups/t1/events": [
                {"id": "g1", "subject": "Retro"},
                {"id": "g2", "subject": "Someone else's meeting"},
            ],
        }
    )
    got = list(family.cleanup(graph, context(), "mia", {"cal-group"}))  # pyright: ignore[reportArgumentType]
    assert got == [("DELETE", "/groups/t1/events/g1", None)]
    assert graph.learned == [("team", "t1")]
    assert list(family.cleanup(graph, context(), "anna", {"cal-group"})) == []  # pyright: ignore[reportArgumentType]


def test_the_sweep_names_only_case_items_and_the_shares_of_a_calendar_of_the_owner() -> None:
    held = {
        "/me/calendars": [
            {"id": "c1", "name": "Calendar", "canShare": True},
            {"id": "c2", "name": "seed-v1 Shared calendar", "canShare": True},
            {"id": "c3", "name": "seed-v1 Anna Planning", "canShare": False},
        ],
        "/me/events": [
            {"id": "e1", "subject": "Daily standup"},
            {"id": "e2", "subject": "seed-v1 case-outlook_create_event-simple"},
        ],
        "/me/calendars/c2/events": [{"id": "e3", "subject": "seed-v1 case-x"}],
        "/me/calendars/c3/events": [{"id": "e4", "subject": "seed-v1 case-on-behalf"}],
        "/me/contacts": [
            {"id": "k1", "displayName": "Lena Fischer"},
            {"id": "k2", "displayName": "seed-v1 case-outlook_create_contact-person"},
        ],
        "/me/calendars/c2/calendarPermissions": [
            {"id": "p1", "isRemovable": False},
            {"id": "p2", "isRemovable": True},
        ],
        "/me/calendars/c3/calendarPermissions": [{"id": "p3", "isRemovable": True}],
    }
    mia = list(family.sweep(Listing(held), "mia"))  # pyright: ignore[reportArgumentType]
    assert mia == [
        ("DELETE", "/me/events/e2"),
        ("DELETE", "/me/calendars/c2/events/e3"),
        ("DELETE", "/me/calendars/c3/events/e4"),
        ("DELETE", "/me/contacts/k2"),
        ("DELETE", "/me/calendars/c2/calendarPermissions/p2"),
    ]
    anna = list(family.sweep(Listing(held), "anna"))  # pyright: ignore[reportArgumentType]
    assert ("DELETE", "/me/calendars/c2/calendarPermissions/p2") not in anna
    assert not [call for call in anna if "calendarPermissions" in call[1]]


def test_cleanup_cases_deletes_what_the_sweep_names(monkeypatch: pytest.MonkeyPatch) -> None:
    box = Mailbox(UPNS[0])
    box.lists["/me/events"] = [{"id": "e2", "subject": "seed-v1 case-x"}]
    box.lists["/me/calendars"] = []
    monkeypatch.setattr(seed, "FAMILIES", (family,))
    out: list[str] = []
    deleted = seed.cleanup_cases(box.graph(), context(), 1, True, out.append)
    assert (deleted, out) == (1, ["would delete DELETE /me/events/e2"])
    assert box.sent == []


def test_an_answer_that_graph_sends_with_no_body_is_accepted_by_apply() -> None:
    box = Mailbox(UPNS[1], bodiless=True)
    deliver(box, "Design workshop", "Content review")
    assert run(box, 2, "cal-answers")
