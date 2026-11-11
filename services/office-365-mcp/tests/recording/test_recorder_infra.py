# pyright: reportPrivateUsage=false
"""The plug points that the family writers use: the extra addresses, the inviting tools, the shared
mailbox and calendars, the chat of a case, the monitor of a copy, a short scheduled reply, the
argument generator, the day tokens, the generated bodies and the host entries of `serve()`."""

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from typing import cast

import httpx
import pytest
import respx

from tests.graph_fixtures import generate, response, serve
from tests.integration.test_scenarios import (
    Json,
    Replay,
    day_named,
    generated,
    mapping,
    resolved,
    same,
)
from tests.recording import guard as guard_module
from tests.recording import scrub as scrub_module
from tests.recording.conftest import body_of
from tests.recording.families import load, merge
from tests.recording.guard import GRAPH_HOST, Guard, Refused
from tests.recording.lint import lint_files
from tests.recording.record import (
    Plan,
    check,
    describe,
    extras_from_environment,
    guard_for,
    persona_values,
    planned_values,
    resolve,
    synthetic_extra,
    with_personas,
)
from tests.recording.scrub import (
    LARGE_BODY,
    Hop,
    Identities,
    Recording,
    files_of,
    load_corpus,
    scrub,
)
from tests.recording.stand_in import DOMAIN, UPN, UPNS, USER_ID

ROOM = f"room@{DOMAIN}"
GUEST = "guest@external.test"
SHARED = f"shared@{DOMAIN}"
DIRECTORY = f"directory@{DOMAIN}"
EXTRAS = {
    "SEED_ROOM_UPN": ROOM,
    "SEED_GUEST_UPN": GUEST,
    "SEED_SHARED_UPN": SHARED,
    "SEED_DIRECTORY_UPN": DIRECTORY,
}
MAIL_TOOL, OTHER_TOOL = "outlook_list_mail", "outlook_read_event"
GRAPH = f"https://{GRAPH_HOST}/v1.0"
ALLOWED = frozenset(UPNS)
JSON_HEAD = (("content-type", "application/json"),)


def asked_of(method: str, host: str, path: str, sent: object = None) -> Json:
    return {"method": method, "host": host, "path": path, "query": {}, "headers": {}, "json": sent}


def uses(**names: set[str]) -> dict[str, frozenset[str]]:
    return {f"SEED_{name}_UPN": frozenset(tools) for name, tools in names.items()}


def patched(monkeypatch: pytest.MonkeyPatch, **fields: object) -> None:
    monkeypatch.setattr(guard_module, "FAMILIES", replace(load(), **fields))


def guard(**fields: object) -> Guard:
    made = Guard(UPN, ALLOWED, True, 40, me_id=USER_ID, **fields)  # pyright: ignore[reportArgumentType]
    made.seen_seed.add("AAMkSEED")
    return made


def request(method: str, path: str, body: object = None) -> httpx.Request:
    content = json.dumps(body).encode() if body is not None else b""
    return httpx.Request(method, f"{GRAPH}{path}", content=content)


def family(**attributes: object) -> ModuleType:
    module = ModuleType("synthetic")
    for name, value in attributes.items():
        setattr(module, name, value)
    return module


class TestFamilyPlugIns:
    def test_the_uses_of_an_address_and_the_inviters_merge_across_families(self) -> None:
        merged = merge(
            [
                family(READ_TOOLS=frozenset({"a"}), ADDRESSES=uses(ROOM={"a"})),
                family(
                    WRITE_TOOLS={"b": ()},
                    INVITERS=frozenset({"b"}),
                    ADDRESSES=uses(ROOM={"b"}) | uses(GUEST={"b"}),
                ),
            ]
        )
        assert merged.address_uses == uses(ROOM={"a", "b"}) | uses(GUEST={"b"})
        assert merged.inviters == {"b"}

    @pytest.mark.parametrize(
        "modules",
        [
            [family(READ_TOOLS=frozenset({"a"}), ADDRESSES={"ROOM": frozenset({"a"})})],
            [family(READ_TOOLS=frozenset({"a"}), ADDRESSES=uses(ROOM={"zz"}))],
            [family(READ_TOOLS=frozenset({"a"}), INVITERS=frozenset({"a"}))],
        ],
    )
    def test_a_name_that_is_no_address_variable_and_a_tool_that_no_family_claims_stop_the_import(
        self, modules: list[ModuleType]
    ) -> None:
        with pytest.raises(ValueError, match="ADDRESSES|INVITERS"):
            _ = merge(modules)

    def test_the_families_name_the_tools_that_the_plan_gives_the_extra_addresses(self) -> None:
        merged = load()
        assert {"outlook_find_recipient", "outlook_check_availability"} <= merged.address_uses[
            "SEED_DIRECTORY_UPN"
        ]
        assert "outlook_create_event" not in merged.address_uses["SEED_GUEST_UPN"]
        assert "teams_create_meeting" in merged.address_uses["SEED_GUEST_UPN"]
        assert "outlook_create_event" in merged.address_uses["SEED_ROOM_UPN"]
        assert {"outlook_list_mail", "outlook_move_mail"} <= merged.address_uses["SEED_SHARED_UPN"]
        assert "teams_send_chat_message" not in merged.address_uses["SEED_SHARED_UPN"]
        assert merged.inviters == {
            "outlook_create_event",
            "outlook_update_event",
            "outlook_cancel_event",
            "outlook_delete_event",
            "teams_create_meeting",
            "teams_update_meeting",
        }


class TestExtraAddresses:
    def test_an_extra_address_is_open_for_the_tools_that_the_family_names_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patched(monkeypatch, address_uses=uses(DIRECTORY={"outlook_find_recipient"}))
        made = guard(extras=EXTRAS)
        assert made.refuses_call("outlook_find_recipient", {"query": DIRECTORY}) is None
        refused = made.refuses_call("outlook_list_mail", {"query": DIRECTORY})
        assert refused is not None and "that is not a test user" in refused
        assert guard().refuses_call("outlook_find_recipient", {"query": DIRECTORY}) is not None
        other = made.refuses_call("outlook_find_recipient", {"query": GUEST})
        assert other is not None and "that is not a test user" in other

    def test_the_request_of_a_tool_that_may_use_the_address_goes_out_and_another_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patched(monkeypatch, address_uses=uses(DIRECTORY={"outlook_get_mail_tips"}))
        made = guard(extras=EXTRAS)
        ask = request("POST", "/me/getMailTips", {"EmailAddresses": [DIRECTORY]})
        assert made.refuses_request(ask, "outlook_get_mail_tips") is None
        assert "body holds" in str(made.refuses_request(ask, "outlook_list_mail"))

    def test_the_guest_may_come_to_a_meeting_but_not_to_an_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patched(
            monkeypatch,
            address_uses=uses(GUEST={"teams_create_meeting"}),
            inviters=frozenset({"teams_create_meeting", "outlook_create_event"}),
        )
        made = guard(extras=EXTRAS)
        assert made.refuses_call("teams_create_meeting", {"attendees": [GUEST, UPNS[1]]}) is None
        assert made.refuses_call("outlook_create_event", {"attendees": [GUEST]}) is not None

    def test_the_room_is_the_one_room_address_that_an_event_may_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patched(
            monkeypatch,
            address_uses=uses(ROOM={"outlook_create_event"}),
            inviters=frozenset({"outlook_create_event"}),
        )
        made = guard(extras=EXTRAS)
        assert made.refuses_call("outlook_create_event", {"room_addresses": [ROOM]}) is None
        elsewhere = {"room_addresses": [f"other-room@{DOMAIN}"]}
        assert made.refuses_call("outlook_create_event", elsewhere) is not None
        assert guard().refuses_call("outlook_create_event", {"room_addresses": [ROOM]}) is not None


class TestInvitingTools:
    @pytest.fixture(autouse=True)
    def inviters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        patched(monkeypatch, inviters=frozenset({"outlook_create_event"}))

    def test_a_persona_or_a_persona_id_is_a_guest_of_an_inviting_tool(self) -> None:
        made = guard(people=frozenset({"GUID-OF-ANNA"}))
        ok = {"subject": "s", "attendees": [UPNS[1], UPNS[2]], "online_meeting": True}
        assert made.refuses_call("outlook_create_event", ok) is None
        by_id = {"attendees": [{"user_id": "GUID-OF-ANNA", "name": "Anna"}]}
        assert made.refuses_call("outlook_create_event", by_id) is None

    @pytest.mark.parametrize(
        "args",
        [
            {"attendees": [f"ceo@{DOMAIN}"]},
            {"attendees": ["Anna"]},
            {"attendees": [{"user_id": "GUID-OF-SOMEONE", "name": "Anna"}]},
            {"optional_attendees": ["x@evil.com"]},
        ],
    )
    def test_anyone_else_is_refused(self, args: Mapping[str, object]) -> None:
        refused = guard(people=frozenset({"GUID-OF-ANNA"})).refuses_call(
            "outlook_create_event", args
        )
        assert refused is not None

    def test_a_tool_that_is_no_inviter_still_may_not_invite(self) -> None:
        refused = guard().refuses_call("outlook_forward_event", {"attendees": [UPNS[1]]})
        assert refused is not None and "would invite" in refused

    def test_a_read_tool_may_name_a_person_by_name(self) -> None:
        assert guard().refuses_call("outlook_check_availability", {"attendees": ["Anna"]}) is None


class TestSharedMailbox:
    @pytest.fixture(autouse=True)
    def shared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        patched(monkeypatch, address_uses=uses(SHARED={MAIL_TOOL, "outlook_mark_mail"}))

    def test_the_path_of_the_shared_mailbox_is_open_to_the_mail_tools_only(self) -> None:
        made = guard(extras=EXTRAS)
        read = request("GET", f"/users/{SHARED}/mailFolders/inbox/messages")
        assert made.refuses_request(read, MAIL_TOOL) is None
        assert made.refuses_request(read, OTHER_TOOL) is not None
        assert guard().refuses_request(read, MAIL_TOOL) is not None
        anna = request("GET", f"/users/{UPNS[1]}/mailFolders/inbox/messages")
        assert made.refuses_request(anna, MAIL_TOOL) is not None

    def test_a_mailbox_argument_may_name_the_shared_mailbox_for_those_tools(self) -> None:
        made = guard(extras=EXTRAS)
        assert made.refuses_call(MAIL_TOOL, {"mailbox": SHARED.upper()}) is None
        assert made.refuses_call(OTHER_TOOL, {"mailbox": SHARED}) is not None
        assert made.refuses_call(MAIL_TOOL, {"mailbox": UPNS[1]}) is not None

    def test_a_write_into_the_shared_mailbox_names_an_item_that_the_run_read_as_seed_data(
        self,
    ) -> None:
        made = guard(extras=EXTRAS)
        mark = request("PATCH", f"/users/{SHARED}/messages/AAMkSEED", {"isRead": True})
        foreign = request("PATCH", f"/users/{SHARED}/messages/AAMkOTHER", {"isRead": True})
        assert made.refuses_request(mark, "outlook_mark_mail") is None
        assert "did not read as seed data" in str(
            made.refuses_request(foreign, "outlook_mark_mail")
        )


class TestChatsAndCalendars:
    def test_a_chat_read_with_a_case_topic_may_be_written_into_and_another_chat_may_not(
        self,
    ) -> None:
        made = guard()
        rows = {
            "value": [
                {"id": "chat-case", "topic": "seed-v1 case-teams_send_chat_message-x"},
                {"id": "chat-seed", "topic": "seed-v1 chat"},
                {"id": "chat-other", "topic": "Lunch"},
            ]
        }
        made.saw(request("GET", "/me/chats"), 200, None, rows)
        send = {"body": {"content": "hi"}}
        for chat, ok in (("chat-case", True), ("chat-seed", False), ("chat-other", False)):
            refused = made.refuses_request(
                request("POST", f"/chats/{chat}/messages", send), "teams_send_chat_message"
            )
            assert (refused is None) is ok

    def test_a_calendar_that_a_test_user_owns_may_take_an_event_and_no_other_may(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(
            guard_module.WRITE_TOOLS,
            "outlook_create_event_on_behalf",
            ("POST /v1.0/me/calendars/*/events",),
        )
        made = guard()
        rows = {
            "value": [
                {"id": "cal-anna", "name": "Anna", "canEdit": True, "owner": {"address": UPNS[1]}},
                {"id": "cal-ceo", "name": "CEO", "canEdit": True, "owner": {"address": "c@x.test"}},
                {"id": "cal-note", "owner": {"address": UPNS[1]}, "name": "no calendar keys"},
            ]
        }
        made.saw(request("GET", "/me/calendars"), 200, None, rows)
        tool = "outlook_create_event_on_behalf"
        event = {"subject": "s"}
        ok = made.refuses_request(request("POST", "/me/calendars/cal-anna/events", event), tool)
        assert ok is None
        for calendar in ("cal-ceo", "cal-note", "cal-unknown"):
            refused = made.refuses_request(
                request("POST", f"/me/calendars/{calendar}/events", event), tool
            )
            assert "did not read as seed data" in str(refused)

    def test_a_calendar_of_a_test_user_gives_no_right_to_delete_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(
            guard_module.WRITE_TOOLS, "outlook_delete_calendar", ("DELETE /v1.0/me/calendars/*",)
        )
        made = guard()
        rows = {"value": [{"id": "cal-anna", "canEdit": True, "owner": {"address": UPNS[1]}}]}
        made.saw(request("GET", "/me/calendars"), 200, None, rows)
        refused = made.refuses_request(
            request("DELETE", "/me/calendars/cal-anna"), "outlook_delete_calendar"
        )
        assert "did not read as seed data" in str(refused)


MONITOR = "https://contoso.sharepoint.com/_api/v2.0/monitor/abc"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
SUNDAY, MONDAY, SATURDAY = date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 7)


class TestMonitor:
    def test_the_monitor_of_a_202_copy_may_be_read_once_without_the_token(self) -> None:
        made = guard()
        made.saw(request("POST", "/me/drive/items/AAMkSEED/copy"), 202, MONITOR, None)
        poll = httpx.Request("GET", MONITOR)
        assert made.refuses_request(poll, "sharepoint_copy_item") is None
        authorized = httpx.Request("GET", MONITOR, headers={"authorization": "Bearer t"})
        assert "Authorization" in str(made.refuses_request(authorized, "sharepoint_copy_item"))

    @pytest.mark.parametrize(
        ("status", "location"),
        [(200, MONITOR), (202, "https://evil.example/monitor"), (202, None)],
    )
    def test_no_other_answer_opens_a_host(self, status: int, location: str | None) -> None:
        made = guard()
        made.saw(request("GET", "/me/drive"), status, location, None)
        refused = made.refuses_request(httpx.Request("GET", MONITOR), "sharepoint_copy_item")
        assert refused is not None
        assert "is not the redirect Graph answered" in refused


class TestScheduledReply:
    def sets(self, made: Guard, **setting: object) -> str | None:
        found = {
            "status": "scheduled",
            "externalAudience": "none",
            "scheduledStartDateTime": {
                "dateTime": "2026-11-02T12:00:00.0000000",
                "timeZone": "UTC",
            },
            "scheduledEndDateTime": {"dateTime": "2026-11-03T12:00:00.0000000", "timeZone": "UTC"},
        } | setting
        body = {"automaticRepliesSetting": found}
        return made.refuses_request(
            request("PATCH", "/me/mailboxSettings", body), "outlook_set_automatic_reply"
        )

    @pytest.fixture(autouse=True)
    def forbidden(self, monkeypatch: pytest.MonkeyPatch) -> None:
        patched(monkeypatch, forbidden={"status": frozenset({"alwaysEnabled", "scheduled"})})
        monkeypatch.setitem(
            guard_module.WRITE_TOOLS,
            "outlook_set_automatic_reply",
            ("PATCH /v1.0/me/mailboxSettings",),
        )

    def test_a_reply_for_nobody_outside_that_ends_within_three_days_is_allowed(self) -> None:
        assert self.sets(guard(now=lambda: NOW)) is None

    @pytest.mark.parametrize(
        "setting",
        [
            {"externalAudience": "all"},
            {"externalAudience": "contactsOnly"},
            {"scheduledEndDateTime": {"dateTime": "2026-11-05T12:00:01", "timeZone": "UTC"}},
            {"scheduledEndDateTime": {"dateTime": "2026-11-02T11:59:00", "timeZone": "UTC"}},
            {"scheduledEndDateTime": {"dateTime": "2026-11-03T12:00:00", "timeZone": "Pacific"}},
            {"scheduledEndDateTime": {"dateTime": "soon", "timeZone": "UTC"}},
            {"status": "alwaysEnabled"},
        ],
    )
    def test_any_other_reply_is_refused(self, setting: dict[str, object]) -> None:
        assert "no recording may do" in str(self.sets(guard(now=lambda: NOW), **setting))

    def test_the_status_of_another_body_stays_forbidden(self) -> None:
        other = request("PATCH", "/me/mailboxSettings", {"status": "scheduled"})
        refused = guard(now=lambda: NOW).refuses_request(other, "outlook_set_automatic_reply")
        assert "no recording may do" in str(refused)

    def test_a_scheduled_reply_without_an_end_is_refused(self) -> None:
        body = {"automaticRepliesSetting": {"status": "scheduled", "externalAudience": "none"}}
        refused = guard(now=lambda: NOW).refuses_request(
            request("PATCH", "/me/mailboxSettings", body), "outlook_set_automatic_reply"
        )
        assert "no recording may do" in str(refused)


REPLY = "outlook_set_automatic_reply"


class TestScheduledReplyChain:
    def refusals(self, *statuses: str) -> list[str]:
        steps: tuple[Json, ...] = tuple(
            {"tool": REPLY, "args": {"status": status}} for status in statuses
        )
        return check(Plan("p", "rec-p", steps, True), guard())

    def test_a_chain_that_schedules_a_reply_ends_with_a_step_that_disables_it(self) -> None:
        assert self.refusals("scheduled", "disabled") == []
        assert self.refusals("disabled") == []
        for chain in (("scheduled",), ("scheduled", "disabled", "scheduled")):
            assert "needs a last step" in self.refusals(*chain)[0]

    def test_a_scheduled_reply_followed_by_a_read_is_refused_too(self) -> None:
        steps: tuple[Json, ...] = (
            {"tool": REPLY, "args": {"status": "scheduled"}},
            {"tool": "outlook_get_mailbox_settings"},
        )
        assert "needs a last step" in check(Plan("p", "rec-p", steps, True), guard())[0]


class TestRulesForward:
    @pytest.fixture(autouse=True)
    def rules(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(
            guard_module.WRITE_TOOLS,
            "outlook_create_mail_rule",
            ("POST /v1.0/me/mailFolders/inbox/messageRules",),
        )

    def forward(self, address: str) -> str | None:
        body = {"actions": {"forwardTo": [{"emailAddress": {"address": address}}]}}
        return guard().refuses_request(
            request("POST", "/me/mailFolders/inbox/messageRules", body), "outlook_create_mail_rule"
        )

    def test_a_rule_forwards_to_a_test_user_and_to_nobody_else(self) -> None:
        assert self.forward(UPNS[1]) is None
        assert "that is not a test user" in str(self.forward("x@evil.com"))
        assert "that is not a test user" in str(self.forward(DIRECTORY))


class TestPlaceholders:
    def test_an_env_name_gives_the_address_and_in_the_fixture_its_synthetic_form(self) -> None:
        real = persona_values(UPNS, {}, synthetic=False, extras=EXTRAS)
        fake = persona_values(UPNS, {}, synthetic=True, extras=EXTRAS)
        assert real["env:SEED_ROOM_UPN"] == ROOM
        assert fake["env:SEED_ROOM_UPN"] == "room@example.test" == synthetic_extra("SEED_ROOM_UPN")
        assert fake["env:SEED_DIRECTORY_UPN"] == "directory@example.test"
        assert with_personas({"to": ["env:SEED_GUEST_UPN", "persona:anna"]}, real) == {
            "to": [GUEST, UPNS[1]]
        }

    def test_a_name_whose_variable_is_not_set_is_refused(self) -> None:
        with pytest.raises(Refused, match="not set"):
            _ = with_personas("env:SEED_ROOM_UPN", persona_values(UPNS, {}, synthetic=False))

    def test_the_variables_come_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in EXTRAS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("SEED_ROOM_UPN", f" {ROOM.upper()} ")
        assert extras_from_environment() == {"SEED_ROOM_UPN": ROOM}
        monkeypatch.setenv("SEED_GUEST_UPN", "nobody")
        with pytest.raises(Refused, match="SEED_GUEST_UPN"):
            _ = extras_from_environment()

    def test_a_guard_gets_the_extras_of_the_run(self) -> None:
        plan = resolve("outlook_list_mail-inbox")
        assert guard_for(UPNS, plan, False, 40, EXTRAS).extras == EXTRAS
        assert guard_for(UPNS, plan, False, 40).extras == {}

    def test_the_scrub_writes_the_synthetic_address_in_place_of_the_extra_one(self) -> None:
        answer = {"value": [{"id": "x", "mail": ROOM, "displayName": "Room"}]}
        asked = asked_of("GET", GRAPH_HOST, "/v1.0/me/people")
        body = json.dumps(answer).encode()
        head = (("content-type", "application/json"),)
        hop = Hop(asked, f"{GRAPH}/me/people", False, 200, head, body)
        recording = Recording(
            "one",
            "rec-one",
            "stand-in",
            datetime(2026, 11, 2, tzinfo=UTC),
            (hop,),
            Identities(frozenset(), "t"),
            {ROOM: "room"},
            frozenset(),
        )
        kept = body_of(files_of(scrub(recording)), "rec-one.01").decode()
        assert "room@example.test" in kept and ROOM not in kept


class TestGeneratedArguments:
    def test_a_repeat_gives_the_text_the_number_of_times(self) -> None:
        assert generated({"repeat": {"text": "ab", "count": 3}}) == "ababab"
        assert generated({"a": [{"repeat": {"text": "x", "count": 2}}], "b": 1}) == {
            "a": ["xx"],
            "b": 1,
        }
        assert resolved({"repeat": {"text": "x", "count": 1_000_000}}, ()) == "x" * 1_000_000

    @pytest.mark.parametrize(
        "spec",
        [
            {"text": "", "count": 3},
            {"text": "a", "count": 0},
            {"text": "a", "count": "3"},
            {"text": "a", "count": 20_000_001},
            {"count": 3},
        ],
    )
    def test_a_bad_repeat_is_refused(self, spec: Mapping[str, object]) -> None:
        with pytest.raises(ValueError, match="repeat"):
            _ = generated({"repeat": spec})

    def test_a_placeholder_of_a_length_matches_any_text_of_that_length(self) -> None:
        assert same("<generated:5>", "abcde")
        assert not same("<generated:5>", "abcd")
        assert not same("<generated:5>", 5)
        assert same({"body": "<generated:3>"}, {"body": "xyz"})

    def test_the_plan_keeps_a_short_generated_text_as_a_literal_and_drops_a_giant_one(
        self,
    ) -> None:
        steps: tuple[Json, ...] = (
            {"tool": "x", "args": {"a": {"repeat": {"text": "abcd", "count": 500}}}},
            {"tool": "y", "args": {"b": {"repeat": {"text": "z", "count": LARGE_BODY + 1}}}},
        )
        literals = Plan("p", "rec-p", steps, True).literals
        assert literals == {"abcd" * 500}

    def test_a_giant_request_text_is_a_placeholder_with_its_length_in_the_metadata(self) -> None:
        text = "a" * (LARGE_BODY + 7)
        asked = asked_of("PUT", GRAPH_HOST, "/v1.0/me/x", {"content": text, "title": "seed-v1 x"})
        hop = Hop(asked, f"{GRAPH}/me/x", False, 200, (), b"")
        recording = Recording(
            "one",
            "rec-one",
            "stand-in",
            datetime(2026, 11, 2, tzinfo=UTC),
            (hop,),
            Identities(frozenset(), "t"),
            {},
            frozenset(),
        )
        fixture = scrub(recording)
        assert (
            mapping(mapping(fixture.interactions[0])["json"])["content"]
            == f"<generated:{len(text)}>"
        )
        assert fixture.metadata["request_size"] == {"1": [len(text)]}
        assert len(files_of(fixture)["fixtures/rec-one.json"]) < 1000


class TestWorkingHours:
    def test_a_time_and_a_zone_name_stay_and_anything_else_is_replaced(self) -> None:
        answer = {
            "value": [
                {
                    "scheduleId": UPNS[1],
                    "workingHours": {
                        "daysOfWeek": ["monday"],
                        "startTime": "08:00:00.0000000",
                        "endTime": "qzx unseeded",
                        "timeZone": {"name": f"x@{DOMAIN}"},
                    },
                }
            ]
        }
        asked = asked_of("POST", GRAPH_HOST, "/v1.0/me/calendar/getSchedule")
        body = json.dumps(answer).encode()
        hop = Hop(asked, f"{GRAPH}/me/calendar/getSchedule", False, 200, JSON_HEAD, body)
        recording = Recording(
            "one",
            "rec-one",
            "stand-in",
            datetime(2026, 11, 2, tzinfo=UTC),
            (hop,),
            Identities(frozenset(), "t"),
            {},
            frozenset(),
        )
        kept = mapping(
            cast("object", json.loads(body_of(files_of(scrub(recording)), "rec-one.01")))
        )
        hours = mapping(mapping(cast("list[object]", kept["value"])[0])["workingHours"])
        assert hours["startTime"] == "08:00:00.0000000"
        assert hours["endTime"] == "synthetic text 01"
        assert hours["timeZone"] == {"name": "synthetic text 02"}


class TestDayTokens:
    @pytest.mark.parametrize(
        ("today", "word", "expected"),
        [
            (SUNDAY, "nextMonday", date(2026, 11, 2)),
            (MONDAY, "nextMonday", date(2026, 11, 9)),
            (SATURDAY, "nextMonday", date(2026, 11, 9)),
            (SATURDAY, "nextTuesday", date(2026, 11, 10)),
            (SATURDAY, "nextWednesday", date(2026, 11, 11)),
            (MONDAY, "nextMonday+2", date(2026, 11, 11)),
            (MONDAY, "nextMonday-7", date(2026, 11, 2)),
            (MONDAY, "tomorrow", date(2026, 11, 3)),
            (MONDAY, "yesterday", date(2026, 11, 1)),
        ],
    )
    def test_a_weekday_is_the_next_one_on_or_after_tomorrow(
        self, today: date, word: str, expected: date
    ) -> None:
        assert day_named(word, today) == expected

    def test_a_token_in_an_argument_becomes_that_day(self) -> None:
        assert resolved("~nextMonday", ()) == day_named("nextMonday").isoformat()
        assert resolved("a~nextTuesday+1T09:00:00", ()) == (
            f"a{day_named('nextTuesday+1').isoformat()}T09:00:00"
        )
        assert same("~nextMonday", f"{day_named('nextMonday').isoformat()}T10:00:00Z")
        assert not same("~nextMonday", f"{day_named('nextWednesday').isoformat()}T10:00:00Z")

    def test_the_scrub_writes_the_token_that_the_case_used_even_when_it_is_tomorrow(self) -> None:
        monday = day_named("nextMonday", SUNDAY)
        assert monday == date(2026, 11, 2)
        symbols = scrub_module._symbols(SUNDAY, frozenset({"~nextMonday"}))
        assert symbols(f"{monday.isoformat()}T09:00:00") == "~nextMonday"
        assert symbols("2026-11-01") == "~today"
        plain = scrub_module._symbols(SUNDAY)
        assert plain("2026-11-02") == "~tomorrow"

    def test_a_fixture_recorded_on_one_day_replays_on_another(self) -> None:
        recorded = scrub_module._symbols(SUNDAY)("2026-11-20T09:00:00+00:00")
        assert recorded == "~day+19"
        assert scrub_module._symbols(SUNDAY)("2026-10-20") == "~day-12"
        assert day_named("day+19", SUNDAY) == date(2026, 11, 20)
        assert day_named("day-12", MONDAY) == date(2026, 10, 21)
        assert resolved("a~day+19T09:00:00", ()) == f"a{day_named('day+19').isoformat()}T09:00:00"
        assert same("~day+19", f"{day_named('day+19').isoformat()}T10:00:00Z")

    def test_the_plan_names_the_tokens_of_its_steps(self) -> None:
        steps: tuple[Json, ...] = ({"tool": "x", "args": {"d": "~nextMonday", "e": "~today+0"}},)
        assert Plan("p", "rec-p", steps, True).tokens == {"~nextMonday", "~today"}


def answer_of(spec: Mapping[str, object]) -> httpx.Response:
    return httpx.Response(
        cast("int", spec["status"]), content=b"downloaded" if "body" in spec else b""
    )


def a_generated_recording(size: int = LARGE_BODY + 100) -> tuple[Recording, scrub_module.Corpus]:
    raw = bytes(range(256)) * (size // 256 + 1)
    sha = hashlib.sha256(raw).hexdigest()
    corpus = load_corpus()
    corpus = replace(
        corpus,
        binaries=corpus.binaries | {sha},
        generated={sha: {"generator": "filler", "size": len(raw), "label": "t", "sha256": sha}},
    )
    download = asked_of("GET", "x.sharepoint.com", "/f")
    attachment = asked_of("GET", GRAPH_HOST, "/v1.0/me/a")
    body = json.dumps({"contentBytes": base64.b64encode(raw).decode()}).encode()
    hops = (
        Hop(
            download,
            "https://x.sharepoint.com/f",
            False,
            200,
            (("content-type", "application/pdf"),),
            raw,
        ),
        Hop(attachment, f"{GRAPH}/me/a", False, 200, (("content-type", "application/json"),), body),
    )
    recording = Recording(
        "one",
        "rec-one",
        "stand-in",
        datetime(2026, 11, 2, tzinfo=UTC),
        hops,
        Identities(frozenset(), "t"),
        {},
        frozenset(),
    )
    return recording, corpus


class TestGeneratedBodies:
    def test_a_big_seed_body_becomes_a_stub_and_its_json_leaf_becomes_a_placeholder(self) -> None:
        recording, corpus = a_generated_recording()
        fixture = scrub(recording, corpus)
        sha = next(iter(corpus.generated))
        stub = cast("Json", json.loads(fixture.bodies[f"{sha}.gen"]))
        assert stub == {
            "generator": "filler",
            "label": "t",
            "sha256": sha,
            "size": len(recording.hops[0].body),
        }
        assert fixture.interactions[0]["body"] == f"{sha}.gen"
        assert "body" not in fixture.interactions[1]
        leaf = cast("Json", json.loads(body_of(fixture, "rec-one.02")))
        assert leaf == {"contentBytes": f"<generated:{sha}>"}
        assert sum(len(one) for one in fixture.bodies.values()) < 2000

    def test_the_lint_accepts_the_stubs_and_refuses_each_that_the_manifest_does_not_hold(
        self,
    ) -> None:
        recording, corpus = a_generated_recording()
        files = files_of(scrub(recording, corpus))
        assert lint_files(files, (), corpus) == []
        sha = next(iter(corpus.generated))
        stub = cast("Json", json.loads(files[f"bodies/{sha}.gen"]))
        for change in (
            {"size": len(recording.hops[0].body) + 1},
            {"label": "other"},
            {"generator": "text"},
        ):
            bad = {**files, f"bodies/{sha}.gen": json.dumps({**stub, **change}).encode()}
            assert any("stub whose generator" in found for found in lint_files(bad, (), corpus))
        wrong = {k: v for k, v in files.items() if not k.endswith(".gen")}
        assert any("is missing" in found for found in lint_files(wrong, (), corpus))
        not_held = replace(corpus, generated={})
        assert lint_files(files, (), not_held) != []

    def test_the_stub_expands_to_the_bytes_that_the_generator_makes(self, tmp_path: Path) -> None:
        raw = bytes(generate("filler", 400_000, "label"))
        sha = hashlib.sha256(raw).hexdigest()
        stub = {"generator": "filler", "size": 400_000, "label": "label", "sha256": sha}
        (tmp_path / f"{sha}.gen").write_text(json.dumps(stub))
        assert response({"status": 200, "body": f"{sha}.gen"}, tmp_path).content == raw
        (tmp_path / "a.json").write_text(f'{{"contentBytes": "<generated:{sha}>"}}')
        made = response({"status": 200, "body": "a.json"}, tmp_path)
        assert json.loads(made.content) == {"contentBytes": base64.b64encode(raw).decode()}
        assert made.headers["content-type"] == "application/json"
        (tmp_path / f"{sha}.gen").write_text(json.dumps({**stub, "label": "changed"}))
        with pytest.raises(ValueError, match="changed"):
            _ = response({"status": 200, "body": f"{sha}.gen"}, tmp_path)


class TestHostEntries:
    def test_a_fixture_row_with_a_host_is_answered_on_that_host_and_graph_rows_stay(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "fixtures").mkdir()
        (tmp_path / "bodies").mkdir()
        (tmp_path / "bodies" / "file.txt").write_text("downloaded")
        rows = [
            {"method": "GET", "path": "/v1.0/me/drive/items/i/content", "status": 302},
            {
                "method": "GET",
                "host": "contoso.sharepoint.com",
                "path": "/dl/f",
                "status": 200,
                "body": "file.txt",
            },
        ]
        (tmp_path / "fixtures" / "rec-h.json").write_text(json.dumps(rows))
        monkeypatch.setattr("tests.graph_fixtures.INTEGRATION", tmp_path)
        monkeypatch.setattr("tests.graph_fixtures.response", answer_of)
        with respx.mock(base_url=GRAPH, assert_all_called=False) as router:
            routes = serve(router, "rec-h")
            assert set(routes) == {
                ("GET", "/me/drive/items/i/content"),
                ("GET", "https://contoso.sharepoint.com/dl/f"),
            }
            with httpx.Client() as client:
                assert client.get("https://contoso.sharepoint.com/dl/f").content == b"downloaded"
                assert client.get(f"{GRAPH}/me/drive/items/i/content").status_code == 302
                with pytest.raises(Exception, match="not mocked"):
                    _ = client.get("https://other.example/dl/f")

    def test_a_non_graph_row_without_a_host_is_still_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        (tmp_path / "fixtures").mkdir()
        rows = [{"method": "GET", "path": "/other/me", "status": 200}]
        (tmp_path / "fixtures" / "rec-h.json").write_text(json.dumps(rows))
        monkeypatch.setattr("tests.graph_fixtures.INTEGRATION", tmp_path)
        with respx.mock(base_url=GRAPH) as router, pytest.raises(ValueError, match="v1.0"):
            _ = serve(router, "rec-h")

    def test_the_replay_matches_a_row_by_its_host(self) -> None:
        row = {"method": "GET", "host": "contoso.sharepoint.com", "path": "/dl/f", "status": 200}
        replay = Replay([row])
        assert (
            replay(httpx.Request("GET", "https://contoso.sharepoint.com/dl/f")).status_code == 200
        )
        assert replay.unmatched == []


class TestPlaceholdersInTheStaticCheck:
    def refusals(self, tool: str, args: Json) -> list[str]:
        plan = Plan("p", "rec-p", ({"tool": tool, "args": args},), True)
        return check(plan, guard_for(UPNS, plan, True, 40), planned_values(UPNS))

    def test_an_inviting_tool_may_name_a_persona_by_placeholder_and_by_id_placeholder(self) -> None:
        anna = {"emailAddress": "persona:anna"}
        assert self.refusals("outlook_create_event", {"attendees": [anna]}) == []
        by_id = {"user_id": "persona:anna.id", "name": "persona:anna.name"}
        assert self.refusals("teams_create_meeting", {"attendees": [by_id]}) == []

    @pytest.mark.parametrize(
        ("tool", "args"),
        [
            ("outlook_create_event", {"attendees": ["persona:anna", "mallory@evil.example"]}),
            ("outlook_create_event", {"attendees": ["mallory@evil.example"]}),
            ("outlook_create_event", {"attendees": ["env:SEED_ROOM_UPN"]}),
            (
                "outlook_create_event",
                {"attendees": [{"user_id": "00000000-0000-4000-8000-000000000bad"}]},
            ),
            ("outlook_mark_mail", {"attendees": ["persona:anna"]}),
        ],
    )
    def test_a_stranger_a_missing_variable_or_a_tool_that_may_not_invite_is_still_refused(
        self, tool: str, args: Json
    ) -> None:
        assert self.refusals(tool, args) != []

    def test_the_dry_run_shows_the_same_verdicts_and_never_the_address(self) -> None:
        plan = Plan(
            "p",
            "rec-p",
            ({"tool": "outlook_create_event", "args": {"attendees": ["persona:anna"]}},),
            True,
        )
        lines = describe(plan, guard_for(UPNS, plan, True, 40), planned_values(UPNS))
        assert [line for line in lines if "REFUSED" in line] == []
        assert UPNS[1] not in "".join(lines)
