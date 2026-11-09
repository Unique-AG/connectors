import functools
import json
from collections.abc import Iterator, Mapping, Sequence
from typing import cast
from urllib.parse import unquote

import httpx
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import (
    BlobResourceContents,
    ElicitRequestFormParams,
    ElicitResult,
    EmbeddedResource,
    InputRequiredResult,
    TextResourceContents,
)
from respx import MockRouter, Route
from respx.models import Call

from office_365_mcp.shared.handles import meeting_uri_for
from tests.e2e.test_scenarios import build_server, patch_obo
from tests.graph_fixtures import recorded_json
from tests.tools.conftest import (
    JOIN_WEB_URL,
    MEETING_ID,
    chat_hit,
    meeting_payload,
    message_payload,
    transcript_payload,
)
from tests.tools.conftest import search_response as teams_hits
from tests.tools.scenarios.support import Person, call, response, serve
from tests.tools.teams_recordings import chat_payload, online_meeting_info

YESTERDAY = "2026-10-29"
TODAY = "2026-10-30"
TOMORROW = "2026-10-31"

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PRICE_LIST = b"PK\x03\x04price list: Standard 100, Premium 180"
PRICE_LIST_SIZE = len(PRICE_LIST)

SEARCH = "/search/query"
BUSY_60_SECONDS = "left alone for 60 seconds"
RETRY_ONCE = "Retry once"
STOP_AND_REPORT = "stop and report it"
SIGN_IN_AGAIN = "Ask the user to sign in to this connector again"
NOTHING_SHARED = "No link was created, and nothing was shared."

SAVED_AS = "seed-v1 case-sharepoint_create_text_file-seed-folder.txt"
ANNA = "anna@example.test"
TOM = "tom@example.test"
TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0001"
ACTION_ITEMS = (
    "Anna sends the offer on Monday.",
    "Tom books the demo room.",
    "Anna updates the plan.",
)
DESIGN_REVIEW = "WEBVTT\n\n" + "\n\n".join(
    f"00:00:{5 * number:02d}.000 --> 00:00:{5 * number + 4:02d}.000\n<v {speaker}>{item}</v>"
    for number, (speaker, item) in enumerate(
        zip(("Anna Meier", "Tom Berger", "Anna Meier"), ACTION_ITEMS, strict=True), start=1
    )
)


def _fault(status: int, body: str, **headers: str) -> httpx.Response:
    return response({"status": status, "body": body, "headers": headers})


def _busy(seconds: int = 30) -> httpx.Response:
    return _fault(429, "error.TooManyRequests.json", **{"Retry-After": str(seconds)})


def _refused() -> httpx.Response:
    return _fault(403, "error.accessDenied.json")


def _failure(kind: str) -> httpx.Response | Exception:
    match kind:
        case "fails-with-an-internal-error":
            return _fault(500, "error.generalException.json")
        case "no-answer-in-time":
            return httpx.ReadTimeout("no answer in time")
        case _:
            return response(
                {
                    "status": 200,
                    "headers": {"Content-Type": "text/html"},
                    "body": "page.notData.html",
                }
            )


THREE_FAILURES = ["fails-with-an-internal-error", "no-answer-in-time", "unreadable-answer"]


def _fresh(graph: MockRouter, name: str) -> dict[tuple[str, str], Route]:
    graph.routes.clear()
    return serve(graph, f"rec-tool-{name}")


def _requests(graph: MockRouter) -> list[tuple[str, str]]:
    return [
        (made.request.method, made.request.url.path) for made in cast("Sequence[Call]", graph.calls)
    ]


def _nothing_was_sent(graph: MockRouter) -> bool:
    return not [path for method, path in _requests(graph) if method == "POST" and "/send" in path]


def _list(result: Mapping[str, object], key: str) -> Sequence[Mapping[str, object]]:
    return cast("Sequence[Mapping[str, object]]", result[key])


def _sent_json(route: Route) -> Mapping[str, object]:
    return cast("Mapping[str, object]", json.loads(route.calls.last.request.content))


@functools.cache
def _server() -> FastMCP[None]:
    return build_server()


async def _todays_events(graph: MockRouter) -> Mapping[str, object]:
    _ = _fresh(graph, "outlook_list_events-today")
    return await call("outlook_list_events", starts_on=YESTERDAY, ends_on=TODAY)


async def _event_named(graph: MockRouter, fixture: str, subject: str) -> Mapping[str, object]:
    _ = _fresh(graph, fixture)
    found = await call(
        "outlook_list_events", starts_on=YESTERDAY, ends_on=TODAY, subject_contains=subject
    )
    return await call("outlook_read_event", uri=_list(found, "events")[0]["uri"])


async def _newest_mail(graph: MockRouter) -> Mapping[str, object]:
    _ = _fresh(graph, "outlook_list_mail-inbox")
    return await call("outlook_list_mail", folder="inbox", category="seed-v1", limit=3)


async def _budget_mail(graph: MockRouter) -> Mapping[str, object]:
    _ = _fresh(graph, "outlook_search_mail-budget")
    return await call("outlook_search_mail", query="Q3 budget review", category="seed-v1", limit=5)


async def _read_mail(graph: MockRouter, uri: object) -> Mapping[str, object]:
    _ = _fresh(graph, "outlook_read_mail-latest")
    return await call("outlook_read_mail", uri=uri)


async def _thread(graph: MockRouter) -> Mapping[str, object]:
    _ = _fresh(graph, "outlook_read_thread-relaunch")
    listed = await call("outlook_list_mail", folder="inbox", category="Website", limit=1)
    return await call("outlook_read_thread", uri=_list(listed, "messages")[0]["uri"])


async def _plan_file(graph: MockRouter) -> Mapping[str, object]:
    _ = _fresh(graph, "sharepoint_read_file-docx")
    found = await call("sharepoint_search_files", query="seed-v1 Project Plan")
    return _list(found, "files")[0]


def _stores_file(
    graph: MockRouter, uri: str, *, size: int = PRICE_LIST_SIZE, status: int = 200
) -> Route:
    _, _, drive, item = uri.rsplit("/", 3)
    path = f"/drives/{drive}/items/{item}"
    _ = graph.get(path).mock(
        return_value=httpx.Response(
            status,
            json={
                "id": unquote(item),
                "name": "Price list.docx",
                "size": size,
                "webUrl": "https://contoso.sharepoint.example/Price%20list.docx",
                "file": {"mimeType": DOCX},
                "parentReference": {"driveId": unquote(drive)},
            },
        )
    )
    return graph.get(f"{path}/content").mock(return_value=httpx.Response(200, content=PRICE_LIST))


async def _read_file(uri: str) -> EmbeddedResource:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        async with Client(FastMCPTransport(_server()), mode="legacy") as client:
            answer = await client.call_tool("sharepoint_read_file", {"file": uri})
    (block,) = answer.content
    assert isinstance(block, EmbeddedResource)
    return block


def _patched(routes: Mapping[tuple[str, str], Route]) -> Route:
    return next(route for (method, _), route in routes.items() if method == "PATCH")


def _draft(graph: MockRouter) -> Route:
    return _fresh(graph, "outlook_draft_mail-basic")[("POST", "/me/messages")]


class TestMiaStartsHerDayWithOneOverview:
    async def test_it_gives_the_meetings_and_the_newest_mail_with_the_count_of_unread_mail(
        self, graph: MockRouter
    ) -> None:
        meetings = await _todays_events(graph)
        mail = await _newest_mail(graph)

        assert [row["subject"] for row in _list(meetings, "events")][:3] == [
            "Company holiday",
            "Daily standup",
            "Offsite agenda review",
        ]
        received = [cast("str", row["received_at"]) for row in _list(mail, "messages")]
        assert received == sorted(received, reverse=True)
        assert mail["unread_items"] == 23
        assert _list(mail, "messages")[0]["sender"] == {"name": "Anna Meier", "address": ANNA}

    async def test_it_gives_the_attendees_of_a_meeting_it_reads(self, graph: MockRouter) -> None:
        meeting = await _event_named(
            graph, "outlook_suggest_meeting_times-tomorrow", "Hosting review"
        )

        assert meeting["subject"] == "Hosting review"
        assert _list(meeting, "attendees")[0]["address"] == ANNA

    async def test_it_reads_the_mail_first_and_then_the_calendar(self, graph: MockRouter) -> None:
        found = await _newest_mail(graph)
        mail = await _read_mail(graph, _list(found, "messages")[0]["uri"])
        meetings = await _todays_events(graph)
        agenda = await _event_named(graph, "outlook_read_event-agenda", "Offsite agenda review")

        assert (
            mail["body"]
            == "Accepted. I attach the final numbers. Please check line 7 before Thursday.\r\n"
        )
        assert agenda["start"] == {
            "local": "2026-10-29T10:00:00.0000000",
            "time_zone": "UTC",
            "iso": "2026-10-29T10:00:00+00:00",
        }
        assert "Offsite agenda review" in [row["subject"] for row in _list(meetings, "events")]
        paths = [path for _, path in _requests(graph)]
        assert paths.index("/v1.0/me/calendar") > min(
            n for n, path in enumerate(paths) if path.startswith("/v1.0/me/messages/")
        )


class TestAnInvitationIsNeverAnsweredWithoutMia:
    async def test_it_shows_the_invitation_of_anna_in_the_inbox_and_sends_no_answer(
        self, graph: MockRouter
    ) -> None:
        _ = _fresh(graph, "outlook_list_mail-inbox")

        mail = await call("outlook_list_mail", folder="inbox", unread_only=True, limit=5)

        (invitation,) = [
            row for row in _list(mail, "messages") if row["subject"] == "Roadmap check"
        ]
        assert invitation["sender"] == {"name": "Anna Meier", "address": ANNA}
        assert invitation["is_read"] is False
        assert [(method, path) for method, path in _requests(graph) if method != "GET"] == []

    async def test_it_sends_no_answer_to_the_organizer_when_mia_declines(
        self, graph: MockRouter
    ) -> None:
        routes = _fresh(graph, "outlook_read_event-agenda")
        found = await call(
            "outlook_list_events",
            starts_on=YESTERDAY,
            ends_on=TODAY,
            subject_contains="Offsite agenda review",
        )
        event_path = next(path for _, path in routes if path.count("/events/") == 1)
        answered = graph.post(f"{event_path}/accept").mock(return_value=httpx.Response(202))
        person = Person(approval="no")

        with pytest.raises(ToolError, match="did not agree"):
            _ = await call(
                "outlook_respond_to_invite",
                person=person,
                uri=_list(found, "events")[0]["uri"],
                response="accept",
            )

        assert len(person.asked) == 1
        assert not answered.called


class TestAReplyUsesADocumentFromSharePoint:
    async def test_it_drafts_the_reply_with_the_price_list_and_sends_nothing(
        self, graph: MockRouter
    ) -> None:
        question = await _budget_mail(graph)
        mail = await _read_mail(graph, _list(question, "messages")[0]["uri"])
        plan = await _plan_file(graph)
        price_list = await _read_file(cast("str", plan["uri"]))
        routes = _fresh(graph, "outlook_draft_reply-reply")
        draft = await call(
            "outlook_draft_reply",
            message_ref=mail["uri"],
            mode="reply",
            body="The Standard list price is 100.",
            categories=["seed-v1 case-outlook_draft_reply-reply"],
        )

        assert _list(question, "messages")[0]["uri"] == mail["uri"]
        assert isinstance(price_list.resource, BlobResourceContents)
        assert price_list.resource.mime_type == DOCX
        written = cast("Mapping[str, Mapping[str, str]]", _sent_json(_patched(routes)))
        assert "The Standard list price is 100." in written["body"]["content"]
        assert draft["mode"] == "reply"
        assert draft["to"] == [{"name": "Anna Meier", "address": ANNA}]
        assert _nothing_was_sent(graph)


def _asked_before_each_call(route: Route, person: Person) -> list[int]:
    answers = cast("Iterator[httpx.Response]", route.side_effect)
    seen: list[int] = []

    def answer(request: httpx.Request) -> httpx.Response:
        _ = request
        seen.append(len(person.asked))
        return next(answers)

    _ = route.mock(side_effect=answer)
    return seen


def _teams_message(*, attachment_url: str | None = None) -> Mapping[str, object]:
    attachments = (
        [
            {
                "id": "a1",
                "contentType": "reference",
                "contentUrl": attachment_url,
                "name": "Offer.docx",
            }
        ]
        if attachment_url
        else []
    )
    return message_payload(
        message_id="1770000000001", content="<p>Acme renewal</p>", attachments=attachments
    )


def _teams_has_a_message(graph: MockRouter, *, attachment_url: str | None = None) -> None:
    _ = graph.post(SEARCH).mock(
        return_value=httpx.Response(
            200,
            json=teams_hits(
                [chat_hit(chat_id="19:acme@thread.v2", message_id="1770000000001", summary="Acme")]
            ),
        )
    )
    _ = graph.get("/chats/19%3Aacme%40thread.v2/messages/1770000000001").mock(
        return_value=httpx.Response(200, json=_teams_message(attachment_url=attachment_url))
    )


class TestAThreadLeadsToATimeForAWorkshop:
    async def test_it_asks_for_a_time_for_everyone_in_the_thread_and_names_the_free_times(
        self, graph: MockRouter
    ) -> None:
        thread = await _thread(graph)
        others = sorted(
            {
                cast("Mapping[str, str]", row["sender"])["address"]
                for row in _list(thread, "messages")
            }
            - {"mia@example.test"}
        )
        graph.routes.clear()
        slot = {"dateTime": "2026-11-03T10:00:00.0000000", "timeZone": "Europe/Zurich"}
        found = graph.post("/me/findMeetingTimes").mock(
            return_value=httpx.Response(
                200,
                json={
                    "emptySuggestionsReason": "",
                    "meetingTimeSuggestions": [
                        {
                            "confidence": 100.0,
                            "order": 1,
                            "organizerAvailability": "free",
                            "attendeeAvailability": [
                                {
                                    "availability": "free",
                                    "attendee": {"emailAddress": {"address": a}},
                                }
                                for a in others
                            ],
                            "locations": [],
                            "meetingTimeSlot": {
                                "start": slot,
                                "end": slot | {"dateTime": "2026-11-03T11:30:00.0000000"},
                            },
                        }
                    ],
                },
            )
        )

        suggested = await call(
            "outlook_suggest_meeting_times",
            attendees=others,
            starts_at="2026-11-02T08:00:00",
            ends_at="2026-11-06T18:00:00",
            time_zone="Europe/Zurich",
            duration_minutes=90,
        )

        assert others == [ANNA, TOM]
        sent = _sent_json(found)
        assert [
            row["emailAddress"] for row in cast("Sequence[Mapping[str, object]]", sent["attendees"])
        ] == [
            {"address": ANNA},
            {"address": TOM},
        ]
        assert sent["meetingDuration"] == "PT90M"
        (slot_found,) = _list(suggested, "suggestions")
        assert (
            cast("Mapping[str, str]", slot_found["start"])["local"] == "2026-11-03T10:00:00.0000000"
        )
        assert (
            cast("Mapping[str, str]", slot_found["end"])["local"] == "2026-11-03T11:30:00.0000000"
        )
        assert [row["availability"] for row in _list(slot_found, "attendees")] == ["free", "free"]


class TestAMeetingIsPreparedFromItsInvitationMailAndFiles:
    async def test_it_gathers_the_time_the_attendees_the_mail_and_the_deck(
        self, graph: MockRouter
    ) -> None:
        meeting = await _event_named(
            graph, "outlook_suggest_meeting_times-tomorrow", "Hosting review"
        )
        thread = await _thread(graph)
        plan = await _plan_file(graph)
        deck = await _read_file(cast("str", plan["uri"]))

        assert meeting["start"] == {
            "local": "2026-10-29T13:00:00.0000000",
            "time_zone": "UTC",
            "iso": "2026-10-29T13:00:00+00:00",
        }
        assert [row["address"] for row in _list(meeting, "attendees")] == [ANNA]
        assert _list(thread, "messages")[0]["subject"] == "Website relaunch: launch checklist"
        assert plan["name"] == "seed-v1 Project Plan.docx"
        assert isinstance(deck.resource, BlobResourceContents)
        assert deck.resource.mime_type == DOCX


class TestEverythingAboutOneCustomerIsGathered:
    async def test_it_gathers_the_mail_the_teams_message_and_the_file(
        self, graph: MockRouter
    ) -> None:
        mail = await _budget_mail(graph)
        plan = await _plan_file(graph)
        graph.routes.clear()
        _teams_has_a_message(graph)
        hits = await call("teams_search_messages", query="Acme")
        message = await call("teams_read_message", uri=_list(hits, "messages")[0]["uri"])

        assert _list(mail, "messages")[0]["subject"] == "RE: Q3 budget review"
        assert _list(hits, "messages")[0]["chat_id"] == "19:acme@thread.v2"
        assert message["body"] == "<p>Acme renewal</p>"
        assert plan["name"] == "seed-v1 Project Plan.docx"


class TestADecisionFromAChatBecomesAMailDraft:
    async def test_it_drafts_the_decision_to_both_people_and_sends_nothing(
        self, graph: MockRouter
    ) -> None:
        _ = _fresh(graph, "teams_list_chat_messages-first")
        chats = await call("teams_list_chats", limit=5, include_member_emails=True)
        chat = _list(chats, "chats")[0]["chat_id"]
        said = await call("teams_list_chat_messages", chat_id=chat, limit=10)
        created = _draft(graph)

        draft = await call(
            "outlook_draft_mail",
            to=[ANNA],
            cc=[TOM],
            subject="The launch moves to 14 June",
            body="The launch moves to 14 June.",
        )

        assert _list(said, "messages")[0]["chat_id"] == chat
        sent = _sent_json(created)
        assert sent["subject"] == "The launch moves to 14 June"
        assert "The launch moves to 14 June." in cast("Mapping[str, str]", sent["body"])["content"]
        assert [
            row["emailAddress"]
            for row in cast("Sequence[Mapping[str, object]]", sent["toRecipients"])
        ] == [{"address": ANNA}]
        assert [
            row["emailAddress"]
            for row in cast("Sequence[Mapping[str, object]]", sent["ccRecipients"])
        ] == [{"address": TOM}]
        assert [row["address"] for row in _list(draft, "to")] == [ANNA]
        assert _nothing_was_sent(graph)


class TestAFileMovesBetweenMailTeamsAndSharePoint:
    async def test_it_puts_a_link_to_the_file_in_the_draft_after_mia_approves_the_link(
        self, graph: MockRouter
    ) -> None:
        plan = await _plan_file(graph)
        routes = _fresh(graph, "sharepoint_create_share_link-plan")
        person = Person()
        created = next(route for (_, path), route in routes.items() if path.endswith("/createLink"))
        asked_before = _asked_before_each_call(created, person)
        link = await call(
            "sharepoint_create_share_link",
            person=person,
            item=plan["uri"],
            access="view",
            audience="organization",
        )
        route = _draft(graph)

        _ = await call(
            "outlook_draft_mail",
            to=[ANNA],
            subject="The price list",
            body=f"Here is the [price list]({link['share_url']}).",
        )

        assert asked_before == [1]
        assert link["access"] == "view"
        sent = _sent_json(route)
        assert cast("str", link["share_url"]) in cast("Mapping[str, str]", sent["body"])["content"]
        assert "attachments" not in sent
        assert _nothing_was_sent(graph)

    async def test_it_saves_the_text_of_a_mail_in_a_folder_after_mia_approves_the_file(
        self, graph: MockRouter
    ) -> None:
        found = await _budget_mail(graph)
        mail = await _read_mail(graph, _list(found, "messages")[0]["uri"])
        plan = await _plan_file(graph)
        folder = cast("str", plan["parent_uri"])
        _ = _fresh(graph, "sharepoint_browse_folder-seed-folder")
        listing = await call("sharepoint_browse_folder", folder=folder, limit=10)
        routes = _fresh(graph, "sharepoint_create_text_file-seed-folder")
        person = Person()
        upload = next(route for (method, _), route in routes.items() if method == "PUT")
        asked_before = _asked_before_each_call(upload, person)

        saved = await call(
            "sharepoint_create_text_file",
            person=person,
            folder=folder,
            name=SAVED_AS,
            content=cast("str", mail["body"]),
        )

        assert _list(listing, "items")
        assert asked_before == [1]
        assert upload.calls.last.request.content == cast("str", mail["body"]).encode()
        assert saved["is_folder"] is False
        assert saved["parent_uri"] == folder

    async def test_it_reads_a_file_that_a_teams_message_links(self, graph: MockRouter) -> None:
        plan = await _plan_file(graph)
        graph.routes.clear()
        _teams_has_a_message(graph, attachment_url=cast("str", plan["web_url"]))
        hits = await call("teams_search_messages", query="Offer")
        message = await call("teams_read_message", uri=_list(hits, "messages")[0]["uri"])
        (attached,) = _list(message, "attachments")
        _ = _fresh(graph, "sharepoint_resolve_url-plan")
        resolved = await call("sharepoint_resolve_url", url=attached["url"])
        _ = _stores_file(graph, cast("str", resolved["uri"]))
        offer = await _read_file(cast("str", resolved["uri"]))

        assert attached["name"] == "Offer.docx"
        assert resolved["name"] == "seed-v1 Project Plan.docx"
        assert isinstance(offer.resource, BlobResourceContents)
        assert offer.resource.mime_type == DOCX

    async def test_it_resolves_a_file_that_a_chat_shows_as_a_reference_attachment(
        self, graph: MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-sharepoint_read_file-teams-attachment")
        listed = await call(
            "teams_list_chat_messages", chat_id="19:5s8q5t4ig507874f4l06948227913531@thread.v2"
        )
        (attached,) = _list(_list(listed, "messages")[0], "attachments")
        resolved = await call("sharepoint_resolve_url", url=attached["url"])

        assert attached["content_type"] == "reference"
        assert resolved["name"] == "seed-v1 Meeting Notes.txt"
        assert str(resolved["uri"]).startswith("sharepoint:///files/")

    async def test_it_reads_a_file_that_anna_shared_with_mia_and_posted_in_a_chat(
        self, graph: MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-sharepoint_read_file-teams-attachment-other-user")
        listed = await call(
            "teams_list_chat_messages", chat_id="19:g71c902v10u17ab7d1qh522v93rhppa3@thread.v2"
        )
        message = _list(listed, "messages")[0]
        (attached,) = _list(message, "attachments")
        resolved = await call("sharepoint_resolve_url", url=attached["url"])
        read = await _read_file(cast("str", resolved["uri"]))

        assert "Anna" in str(message["sender"])
        assert attached["content_type"] == "reference"
        assert (
            resolved["name"] == "seed-v1 case-sharepoint_read_file-teams-attachment-other-user.txt"
        )
        assert isinstance(read.resource, TextResourceContents)
        assert read.resource.text.startswith("Meeting notes, weekly project sync.")


class TestABriefSaysWhichPartItCouldNotRead:
    async def test_it_gives_the_meetings_when_the_mail_does_not_answer(
        self, graph: MockRouter
    ) -> None:
        meetings = await _todays_events(graph)
        routes = _fresh(graph, "outlook_list_mail-inbox")
        _ = routes[("GET", "/me/mailFolders/inbox")].mock(side_effect=httpx.ReadTimeout)

        with pytest.raises(ToolError, match=RETRY_ONCE):
            _ = await call("outlook_list_mail", folder="inbox", category="seed-v1", limit=3)

        assert _list(meetings, "events")[1]["subject"] == "Daily standup"

    async def test_it_gives_the_mail_and_its_unread_count_when_the_calendar_is_refused(
        self, graph: MockRouter
    ) -> None:
        mail = await _newest_mail(graph)
        routes = _fresh(graph, "outlook_list_events-today")
        _ = routes[("GET", "/me/calendar")].mock(return_value=_refused())

        with pytest.raises(ToolError, match="Ask a Microsoft 365 administrator"):
            _ = await call("outlook_list_events", starts_on=YESTERDAY, ends_on=TODAY)

        assert mail["unread_items"] == 23


class TestAReplyThatNeedsAPriceListSaysWhenItCouldNotReadTheList:
    async def test_it_returns_no_part_of_a_file_over_ten_megabytes(self, graph: MockRouter) -> None:
        plan = await _plan_file(graph)
        graph.routes.clear()
        content = _stores_file(graph, cast("str", plan["uri"]), size=11 * 1024 * 1024)

        with pytest.raises(ToolError, match=r"11\.0 MB.*cannot return a file this large"):
            _ = await _read_file(cast("str", plan["uri"]))

        assert not content.called
        assert _nothing_was_sent(graph)

    async def test_it_sends_the_assistant_back_to_search_when_microsoft_no_longer_finds_the_file(
        self, graph: MockRouter
    ) -> None:
        plan = await _plan_file(graph)
        graph.routes.clear()
        _ = _stores_file(graph, cast("str", plan["uri"]), status=404)

        with pytest.raises(ToolError, match="Search again with sharepoint_search_files"):
            _ = await _read_file(cast("str", plan["uri"]))

        assert _nothing_was_sent(graph)


class TestAMeetingIsPreparedEvenWhenItsDeckCannotBeRead:
    async def test_it_keeps_the_meeting_and_the_mail_when_the_deck_is_gone(
        self, graph: MockRouter
    ) -> None:
        meeting = await _event_named(
            graph, "outlook_suggest_meeting_times-tomorrow", "Hosting review"
        )
        mail = await _budget_mail(graph)
        plan = await _plan_file(graph)
        graph.routes.clear()
        _ = _stores_file(graph, cast("str", plan["uri"]), status=404)

        with pytest.raises(ToolError, match="Search again with sharepoint_search_files"):
            _ = await _read_file(cast("str", plan["uri"]))

        assert meeting["subject"] == "Hosting review"
        assert _list(mail, "messages")[0]["subject"] == "RE: Q3 budget review"


class TestASearchAcrossThreePlacesSaysWhichPlaceItCouldNotSearch:
    @staticmethod
    def _sources(
        graph: MockRouter,
        *,
        teams: httpx.Response | None = None,
        mail: httpx.Response | Exception | None = None,
        files: httpx.Response | None = None,
    ) -> None:
        routes = _fresh(graph, "outlook_search_mail-budget")
        if mail is not None:
            _ = routes[("GET", "/me/messages")].mock(side_effect=[mail])

        def search(request: httpx.Request) -> httpx.Response:
            kinds = cast(
                "Mapping[str, Sequence[Mapping[str, Sequence[str]]]]", json.loads(request.content)
            )
            if "chatMessage" in kinds["requests"][0]["entityTypes"]:
                return teams or httpx.Response(
                    200,
                    json=teams_hits(
                        [chat_hit(chat_id="19:acme@thread.v2", message_id="1770000000001")]
                    ),
                )
            return files or response(
                {
                    "status": 200,
                    "response_json": recorded_json("rec-tool-sharepoint_search_files-plan.01"),
                }
            )

        _ = graph.post(SEARCH).mock(side_effect=search)

    async def test_it_names_the_mail_and_the_files_when_teams_is_refused(
        self, graph: MockRouter
    ) -> None:
        self._sources(graph, teams=_refused())
        mail = await call("outlook_search_mail", query="Acme", limit=5)
        files = await call("sharepoint_search_files", query="Acme")

        with pytest.raises(ToolError, match="Ask a Microsoft 365 administrator"):
            _ = await call("teams_search_messages", query="Acme")

        assert _list(mail, "messages")[0]["subject"] == "RE: Q3 budget review"
        assert _list(files, "files")[0]["name"] == "seed-v1 Project Plan.docx"

    async def test_it_names_the_teams_message_and_the_files_when_the_mail_does_not_answer(
        self, graph: MockRouter
    ) -> None:
        self._sources(graph, mail=httpx.ReadTimeout("no answer in time"))
        teams = await call("teams_search_messages", query="Acme")
        files = await call("sharepoint_search_files", query="Acme")

        with pytest.raises(ToolError, match=RETRY_ONCE):
            _ = await call("outlook_search_mail", query="Acme", limit=5)

        assert _list(teams, "messages")[0]["chat_id"] == "19:acme@thread.v2"
        assert _list(files, "files")[0]["name"] == "seed-v1 Project Plan.docx"

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_it_names_the_mail_and_the_teams_message_when_the_files_stay_busy(
        self, graph: MockRouter
    ) -> None:
        self._sources(graph, files=_busy(60))
        mail = await call("outlook_search_mail", query="Acme", limit=5)
        teams = await call("teams_search_messages", query="Acme")

        with pytest.raises(ToolError, match=BUSY_60_SECONDS):
            _ = await call("sharepoint_search_files", query="Acme")

        assert _list(mail, "messages")[0]["subject"] == "RE: Q3 budget review"
        assert _list(teams, "messages")[0]["chat_id"] == "19:acme@thread.v2"


class TestATimeIsNeverOfferedAsFreeForAPersonWhoseCalendarCannotBeRead:
    async def test_it_marks_the_row_of_the_unreadable_calendar_and_shows_the_other_as_free(
        self, graph: MockRouter
    ) -> None:
        routes = _fresh(graph, "outlook_check_availability-tomorrow")
        schedule = routes[("POST", "/me/calendar/getSchedule")]
        _ = schedule.mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {"scheduleId": ANNA, "availabilityView": "0" * 20, "scheduleItems": []},
                        {
                            "scheduleId": TOM,
                            "availabilityView": "",
                            "scheduleItems": [],
                            "error": {
                                "responseCode": "ErrorFreeBusyDataUnavailable",
                                "message": "No access",
                            },
                        },
                    ]
                },
            )
        )

        found = await call(
            "outlook_check_availability",
            addresses=[ANNA, TOM],
            starts_at="2026-11-03T08:00:00",
            ends_at="2026-11-03T18:00:00",
            time_zone="Europe/Zurich",
        )

        anna, tom = _list(found, "schedules")
        assert anna["error"] is None
        assert set(cast("str", anna["availability_view"])) == {"0"}
        assert cast("Mapping[str, object]", tom["error"])["message"] == "No access"
        assert "0" not in cast("str", tom["availability_view"] or "")


class TestActionItemsFromATranscriptBecomeAMailDraft:
    async def test_it_drafts_the_three_action_items_to_the_person_the_directory_found(
        self, graph: MockRouter
    ) -> None:
        created = _draft(graph)
        _ = graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        chat_payload(
                            "19:meeting_TjAwMDAwMDAwMDAwMA@thread.v2",
                            chat_type="meeting",
                            topic="Design review",
                            online_meeting_info=online_meeting_info(),
                        )
                    ]
                },
            )
        )
        _ = graph.get("/me/onlineMeetings").mock(
            return_value=httpx.Response(200, json={"value": [meeting_payload()]})
        )
        _ = graph.get(f"/me/onlineMeetings/{MEETING_ID}/transcripts").mock(
            return_value=httpx.Response(200, json={"value": [transcript_payload()]})
        )
        _ = graph.get(f"/me/onlineMeetings/{MEETING_ID}/transcripts/{TRANSCRIPT_ID}/content").mock(
            return_value=httpx.Response(200, content=DESIGN_REVIEW.encode())
        )
        _ = graph.get("/me").mock(
            return_value=httpx.Response(200, json={"id": "me", "mail": "mia@example.test"})
        )
        _ = graph.get("/me/people").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": ANNA,
                            "displayName": "Anna Meier",
                            "scoredEmailAddresses": [{"address": ANNA, "relevanceScore": 9}],
                            "personType": {"class": "Person", "subclass": "OrganizationUser"},
                        }
                    ]
                },
            )
        )

        chats = await call("teams_list_chats", chat_type="meeting", topic_contains="Design review")
        meeting = _list(chats, "chats")[0]["meeting_uri"]
        listed = await call("teams_list_meeting_transcripts", meeting_uri=meeting)
        read = await call("teams_read_transcript", uri=_list(listed, "transcripts")[0]["uri"])
        found = await call("outlook_find_recipient", query="Anna Meier", limit=5)
        items = [cast("str", turn["text"]) for turn in _list(read, "turns")]
        draft = await call(
            "outlook_draft_mail",
            to=[cast("str", _list(found, "candidates")[0]["address"])],
            subject="Action items of the Design review",
            body="\n".join(f"- {item}" for item in items),
        )

        assert tuple(items) == ACTION_ITEMS
        body = cast("Mapping[str, str]", _sent_json(created)["body"])["content"]
        assert all(item in body for item in ACTION_ITEMS)
        assert [row["address"] for row in _list(draft, "to")] == [ANNA]
        assert _nothing_was_sent(graph)


class TestADecisionIsNotDraftedWhenTheChatCannotBeRead:
    async def test_it_tells_the_assistant_to_ask_for_the_access_when_the_chats_are_refused(
        self, graph: MockRouter
    ) -> None:
        routes = _fresh(graph, "teams_list_chats-all")
        _ = routes[("GET", "/me/chats")].mock(return_value=_refused())

        with pytest.raises(ToolError, match="Ask a Microsoft 365 administrator"):
            _ = await call("teams_list_chats", limit=10, include_member_emails=True)

        assert [path for method, path in _requests(graph) if method == "POST"] == []


class TestActionItemsAreNotDraftedWhenTheCompanySwitchedTranscriptsOff:
    async def test_it_says_that_an_administrator_must_allow_transcripts(
        self, graph: MockRouter
    ) -> None:
        meeting = meeting_uri_for(JOIN_WEB_URL)
        _ = graph.get("/me/onlineMeetings").mock(
            return_value=httpx.Response(200, json={"value": [meeting_payload()]})
        )
        _ = graph.get(url__regex=r".*/transcripts$").mock(
            return_value=httpx.Response(
                403,
                json={
                    "error": {
                        "code": "Forbidden",
                        "message": "Transcript access is disabled.",
                        "innerError": {"code": "GraphAccessToTranscriptsDisabled"},
                    }
                },
            )
        )

        with pytest.raises(ToolError) as refused:
            _ = await call("teams_list_meeting_transcripts", meeting_uri=meeting)

        assert "switched OFF" in str(refused.value)
        assert "NOT a consent problem" in str(refused.value)
        assert _nothing_was_sent(graph)


class TestAMailThatMicrosoftDoesNotReturnIsNotReportedAsUnsent:
    async def test_it_says_the_tool_failed_to_read_the_mail_and_creates_no_file(
        self, graph: MockRouter
    ) -> None:
        found = await _budget_mail(graph)
        graph.routes.clear()
        mail = cast("str", _list(found, "messages")[0]["uri"]).removeprefix("outlook:///messages/")
        _ = graph.get(f"/me/messages/{mail}").mock(
            return_value=_fault(404, "error.ErrorItemNotFound.json")
        )

        with pytest.raises(ToolError) as refused:
            _ = await call("outlook_read_mail", uri=_list(found, "messages")[0]["uri"])

        assert "failed to read the message, never that it was never sent" in str(refused.value)
        assert [
            method for method, _ in _requests(graph) if method in {"PUT", "PATCH", "DELETE"}
        ] == []
        assert _nothing_was_sent(graph)


class TestAFileThatAnnaPostedIsNotDescribedWhenMiaCannotOpenIt:
    async def test_it_asks_mia_to_open_the_link_in_a_browser_first(self, graph: MockRouter) -> None:
        plan = await _plan_file(graph)
        graph.routes.clear()
        _teams_has_a_message(graph, attachment_url=cast("str", plan["web_url"]))
        hits = await call("teams_search_messages", query="Offer")
        message = await call("teams_read_message", uri=_list(hits, "messages")[0]["uri"])
        routes = _fresh(graph, "sharepoint_resolve_url-plan")
        share = next(path for _, path in routes if path.startswith("/shares/"))
        _ = routes[("GET", share)].mock(return_value=_refused())

        with pytest.raises(ToolError) as refused:
            _ = await call("sharepoint_resolve_url", url=_list(message, "attachments")[0]["url"])

        assert "Ask the user to open the link in a browser" in str(refused.value)
        assert "does not accept the sharing invitation" in str(refused.value)


class TestASharingLinkNeedsMiasClearAgreement:
    async def test_it_creates_no_link_when_mia_declines(self, graph: MockRouter) -> None:
        plan = await _plan_file(graph)
        routes = _fresh(graph, "sharepoint_create_share_link-plan")
        person = Person(approval="no")

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "sharepoint_create_share_link", person=person, item=plan["uri"], access="view"
            )

        assert NOTHING_SHARED in str(refused.value)
        assert len(person.asked) == 1
        assert [
            route.called for (_, path), route in routes.items() if path.endswith("/createLink")
        ] == [False]

    async def test_it_creates_no_link_when_the_question_gets_an_error_for_an_answer(
        self, graph: MockRouter
    ) -> None:
        plan = await _plan_file(graph)
        routes = _fresh(graph, "sharepoint_create_share_link-plan")
        person = Person(approval="unanswered")

        with pytest.raises(ToolError) as refused:
            _ = await call(
                "sharepoint_create_share_link", person=person, item=plan["uri"], access="view"
            )

        assert NOTHING_SHARED in str(refused.value)
        assert "received no answer" in str(refused.value)
        assert "make the same request again" in str(refused.value)
        assert [
            route.called for (_, path), route in routes.items() if path.endswith("/createLink")
        ] == [False]

    @pytest.mark.parametrize(
        ("tool", "approved", "attempted"),
        [
            pytest.param(
                "sharepoint_create_share_link",
                {"access": "view", "audience": "organization"},
                {"access": "edit", "audience": "organization"},
                id="a-link-that-also-changes-the-file",
            ),
            pytest.param(
                "sharepoint_create_share_link",
                {"access": "view", "audience": "organization"},
                {"access": "view", "audience": "anonymous"},
                id="a-link-for-anyone",
            ),
            pytest.param(
                "sharepoint_create_text_file",
                {"name": SAVED_AS, "content": "The terms of the offer."},
                {"name": SAVED_AS, "content": "Other text."},
                id="a-file-with-another-text",
            ),
            pytest.param(
                "sharepoint_create_text_file",
                {"name": SAVED_AS, "content": "The terms of the offer."},
                {"name": "Offer terms 2.txt", "content": "The terms of the offer."},
                id="a-file-with-another-name",
            ),
        ],
    )
    async def test_it_rejects_an_approval_that_was_given_for_something_else(
        self,
        graph: MockRouter,
        tool: str,
        approved: Mapping[str, str],
        attempted: Mapping[str, str],
    ) -> None:
        plan = await _plan_file(graph)
        target = {
            "sharepoint_create_share_link": ("item", plan["uri"]),
            "sharepoint_create_text_file": ("folder", plan["parent_uri"]),
        }[tool]
        routes = _fresh(
            graph,
            "sharepoint_create_share_link-plan"
            if tool == "sharepoint_create_share_link"
            else "sharepoint_create_text_file-seed-folder",
        )

        with pytest.MonkeyPatch.context() as patch:
            patch_obo(patch)
            async with Client(FastMCPTransport(_server())) as client:
                first = await client.session.call_tool(
                    tool, {target[0]: target[1]} | dict(approved), allow_input_required=True
                )
                assert isinstance(first, InputRequiredResult)
                (key,) = first.input_requests or {}
                question = (first.input_requests or {})[key].params
                assert isinstance(question, ElicitRequestFormParams)
                yes = cast(
                    "Sequence[str]", question.requested_schema["properties"]["value"]["enum"]
                )[0]
                with pytest.raises(MCPError, match="Invalid or expired requestState"):
                    _ = await client.session.call_tool(
                        tool,
                        {target[0]: target[1]} | dict(attempted),
                        input_responses={
                            key: ElicitResult(action="accept", content={"value": yes})
                        },
                        request_state=first.request_state,
                        allow_input_required=True,
                    )

        writes = [
            route
            for (method, _), route in routes.items()
            if method in {"PUT"} or _.endswith("/createLink")
        ]
        assert [route.called for route in writes] == [False]


class TestALinkThatMicrosoftFailsIsAskedForOnceMoreAndThenReported:
    @pytest.mark.parametrize("failure", THREE_FAILURES)
    async def test_it_asks_mia_again_and_then_reports_that_it_could_not_create_the_link(
        self, graph: MockRouter, failure: str
    ) -> None:
        plan = await _plan_file(graph)
        routes = _fresh(graph, "sharepoint_create_share_link-plan")
        created = next(route for (_, path), route in routes.items() if path.endswith("/createLink"))
        _ = created.mock(side_effect=[_failure(failure), _failure(failure)])
        person = Person()

        with pytest.raises(ToolError, match=RETRY_ONCE):
            _ = await call(
                "sharepoint_create_share_link", person=person, item=plan["uri"], access="view"
            )
        with pytest.raises(ToolError, match=STOP_AND_REPORT):
            _ = await call(
                "sharepoint_create_share_link", person=person, item=plan["uri"], access="view"
            )

        assert len(person.asked) == 2
        assert _nothing_was_sent(graph)
        assert ("POST", "/v1.0/me/messages") not in _requests(graph)
