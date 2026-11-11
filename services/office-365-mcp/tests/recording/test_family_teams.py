import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import yaml

from office_365_mcp.tools import TOOL_NAMES
from tests.integration.test_scenarios import mapping
from tests.recording import stand_in
from tests.recording.cases import case_entries
from tests.recording.conftest import body_of
from tests.recording.families import load
from tests.recording.guard import DEFAULT_CAP, GRAPH_HOST, Guard, foreign_address
from tests.recording.lint import lint_files
from tests.recording.record import check, describe, guard_for, resolve, tool_of
from tests.recording.scrub import Hop, Identities, Recording, files_of, load_corpus, scrub

GRAPH = f"https://{GRAPH_HOST}/v1.0"
TEAM = "5a1f7c2e-3b4d-4e6f-8a9b-0c1d2e3f4a5b"
CHANNEL = "19:Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFi@thread.tacv2"
CHAT = "19:Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFi@thread.v2"
POST = "1770000000000"
MEETING = "MSo1N2Y5ZGZiYS0wMDAwLTRhYWEtODAwMC0wMDAwMDAwMDAwMDA"
CASES = [case for case, _ in case_entries() if case.startswith("teams_")]
UNCOVERED = frozenset(tool for tool in load().unrecorded if tool.startswith("teams_"))


THREADS = (
    CHANNEL,
    CHAT,
    "19:meeting_ZmFrZW1lZXRpbmdpZDEyMzQ1Njc4OTBhYmNkZWY@thread.v2",
    "19:a1b2c3d4-e5f6-7788-9900-aabbccddeeff_11112222-3333-4444-5555-666677778888@unq.gbl.spaces",
    "19:11112222-3333-4444-5555-666677778888_a1b2c3d4-e5f6-7788-9900-aabbccddeeff@xyz.unq.gbl.spaces",
)
JOIN_URL = (
    "https://teams.microsoft.com/l/meetup-join/19%3ameeting_ZmFrZW1lZXRpbmdpZDEyMzQ1Njc4OTBhYmNkZWY"
    + f"%40thread.v2/0?context=%7b%22Tid%22%3a%22{stand_in.TENANT_ID}%22%7d"
)
MEETING_LOOKUP: tuple[tuple[str, object], tuple[str, object, dict[str, str]]] = (
    (
        "/me/onlineMeetings/createOrGet",
        {
            "id": MEETING,
            "joinWebUrl": JOIN_URL,
            "chatInfo": {"threadId": THREADS[2], "messageId": "0"},
        },
    ),
    ("/me/onlineMeetings", {"value": []}, {"$filter": f"JoinWebUrl eq '{JOIN_URL}'"}),
)


def an_id(value: str) -> str:
    return quote(value, safe="")


def guard() -> Guard:
    return Guard(
        stand_in.UPN,
        frozenset(stand_in.UPNS),
        True,
        me_id=stand_in.USER_ID,
        drive_ids=frozenset({stand_in.DRIVE_ID}),
    )


def ask(method: str, path: str, body: object = None) -> httpx.Request:
    return httpx.Request(method, f"{GRAPH}{path}", json=body)


def saw(seen: Guard, method: str, path: str, status: int, body: object) -> None:
    seen.saw(ask(method, path), status, None, body)


def a_guard_that_read_the_seed_team() -> Guard:
    seen = guard()
    saw(
        seen,
        "GET",
        "/me/joinedTeams",
        200,
        {"value": [{"id": TEAM, "displayName": "seed-v1 team"}]},
    )
    channels = {"value": [{"id": CHANNEL, "displayName": "seed-v1 private channel"}]}
    saw(seen, "GET", f"/teams/{TEAM}/channels", 200, channels)
    return seen


def a_guard_with_a_post(seen: Guard | None = None) -> Guard:
    seen = seen or a_guard_that_read_the_seed_team()
    saw(seen, "POST", f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages", 201, {"id": POST})
    return seen


class TestCases:
    def test_the_cases_and_the_reasons_cover_every_tool_of_the_family(self) -> None:
        family = {tool for tool in TOOL_NAMES if tool.startswith("teams_")}
        covered = {tool_of(resolve(case).steps[-1]) for case in CASES}
        assert covered | UNCOVERED == family
        assert not covered & UNCOVERED

    @pytest.mark.parametrize("case", CASES)
    def test_a_case_passes_the_guard_plan(self, case: str) -> None:
        plan = resolve(case)
        seen = guard_for(stand_in.UPNS, plan, True, DEFAULT_CAP)
        assert case.startswith(f"{tool_of(plan.steps[-1])}-")
        assert check(plan, seen) == []
        assert not [line for line in describe(plan, seen) if "REFUSED" in line]

    def test_a_case_that_posts_to_a_channel_picks_the_seed_team_by_name(self) -> None:
        posting = [
            case
            for case in CASES
            if resolve(case).external and "chat" not in case and "meeting" not in case
        ]
        assert len(posting) == 11
        for case in posting:
            given = json.dumps(resolve(case).steps)
            assert "teams[display_name=seed-v1 team].team_id" in given
            assert "teams[0]" not in given

    def test_no_case_destroys_a_seed_item(self) -> None:
        assert not [case for case in CASES if resolve(case).destructive]

    def test_a_case_that_posts_to_a_channel_runs_after_the_others(self) -> None:
        external = {case for case in CASES if resolve(case).external}
        assert {case for case in CASES if "channel_message" in case} <= external
        reading = {case for case in CASES if case.startswith("teams_list_") and "chat" in case}
        writing = {case for case in CASES if "chat" in case} - reading - {"teams_read_message-chat"}
        assert writing <= external
        assert not reading & external

    def test_a_case_needs_a_key_that_a_probe_can_check(self) -> None:
        merged = load()
        keys = {"teams-team", "teams-seed-team", "teams-seed-chats", "teams-chat"}
        keys |= {"teams-meeting", "teams-meeting-attendance", "teams-private-channel"}
        needed = {key for case in CASES for key in resolve(case).needs}
        assert needed == keys | {"sharepoint-seed-files"}
        assert keys <= set(merged.needs)
        assert keys <= set(merged.probes)


class TestAllowedRequests:
    @pytest.mark.parametrize(
        ("tool", "method", "path"),
        [
            ("teams_list_my_teams", "GET", "/me/joinedTeams"),
            ("teams_list_channels", "GET", f"/teams/{TEAM}/channels"),
            (
                "teams_get_channel_files_folder",
                "GET",
                f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/filesFolder",
            ),
            ("teams_browse_channel", "GET", f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages"),
            ("teams_list_chats", "GET", "/me/chats"),
            ("teams_list_chat_members", "GET", f"/chats/{an_id(CHAT)}/members"),
            ("teams_list_chat_messages", "GET", f"/chats/{an_id(CHAT)}/messages"),
            ("teams_read_message", "GET", f"/chats/{an_id(CHAT)}/messages/{POST}"),
            ("teams_search_messages", "POST", "/search/query"),
            (
                "teams_search_messages",
                "GET",
                f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages/{POST}",
            ),
            ("teams_list_meeting_recordings", "GET", f"/me/onlineMeetings/{MEETING}/recordings"),
            ("teams_list_meeting_transcripts", "GET", f"/me/onlineMeetings/{MEETING}/transcripts"),
            (
                "teams_list_message_replies",
                "GET",
                f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages/{POST}/replies",
            ),
            ("teams_read_meeting", "GET", f"/me/onlineMeetings/{MEETING}/attendanceReports"),
            (
                "teams_send_channel_message_with_files",
                "GET",
                f"/drives/{stand_in.DRIVE_ID}/items/01ABC",
            ),
            ("teams_delete_message", "GET", "/me"),
        ],
    )
    def test_a_read_of_the_family_is_allowed(self, tool: str, method: str, path: str) -> None:
        assert guard().refuses_request(ask(method, path), tool) is None

    def test_a_search_reaches_no_other_post(self) -> None:
        assert guard().refuses_request(ask("POST", "/search/query"), "teams_list_chats") is not None

    @pytest.mark.parametrize(
        ("tool", "method", "path"),
        [
            (
                "teams_send_channel_message",
                "POST",
                f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages",
            ),
            (
                "teams_send_channel_message_with_files",
                "POST",
                f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages",
            ),
            (
                "teams_send_channel_message",
                "POST",
                f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages/{POST}/replies",
            ),
            (
                "teams_edit_message",
                "PATCH",
                f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages/{POST}",
            ),
            (
                "teams_react_to_message",
                "POST",
                f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages/{POST}/setReaction",
            ),
            (
                "teams_react_to_message",
                "POST",
                f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages/{POST}/unsetReaction",
            ),
            (
                "teams_delete_message",
                "POST",
                f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages/{POST}/softDelete",
            ),
        ],
    )
    def test_a_write_to_a_post_of_this_run_in_the_seed_channel_is_allowed(
        self, tool: str, method: str, path: str
    ) -> None:
        seen = a_guard_with_a_post()
        assert seen.refuses_request(ask(method, path), tool) is None

    @pytest.mark.parametrize(
        ("tool", "method", "path"),
        [
            ("teams_create_meeting", "POST", "/me/onlineMeetings/createOrGet"),
        ],
    )
    def test_a_meeting_is_created_under_me(self, tool: str, method: str, path: str) -> None:
        assert guard().refuses_request(ask(method, path), tool) is None

    @pytest.mark.parametrize(
        ("tool", "method"),
        [("teams_update_meeting", "PATCH"), ("teams_delete_meeting", "DELETE")],
    )
    def test_a_meeting_of_this_run_is_changed_and_deleted(self, tool: str, method: str) -> None:
        seen = guard()
        saw(seen, "POST", "/me/onlineMeetings/createOrGet", 201, {"id": MEETING})
        assert seen.refuses_request(ask(method, f"/me/onlineMeetings/{MEETING}"), tool) is None


OTHER = "99999999-3b4d-4e6f-8a9b-0c1d2e3f4a5b"
STANDARD = "19:c3RhbmRhcmRjaGFubmVsaWQxMjM0NTY3ODkwYWI@thread.tacv2"
CREATE = "/me/onlineMeetings/createOrGet"


class TestChannelsOfTheSeedTeam:
    def listed(self, team: str) -> Guard:
        seen = a_guard_that_read_the_seed_team()
        channels = {"value": [{"id": STANDARD, "displayName": "General"}]}
        saw(seen, "GET", f"/teams/{team}/channels", 200, channels)
        return seen

    def test_a_standard_channel_of_the_seed_team_takes_a_post(self) -> None:
        path = f"/teams/{TEAM}/channels/{an_id(STANDARD)}/messages"
        refusal = self.listed(TEAM).refuses_request(ask("POST", path), "teams_send_channel_message")
        assert refusal is None

    def test_a_channel_listed_under_a_team_that_is_not_seed_data_takes_no_post(self) -> None:
        path = f"/teams/{OTHER}/channels/{an_id(STANDARD)}/messages"
        refusal = self.listed(OTHER).refuses_request(
            ask("POST", path), "teams_send_channel_message"
        )
        assert "did not read as seed data" in str(refusal)

    def test_a_failed_listing_makes_no_channel_seed_data(self) -> None:
        seen = a_guard_that_read_the_seed_team()
        channels = {"value": [{"id": STANDARD}]}
        saw(seen, "GET", f"/teams/{TEAM}/channels", 403, channels)
        path = f"/teams/{TEAM}/channels/{an_id(STANDARD)}/messages"
        refusal = seen.refuses_request(ask("POST", path), "teams_send_channel_message")
        assert "did not read as seed data" in str(refusal)


class TestAMeetingThatCreateOrGetAnswered:
    @pytest.mark.parametrize(
        ("tool", "method"),
        [("teams_update_meeting", "PATCH"), ("teams_delete_meeting", "DELETE")],
    )
    def test_a_seed_case_meeting_that_exists_already_is_this_runs_meeting(
        self, tool: str, method: str
    ) -> None:
        seen = guard()
        body = {"subject": "seed-v1 case-teams_update_meeting-subject meeting"}
        seen.saw(ask("POST", CREATE, body), 200, None, {"id": MEETING})
        assert seen.refuses_request(ask(method, f"/me/onlineMeetings/{MEETING}"), tool) is None

    @pytest.mark.parametrize(
        ("path", "body"),
        [
            (CREATE, {"subject": "Quarterly review"}),
            (CREATE, {"startDateTime": "2026-10-31T14:00:00Z"}),
            ("/me/onlineMeetings", {"subject": "seed-v1 case-x meeting"}),
            ("/me/onlineMeetings/createOrGetX", {"subject": "seed-v1 case-x meeting"}),
        ],
    )
    def test_any_other_answer_of_200_makes_no_meeting_of_this_run(
        self, path: str, body: dict[str, str]
    ) -> None:
        seen = guard()
        seen.saw(ask("POST", path, body), 200, None, {"id": MEETING})
        refusal = seen.refuses_request(
            ask("DELETE", f"/me/onlineMeetings/{MEETING}"), "teams_delete_meeting"
        )
        assert "did not read as seed data" in str(refusal)


class TestRefusedRequests:
    def test_a_post_in_a_channel_that_is_not_seed_data_is_refused(self) -> None:
        path = f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages"
        refusal = guard().refuses_request(ask("POST", path), "teams_send_channel_message")
        assert refusal is not None
        assert "did not read as seed data" in refusal

    def test_a_channel_of_another_team_is_refused(self) -> None:
        other = "99999999-3b4d-4e6f-8a9b-0c1d2e3f4a5b"
        path = f"/teams/{other}/channels/{an_id(CHANNEL)}/messages"
        refusal = a_guard_that_read_the_seed_team().refuses_request(
            ask("POST", path), "teams_send_channel_message"
        )
        assert refusal is not None
        assert "did not read as seed data" in refusal

    @pytest.mark.parametrize(
        ("tool", "method", "suffix"),
        [
            ("teams_edit_message", "PATCH", ""),
            ("teams_react_to_message", "POST", "/setReaction"),
            ("teams_delete_message", "POST", "/softDelete"),
        ],
    )
    def test_a_message_of_an_earlier_run_is_refused(
        self, tool: str, method: str, suffix: str
    ) -> None:
        path = f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages/{POST}{suffix}"
        refusal = a_guard_that_read_the_seed_team().refuses_request(ask(method, path), tool)
        assert refusal is not None
        assert "did not read as seed data" in refusal

    @pytest.mark.parametrize(
        ("tool", "method", "path"),
        [
            ("teams_send_channel_message", "POST", f"/chats/{an_id(CHAT)}/messages"),
            ("teams_rename_chat", "PATCH", f"/chats/{an_id(CHAT)}"),
            ("teams_remove_chat_member", "DELETE", f"/chats/{an_id(CHAT)}/members/{POST}"),
            ("teams_delete_message", "POST", f"/me/chats/{an_id(CHAT)}/messages/{POST}/softDelete"),
            ("teams_update_meeting", "PATCH", f"/me/onlineMeetings/{MEETING}"),
            ("teams_delete_meeting", "DELETE", f"/me/onlineMeetings/{MEETING}"),
            ("teams_list_chats", "POST", "/me/chats"),
            ("teams_list_channels", "POST", f"/teams/{TEAM}/channels"),
        ],
    )
    def test_a_write_outside_the_channel_and_meeting_paths_is_refused(
        self, tool: str, method: str, path: str
    ) -> None:
        assert a_guard_with_a_post().refuses_request(ask(method, path), tool) is not None

    def test_a_tool_without_a_case_is_not_on_the_allowlist(self) -> None:
        refusal = guard().refuses_call("teams_unlisted_tool", {})
        assert refusal is not None
        assert "allowlist" in refusal

    @pytest.mark.parametrize("tool", ["teams_create_meeting", "teams_update_meeting"])
    def test_a_meeting_with_attendees_is_refused(self, tool: str) -> None:
        refusal = guard().refuses_call(tool, {"attendees": [{"user_id": POST, "name": "Anna"}]})
        assert refusal is not None
        assert "invite" in refusal

    def test_a_channel_post_that_names_an_outside_address_is_refused(self) -> None:
        refusal = guard().refuses_call(
            "teams_send_channel_message", {"message": "write to a@evil.example"}
        )
        assert refusal is not None


class TestThreadIds:
    @pytest.mark.parametrize(
        "text",
        [
            f"teams:///teams/{TEAM}/channels/{an_id(CHANNEL)}/messages/{POST}",
            f"teams:///chats/{an_id(CHAT)}/messages/{POST}",
            "19:a1b2c3d4-e5f6-7788-9900-aabbccddeeff_11112222-3333-4444-5555-666677778888@unq.gbl.spaces",
            "19:a1b2c3d4-e5f6-7788-9900-aabbccddeeff_11112222-3333-4444-5555-666677778888@xyz.unq.gbl.spaces",
        ],
    )
    def test_a_thread_id_is_no_address(self, text: str) -> None:
        assert foreign_address(text, frozenset(stand_in.UPNS)) is None

    @pytest.mark.parametrize(
        "text",
        [
            "a@evil.example",
            "a@thread.evil.example",
            "19:abc@thread.v2.evil.example",
            "19:abc@aa.bb.cc.dd.spaces",
        ],
    )
    def test_a_look_alike_is_still_an_address(self, text: str) -> None:
        assert foreign_address(text, frozenset(stand_in.UPNS)) is not None


def recorded(*answers: tuple[str, object] | tuple[str, object, dict[str, str]]) -> Recording:
    hops = tuple(
        Hop(
            {
                "method": "GET",
                "host": GRAPH_HOST,
                "path": path,
                "query": query[0] if query else {},
                "headers": {},
                "json": None,
            },
            f"{GRAPH}{path}",
            False,
            200,
            (("content-type", "application/json"),),
            json.dumps(body).encode(),
        )
        for path, body, *query in answers
    )
    corpus = load_corpus()
    personas = {stand_in.UPNS[one.index - 1].casefold(): one.key for one in corpus.personas}
    return Recording(
        "teams",
        "rec-tool-teams",
        "stand-in",
        datetime.now(UTC),
        hops,
        Identities(frozenset(), "token"),
        personas,
        frozenset(),
    )


PERSON = {
    "user": {"id": stand_in.USER_ID, "displayName": "Mia Keller", "userIdentityType": "aadUser"}
}
MESSAGE = {
    "id": POST,
    "replyToId": None,
    "messageType": "message",
    "createdDateTime": "2026-10-28T09:00:00Z",
    "lastEditedDateTime": None,
    "deletedDateTime": None,
    "subject": None,
    "importance": "normal",
    "locale": "en-us",
    "webUrl": None,
    "from": PERSON,
    "body": {"contentType": "html", "content": "<p>Hello</p>"},
    "attachments": [{"id": TEAM, "contentType": "reference", "contentUrl": None, "name": "x"}],
    "mentions": [{"id": 0, "mentionText": "Anna", "mentioned": PERSON}],
    "reactions": [
        {"reactionType": "like", "createdDateTime": "2026-10-28T09:01:00Z", "user": PERSON}
    ],
}
SHAPES: dict[str, object] = {
    "/me/joinedTeams": {
        "value": [
            {
                "id": TEAM,
                "displayName": "Dogfood",
                "description": None,
                "isArchived": False,
                "tenantId": stand_in.TENANT_ID,
            }
        ]
    },
    f"/teams/{TEAM}/channels": {
        "value": [
            {
                "id": TEAM,
                "displayName": "General",
                "description": None,
                "createdDateTime": "2026-10-01T08:00:00Z",
                "membershipType": "standard",
            }
        ]
    },
    "/me/chats": {
        "value": [
            {
                "id": TEAM,
                "topic": None,
                "chatType": "group",
                "createdDateTime": "2026-10-01T08:00:00Z",
                "lastUpdatedDateTime": "2026-10-01T08:00:00Z",
                "tenantId": stand_in.TENANT_ID,
                "viewpoint": {"isHidden": False, "lastMessageReadDateTime": "2026-10-01T08:00:00Z"},
                "members": [
                    {
                        "id": TEAM,
                        "roles": ["owner"],
                        "displayName": "Mia Keller",
                        "visibleHistoryStartDateTime": "0001-01-01T00:00:00Z",
                        "userId": stand_in.USER_ID,
                        "email": stand_in.UPN,
                        "tenantId": stand_in.TENANT_ID,
                    }
                ],
                "lastMessagePreview": {
                    "id": POST,
                    "createdDateTime": "2026-10-28T09:00:00Z",
                    "isDeleted": False,
                    "messageType": "message",
                    "eventDetail": None,
                    "from": PERSON,
                    "body": {"contentType": "text", "content": "Hello"},
                },
            }
        ]
    },
    f"/teams/{TEAM}/channels/{TEAM}/messages": {
        "value": [
            {
                **MESSAGE,
                "chatId": None,
                "channelIdentity": {"teamId": TEAM, "channelId": TEAM},
                "from": {"application": None, "device": None, **PERSON},
            }
        ]
    },
    "/me/onlineMeetings": {
        "value": [
            {
                "id": MEETING,
                "creationDateTime": "2026-10-28T09:00:00Z",
                "startDateTime": "2026-10-29T14:00:00Z",
                "endDateTime": "2026-10-29T14:30:00Z",
                "subject": None,
                "externalId": TEAM,
                "joinWebUrl": f"https://teams.microsoft.com/l/meetup-join/{TEAM}/0",
                "chatInfo": {"threadId": TEAM, "messageId": "0"},
                "participants": {
                    "organizer": {"upn": stand_in.UPN, "role": "presenter", "identity": PERSON},
                    "attendees": [],
                },
                "lobbyBypassSettings": {"scope": "organization", "isDialInBypassEnabled": False},
            }
        ]
    },
}


IDENTITY = {"id": stand_in.USER_ID, "displayName": "Mia Keller", "tenantId": stand_in.TENANT_ID}
MEETING_ARTIFACT = {
    "id": TEAM,
    "meetingId": TEAM,
    "callId": TEAM,
    "contentCorrelationId": TEAM,
    "createdDateTime": "2026-10-28T09:00:00Z",
    "endDateTime": "2026-10-28T09:10:00Z",
    "meetingOrganizer": {"user": PERSON["user"]},
}
CONTENT = f"{GRAPH}/users/{stand_in.USER_ID}/onlineMeetings/{TEAM}"
SHAPES.update(
    {
        "/me/onlineMeetings/x/attendanceReports/y": {
            "id": TEAM,
            "totalParticipantCount": 3,
            "meetingStartDateTime": "2026-10-28T09:00:00Z",
            "meetingEndDateTime": "2026-10-28T09:10:00Z",
            "attendanceRecords": [
                {
                    "id": TEAM,
                    "emailAddress": stand_in.UPN,
                    "totalAttendanceInSeconds": 540,
                    "role": "Presenter",
                    "identity": IDENTITY,
                    "attendanceIntervals": [
                        {
                            "joinDateTime": "2026-10-28T09:00:00Z",
                            "leaveDateTime": "2026-10-28T09:09:00Z",
                            "durationInSeconds": 540,
                        }
                    ],
                }
            ],
        },
        "/me/onlineMeetings/x/transcripts": {
            "value": [
                {
                    **MEETING_ARTIFACT,
                    "transcriptContentUrl": f"{CONTENT}/transcripts/{TEAM}/content",
                }
            ]
        },
        "/me/onlineMeetings/x/recordings": {
            "value": [
                {**MEETING_ARTIFACT, "recordingContentUrl": f"{CONTENT}/recordings/{TEAM}/content"}
            ]
        },
        "/search/query": {
            "value": [
                {
                    "searchTerms": ["Alpine"],
                    "hitsContainers": [
                        {
                            "total": 3,
                            "moreResultsAvailable": False,
                            "hits": [
                                {
                                    "hitId": POST,
                                    "rank": 1,
                                    "summary": "The <c0>Alpine</c0> Print offer",
                                    "resource": {
                                        "@odata.type": "microsoft.graph.chatMessage",
                                        "id": POST,
                                        "createdDateTime": "2026-10-28T09:00:00Z",
                                        "from": {
                                            "emailAddress": {
                                                "name": "Mia Keller",
                                                "address": stand_in.UPN,
                                            }
                                        },
                                        "chatId": CHAT,
                                        "channelIdentity": {"teamId": TEAM, "channelId": CHANNEL},
                                        "webLink": "https://teams.microsoft.com/l/message/x/1",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        f"/teams/{TEAM}/channels/{CHANNEL}/messages/{POST}/replies": {
            "value": [{**MESSAGE, "replyToId": POST, "chatId": None, "subject": None}]
        },
    }
)
SHAPES[f"/teams/{TEAM}/channels/{TEAM}/messages"] = {
    "@odata.nextLink": f"{GRAPH}/teams/{TEAM}/channels/{TEAM}/messages?$top=50&$skiptoken=abc",
    "value": [
        {
            **MESSAGE,
            "subject": "seed-v1 post p01",
            "chatId": None,
            "channelIdentity": {"teamId": TEAM, "channelId": TEAM},
            "replies": [{**MESSAGE, "replyToId": POST, "chatId": None}],
        }
    ],
}


class TestScrubShapes:
    @pytest.mark.parametrize("path", sorted(SHAPES))
    def test_a_shape_keeps_every_key_and_passes_the_lint(self, path: str) -> None:
        fixture = scrub(recorded((path, SHAPES[path])))
        assert fixture.dropped == {}
        assert lint_files(files_of(fixture)) == []

    @pytest.mark.parametrize("thread", THREADS)
    def test_a_thread_id_keeps_its_suffix_in_every_leaf(self, thread: str) -> None:
        link = f"https://teams.microsoft.com/l/chat/{an_id(thread)}/0?tenantId={stand_in.TENANT_ID}"
        path = f"/chats/{thread}/messages"
        answer = {
            "@odata.nextLink": f"{GRAPH}{path}?$top=5",
            "value": [{"id": thread, "chatType": "group", "webUrl": link}],
        }
        fixture = scrub(recorded((path, answer)))
        files = files_of(fixture)
        assert lint_files(files) == []
        suffix = thread.partition("@")[2]
        assert all(suffix in text.decode() for name, text in files.items() if "meta" not in name)

    def test_a_short_message_id_does_not_rewrite_a_filter(self) -> None:
        fixture = scrub(recorded(*MEETING_LOOKUP))
        assert "%49thread" not in str(fixture.interactions[1]["query"])
        assert '"messageId": "0"' in body_of(fixture, "rec-tool-teams.01").decode()

    def test_a_join_url_in_a_filter_matches_the_join_url_of_the_answer(self) -> None:
        fixture = scrub(recorded(*MEETING_LOOKUP))
        created = cast("dict[str, str]", json.loads(body_of(fixture, "rec-tool-teams.01")))
        joined = created["joinWebUrl"]
        query = cast("dict[str, str]", fixture.interactions[1]["query"])
        assert query["$filter"] == f"JoinWebUrl eq '{joined}'"

    def test_a_meeting_keeps_its_start_time(self) -> None:
        fixture = scrub(recorded(("/me/onlineMeetings", SHAPES["/me/onlineMeetings"])))
        assert "2026-10-29T14:00:00Z" in body_of(fixture, "rec-tool-teams.01").decode()


CREATED_CHAT = "19:Y2hhdGNyZWF0ZWRieXRoZXJ1bm5pbmc@thread.v2"
OTHER_CHAT = "19:Zm9yZWlnbmNoYXRub3Rtb3JlYWQ@thread.v2"
MEMBERSHIP = "MCOrVGKkEno5PZQwMpxcZRO8Ka54QYSfVIhyRGUsDdY0BFY8FQIaMNBmToFfELt5YY="
BOUND = "https://graph.microsoft.com/v1.0/users('{}')"
ANNA_ID = "4c1e8b2a-7d3f-4a96-b5e0-9f2d1c6a8e37"
TOM_ID = "9a7b3d5e-1c2f-4e48-8d6a-0b5c4e3f2a19"
STRANGER_ID = "f0e1d2c3-b4a5-4968-8776-655443322110"


def chat_guard() -> Guard:
    made = guard()
    made.people = frozenset({ANNA_ID, TOM_ID})
    made.created.add(CREATED_CHAT)
    return made


def chat_body(*ids: str, topic: str = "seed-v1 case-teams-chat") -> dict[str, object]:
    members = [{"user@odata.bind": BOUND.format(one), "roles": ["owner"]} for one in ids]
    return {"chatType": "group", "topic": topic, "members": members}


def sent(made: Guard, method: str, path: str, body: object, tool: str) -> str | None:
    return made.refuses_request(ask(method, path, body), tool)


class TestChatWrites:
    def test_a_chat_with_the_test_users_and_a_case_topic_is_allowed(self) -> None:
        made = chat_guard()
        body = chat_body(stand_in.USER_ID, ANNA_ID, TOM_ID)
        assert sent(made, "POST", "/chats", body, "teams_create_chat") is None

    def test_a_chat_with_a_user_who_is_not_a_test_user_is_refused(self) -> None:
        body = chat_body(stand_in.USER_ID, ANNA_ID, STRANGER_ID)
        refusal = sent(chat_guard(), "POST", "/chats", body, "teams_create_chat")
        assert "binds a person that is not a test user" in str(refusal)

    def test_a_chat_with_no_case_topic_or_another_topic_is_refused(self) -> None:
        for topic in ("Weekly sync", "case-teams-chat"):
            body = chat_body(stand_in.USER_ID, ANNA_ID, topic=topic)
            refusal = sent(chat_guard(), "POST", "/chats", body, "teams_create_chat")
            assert "no seed-v1 case- name" in str(refusal)

    def test_a_person_is_bound_by_a_test_users_address_too_and_by_no_other(self) -> None:
        by_address = {"user@odata.bind": BOUND.format(stand_in.UPNS[1]), "roles": ["owner"]}
        body: dict[str, object] = {
            "chatType": "group",
            "topic": "seed-v1 case-x",
            "members": [by_address],
        }
        assert sent(chat_guard(), "POST", "/chats", body, "teams_create_chat") is None
        outside = {"user@odata.bind": BOUND.format("x@outside.example")}
        body["members"] = [outside]
        assert "holds an address that is not a test user" in str(
            sent(chat_guard(), "POST", "/chats", body, "teams_create_chat")
        )

    @pytest.mark.parametrize(
        ("tool", "method", "path", "body"),
        [
            ("teams_rename_chat", "PATCH", "/chats/{}", {"topic": "seed-v1 case-x renamed"}),
            ("teams_send_chat_message", "POST", "/chats/{}/messages", {"body": {"content": "hi"}}),
            (
                "teams_send_chat_message_with_files",
                "POST",
                "/chats/{}/messages",
                {"body": {"content": "hi"}, "attachments": []},
            ),
            (
                "teams_add_chat_member",
                "POST",
                "/chats/{}/members",
                {"user@odata.bind": BOUND.format(TOM_ID), "roles": ["owner"]},
            ),
        ],
    )
    def test_a_write_to_a_chat_needs_a_chat_that_the_run_created(
        self, tool: str, method: str, path: str, body: object
    ) -> None:
        made = chat_guard()
        assert sent(made, method, path.format(an_id(CREATED_CHAT)), body, tool) is None
        refusal = sent(made, method, path.format(an_id(OTHER_CHAT)), body, tool)
        assert "did not create" in str(refusal)

    def test_a_member_is_removed_from_a_created_chat_when_the_member_is_a_test_user(self) -> None:
        made = chat_guard()
        path = f"/chats/{an_id(CREATED_CHAT)}/members/{an_id(MEMBERSHIP)}"
        assert "did not read as seed data" in str(
            sent(made, "DELETE", path, None, "teams_remove_chat_member")
        )
        listed = {
            "value": [
                {"id": MEMBERSHIP, "userId": TOM_ID, "email": stand_in.UPNS[2]},
                {"id": "other-membership", "userId": STRANGER_ID, "email": "x@outside.example"},
            ]
        }
        saw(made, "GET", f"/chats/{an_id(CREATED_CHAT)}/members", 200, listed)
        assert sent(made, "DELETE", path, None, "teams_remove_chat_member") is None
        stranger = f"/chats/{an_id(CREATED_CHAT)}/members/other-membership"
        assert "did not read as seed data" in str(
            sent(made, "DELETE", stranger, None, "teams_remove_chat_member")
        )
        elsewhere = f"/chats/{an_id(OTHER_CHAT)}/members/{an_id(MEMBERSHIP)}"
        assert "did not create" in str(
            sent(made, "DELETE", elsewhere, None, "teams_remove_chat_member")
        )

    def test_a_created_chat_comes_from_a_201_answer_to_the_create(self) -> None:
        made = guard()
        patch = f"/chats/{an_id(CREATED_CHAT)}"
        body = {"topic": "seed-v1 case-x"}
        assert "did not create" in str(sent(made, "PATCH", patch, body, "teams_rename_chat"))
        saw(made, "POST", "/chats", 201, {"id": CREATED_CHAT})
        assert sent(made, "PATCH", patch, body, "teams_rename_chat") is None

    def test_the_chat_globs_belong_to_their_tool_alone(self) -> None:
        made = chat_guard()
        path = f"/chats/{an_id(CREATED_CHAT)}/messages"
        for tool in ("teams_rename_chat", "teams_add_chat_member", "teams_edit_message"):
            assert sent(made, "POST", path, {}, tool) is not None
        assert sent(made, "DELETE", f"/chats/{an_id(CREATED_CHAT)}", None, "teams_rename_chat")

    def test_the_users_of_the_test_users_are_read_at_the_start_and_no_other_user_is(self) -> None:
        made = guard()
        read = ask("GET", f"/users/{quote(stand_in.UPNS[1])}?$select=id")
        assert made.refuses_request(read, "preflight") is None
        stranger = ask("GET", f"/users/{quote('x@outside.example')}?$select=id")
        assert made.refuses_request(stranger, "preflight") is not None
        assert made.refuses_request(read, "teams_list_chats") is not None


ATTACHED: dict[str, object] = {
    "attachments": [{"id": "7f3c9a52-1b8d-4e6a-9c04-2d5e8f1a6b73", "contentType": "reference"}]
}


class TestFilesInAMessage:
    def test_the_id_of_an_attached_file_is_no_destination_in_a_channel(self) -> None:
        path = f"/teams/{TEAM}/channels/{an_id(CHANNEL)}/messages"
        seen = a_guard_that_read_the_seed_team()
        sent_with = seen.refuses_request(
            ask("POST", path, ATTACHED), "teams_send_channel_message_with_files"
        )
        assert sent_with is None

    def test_the_id_of_an_attached_file_is_no_destination_in_a_created_chat(self) -> None:
        path = f"/chats/{an_id(CREATED_CHAT)}/messages"
        assert (
            sent(chat_guard(), "POST", path, ATTACHED, "teams_send_chat_message_with_files") is None
        )

    def test_a_file_message_still_needs_a_channel_or_a_chat_of_this_run(self) -> None:
        elsewhere = f"/teams/{TEAM}/channels/{an_id(STANDARD)}/messages"
        refusal = a_guard_that_read_the_seed_team().refuses_request(
            ask("POST", elsewhere, ATTACHED), "teams_send_channel_message_with_files"
        )
        assert "did not read as seed data" in str(refusal)
        other = f"/chats/{an_id(OTHER_CHAT)}/messages"
        refusal = sent(chat_guard(), "POST", other, ATTACHED, "teams_send_chat_message_with_files")
        assert "did not create" in str(refusal)


def test_the_reaction_case_sends_one_emoji_because_graph_takes_no_name() -> None:
    args = mapping(resolve("teams_react_to_message-post").steps[-1]["args"])
    reaction = str(args["reaction"])
    assert len(reaction) == 1
    assert not reaction.isascii()


CASE_CHAT = "19:Y2FzZWNoYXRyZWFkYnl0aGVydW4xMjM0NTY3OA@thread.v2"
MESSAGE_ID = "1770000000001"
SEED = Path(__file__).resolve().parents[2] / "scripts/dogfood/seed/corpus/teams.yaml"
SEED_TEXT = cast("dict[str, object]", yaml.safe_load(SEED.read_text(encoding="utf-8")))


def a_guard_that_sent_to_a_case_chat() -> Guard:
    seen = guard()
    saw(seen, "GET", "/me/chats", 200, {"value": [{"id": CASE_CHAT, "topic": "seed-v1 case-x"}]})
    saw(seen, "POST", f"/chats/{an_id(CASE_CHAT)}/messages", 201, {"id": MESSAGE_ID})
    return seen


CHAT_MESSAGE = f"/chats/{an_id(CASE_CHAT)}/messages/{MESSAGE_ID}"
REACT = f"{CHAT_MESSAGE}/setReaction"
UNREACT = f"{CHAT_MESSAGE}/unsetReaction"
DELETE = f"/users/{stand_in.USER_ID}{CHAT_MESSAGE}/softDelete"


class TestWritesToAChatMessage:
    @pytest.mark.parametrize(
        ("tool", "path"),
        [
            ("teams_react_to_message", REACT),
            ("teams_react_to_message", UNREACT),
            ("teams_delete_message", DELETE),
        ],
    )
    def test_a_message_that_this_run_sent_to_a_case_chat_takes_the_write_of_its_tool(
        self, tool: str, path: str
    ) -> None:
        assert sent(a_guard_that_sent_to_a_case_chat(), "POST", path, {}, tool) is None

    @pytest.mark.parametrize(
        ("tool", "path"),
        [
            ("teams_react_to_message", DELETE),
            ("teams_delete_message", REACT),
            ("teams_delete_message", UNREACT),
            ("teams_edit_message", REACT),
            ("teams_edit_message", DELETE),
            ("teams_send_chat_message", REACT),
        ],
    )
    def test_the_write_of_one_tool_is_not_a_write_of_a_neighbor(self, tool: str, path: str) -> None:
        assert sent(a_guard_that_sent_to_a_case_chat(), "POST", path, {}, tool) is not None

    def test_a_delete_in_a_chat_needs_the_own_user_path(self) -> None:
        path = f"/chats/{an_id(CASE_CHAT)}/messages/{MESSAGE_ID}/softDelete"
        refusal = sent(a_guard_that_sent_to_a_case_chat(), "POST", path, {}, "teams_delete_message")
        assert "is outside /v1.0/me/" in str(refusal)

    @pytest.mark.parametrize("tool", ["teams_react_to_message", "teams_delete_message"])
    def test_a_chat_that_the_run_did_not_read_as_a_case_chat_is_refused(self, tool: str) -> None:
        made = guard()
        saw(made, "POST", "/chats", 201, {"id": MESSAGE_ID})
        other = an_id(OTHER_CHAT)
        react = f"/chats/{other}/messages/{MESSAGE_ID}/setReaction"
        delete = f"/users/{stand_in.USER_ID}/chats/{other}/messages/{MESSAGE_ID}/softDelete"
        refusal = sent(
            made, "POST", react if tool == "teams_react_to_message" else delete, {}, tool
        )
        assert "did not read as seed data" in str(refusal)

    @pytest.mark.parametrize("tool", ["teams_react_to_message", "teams_delete_message"])
    def test_a_message_of_an_earlier_run_in_a_case_chat_is_refused(self, tool: str) -> None:
        made = guard()
        saw(
            made, "GET", "/me/chats", 200, {"value": [{"id": CASE_CHAT, "topic": "seed-v1 case-x"}]}
        )
        refusal = sent(made, "POST", REACT if "react" in tool else DELETE, {}, tool)
        assert "did not read as seed data" in str(refusal)


NEW_CASES = (
    "teams_list_channels-seed",
    "teams_list_channels-private",
    "teams_get_channel_files_folder-private",
    "teams_browse_channel-posts",
    "teams_browse_channel-long",
    "teams_browse_channel-private",
    "teams_list_message_replies-thread-51",
    "teams_list_message_replies-thread-small",
    "teams_read_message-channel-post",
    "teams_list_chats-unread",
    "teams_list_chat_messages-unread",
    "teams_list_chat_members-send-chat",
    "teams_send_chat_message-mention",
    "teams_send_chat_message_with_files-existing",
    "teams_react_to_message-chat",
    "teams_delete_message-chat",
    "teams_search_messages-alpine",
    "teams_search_messages-lena",
    "teams_search_messages-person-window",
    "teams_read_meeting-attendance",
    "teams_read_transcript-lines",
)


class TestNewCases:
    def corpus_accepts(self, text: str) -> bool:
        return load_corpus().accepts(text)

    def test_every_new_case_exists_and_ends_in_the_tool_of_its_name(self) -> None:
        assert set(NEW_CASES) <= set(CASES)
        for case in NEW_CASES:
            assert case.startswith(f"{tool_of(resolve(case).steps[-1])}-")

    def test_every_string_that_a_new_case_expects_or_selects_is_corpus_text(self) -> None:
        for case in NEW_CASES:
            given = json.dumps(resolve(case).steps, ensure_ascii=False)
            wanted = cast(
                "list[str]", re.findall(r"(?:display_name|subject|speaker)=([^\]]+)\]", given)
            )
            for step in resolve(case).steps:
                expected = mapping(mapping(step.get("expect", {})).get("result", {}))
                wanted += [one for one in expected.values() if isinstance(one, str)]
            for text in wanted:
                assert self.corpus_accepts(text), f"{case}: {text!r} is no corpus text"

    def test_a_chat_case_finds_its_chat_by_the_topic_of_the_seed(self) -> None:
        topics = {one["topic"] for one in cast("list[dict[str, str]]", SEED_TEXT["chats"])}
        found: set[str] = set()
        for case in CASES:
            for step in resolve(case).steps:
                if tool_of(step) == "teams_list_chats" and "topic_contains" in mapping(
                    step["args"]
                ):
                    found.add(str(mapping(step["args"])["topic_contains"]))
        assert found
        assert all(any(topic.startswith(one) for topic in topics) for one in found)

    def test_a_search_case_looks_for_words_of_the_seed_posts(self) -> None:
        for case in ("teams_search_messages-alpine", "teams_search_messages-lena"):
            query = str(mapping(resolve(case).steps[-1]["args"])["query"])
            assert self.corpus_accepts(query)
            assert query in json.dumps(SEED_TEXT)

    def test_a_search_case_waits_for_the_seed_and_runs_as_a_read(self) -> None:
        for case in CASES:
            if case.startswith("teams_search_messages-") and case != "teams_search_messages-seed":
                plan = resolve(case)
                assert plan.needs == ("teams-seed-chats",)
                assert not plan.external
                assert len(plan.steps) == 1

    def test_the_chat_writes_of_a_case_run_after_the_reads_and_reach_other_personas(self) -> None:
        for case in (
            "teams_send_chat_message-mention",
            "teams_send_chat_message_with_files-existing",
            "teams_react_to_message-chat",
            "teams_delete_message-chat",
        ):
            assert resolve(case).external
            assert resolve(case).needs[-1] == "teams-seed-chats"

    def test_the_mention_binds_the_id_and_the_name_of_a_member_that_an_earlier_step_listed(
        self,
    ) -> None:
        bound = mapping(resolve("teams_send_chat_message-mention").steps[-1]["bind"])
        mention = mapping(cast("list[object]", bound["mentions"])[0])
        assert set(mention) == {"user_id", "name"}
        assert all(
            str(one).startswith("$prev.members[email=persona:anna]") for one in mention.values()
        )

    def test_the_probe_of_the_seed_chats_reads_a_topic_that_the_seed_creates(self) -> None:
        _, path, minimum = load().probes["teams-seed-chats"]
        topics = {one["topic"] for one in cast("list[dict[str, str]]", SEED_TEXT["chats"])}
        assert minimum == 1
        assert any(f"'{topic}'" in path for topic in topics)
        assert path.startswith("/me/")

    def test_the_probe_of_the_attendance_reads_the_reports_of_the_held_meeting(self) -> None:
        persona, path, minimum = load().probes["teams-meeting-attendance"]
        assert (persona, minimum) == (1, 1)
        assert path == "/me/onlineMeetings/{meeting}/attendanceReports"

    def test_the_transcript_lines_that_a_case_expects_are_lines_that_a_person_reads(self) -> None:
        lines = {
            line
            for spoken in cast("dict[str, list[str]]", SEED_TEXT["transcript"]).values()
            for line in spoken
        }
        expect = mapping(
            mapping(resolve("teams_read_transcript-lines").steps[-1]["expect"])["result"]
        )
        assert {str(v) for v in expect.values() if isinstance(v, str)} <= lines
