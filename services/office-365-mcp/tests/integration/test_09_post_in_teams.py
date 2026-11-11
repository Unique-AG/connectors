import json
from collections.abc import Callable, Mapping
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS
from office_365_mcp.shared.handles import DriveFolderHandle, MessageHandle
from tests.integration.conftest import ME, TEAMS_SENDER, message_payload
from tests.integration.support import Person, call, serve
from tests.integration.teams_recordings import new_group_chat
from tests.integration.teams_support import (
    Says,
    call_on_the_newer_protocol,
    refused_on_the_newer_protocol,
)
from tests.integration.test_scenarios import build_server, patch_obo

type Row = Mapping[str, object]

CHAT_ID = "19:release@thread.v2"
CHAT_PATH = f"/chats/{quote(CHAT_ID, safe='')}"
TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
CHANNEL_ID = "19:releases@thread.tacv2"
OWN_MESSAGE_ID = "1770000000000"
POST_ID = "1770000000050"
LAUNCH = "Launch on 14 Jun"
MESSAGE_URI = MessageHandle(OWN_MESSAGE_ID, chat_id=CHAT_ID).uri
THUMBS_UP = "\U0001f44d"

NOTES = "seed-v1 Meeting Notes.txt"
NOTES_GUID = "00000000-4897-4dbd-827c-66309915e60d"
NOTES_URL = (
    "https://contoso-my.sharepoint.com/personal/mia_example_test/Documents/"
    "seed-v1%20Seed%20Files/seed-v1%20Meeting%20Notes.txt"
)

DRIVE_ID = "b!SYNTHETICDRIVE0000"
DECK_ID = "01SYNTHETICFILE0000"
DECK_URI = f"sharepoint:///files/{quote(DRIVE_ID, safe='')}/{DECK_ID}"
DECK_PATH = f"/drives/{quote(DRIVE_ID, safe='')}/items/{DECK_ID}"
DECK_GUID = "153fa47d-18c9-4179-be08-9879815a9f90"
DECK_ETAG = f'"{{{DECK_GUID.upper()}}},3"'
SITE = "https://contoso.sharepoint.invalid/sites/sales/Shared%20Documents"

TOM_ID = "00000000-e469-40d3-8f5b-9a7c5dac541e"
RECORDED_CHAT_ID = "19:1j94t52t92wo3a7601bw9d8vnxk1n7m8@thread.v2"
PRIYA_ID = "00000000-0000-4000-8000-0000000000a9"

NOT_AGREED = "did not agree"
SEED_TEAM = "seed-v1 team"
THREAD_POST = "seed-v1 case-teams_list_message_replies-reply post"
THREAD_REPLY = "seed-v1 case-teams_list_message_replies-reply reply"
HELLO_TEAM = "seed-v1 case-teams_send_channel_message-post hello team"
BEFORE = "seed-v1 case-teams_edit_message-post before"
AFTER = "seed-v1 case-teams_edit_message-post after"
DOOMED = "seed-v1 case-teams_delete_message-post doomed"
TARGET = "seed-v1 case-teams_react_to_message-post target"


def _rows(value: object) -> list[Row]:
    return cast("list[Row]", value)


def _uncalled(routes: Mapping[tuple[str, str], respx.Route]) -> list[tuple[str, str]]:
    return [key for key, route in routes.items() if not route.called]


async def _seed_channel() -> dict[str, str]:
    teams = _rows((await call("teams_list_my_teams"))["teams"])
    team_id = cast("str", next(t for t in teams if t["display_name"] == SEED_TEAM)["team_id"])
    channels = await call("teams_list_channels", team_id=team_id, membership_type="standard")
    return {
        "team_id": team_id,
        "channel_id": cast("str", _rows(channels["channels"])[0]["channel_id"]),
    }


async def _notes_uri() -> str:
    found = await call("sharepoint_search_files", query="seed-v1 Meeting Notes", limit=1)
    return cast("str", _rows(found["files"])[0]["uri"])


async def _refused_by(person: Person | None, tool: str, /, **arguments: object) -> str:
    with pytest.raises(ToolError) as raised:
        _ = await call(tool, person=person, **arguments)
    return str(raised.value)


async def _refused(tool: str, /, **arguments: object) -> str:
    return await _refused_by(None, tool, **arguments)


async def _call_from_a_client_that_cannot_ask(tool: str, **arguments: object) -> str:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        async with Client(
            FastMCPTransport(build_server()),
            mode="legacy",
        ) as client:
            with pytest.raises(ToolError) as raised:
                _ = await client.call_tool(tool, arguments)
    return str(raised.value)


def _error(code: str, message: str) -> Row:
    return {"error": {"code": code, "message": message}}


def _request_body(route: respx.Route) -> Row:
    return cast("Row", json.loads(route.calls.last.request.content))


def _writes(graph: respx.MockRouter) -> respx.Route:
    return graph.route(method__in=["POST", "PATCH", "PUT", "DELETE"]).mock(
        return_value=httpx.Response(204)
    )


def _the_chat_answers_the_post_with(
    graph: respx.MockRouter, answer: httpx.Response | Exception
) -> respx.Route:
    route = graph.post(f"{CHAT_PATH}/messages")
    return (
        route.mock(side_effect=answer)
        if isinstance(answer, Exception)
        else route.mock(return_value=answer)
    )


def _the_message_is(
    graph: respx.MockRouter,
    *,
    content: str = LAUNCH,
    sender: Row | None = TEAMS_SENDER,
    deleted_at: str | None = None,
) -> None:
    _ = graph.get(f"{CHAT_PATH}/messages/{OWN_MESSAGE_ID}").mock(
        return_value=httpx.Response(
            200,
            json=message_payload(
                content=content, content_type="text", sender=sender, deleted_at=deleted_at
            ),
        )
    )
    _ = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))


def _the_deck_is(
    graph: respx.MockRouter,
    *,
    drive_type: str = "documentLibrary",
    facet: Row | None = None,
    etag: str | None = DECK_ETAG,
) -> None:
    _ = graph.get(DECK_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": DECK_ID,
                "name": "Q3 Plan.pptx",
                "eTag": etag,
                "webDavUrl": f"{SITE}/Q3%20Plan.pptx",
                "parentReference": {"driveId": DRIVE_ID, "driveType": drive_type},
                **(facet or {"file": {"mimeType": "application/octet-stream"}}),
            },
        )
    )


def _the_writes_are_answered(graph: respx.MockRouter) -> respx.Route:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH" or request.url.path.endswith(
            ("/softDelete", "/setReaction", "/unsetReaction")
        ):
            return httpx.Response(204)
        return httpx.Response(201, json=message_payload(message_id=POST_ID))

    return graph.route(method__in=["POST", "PATCH", "PUT", "DELETE"]).mock(side_effect=answer)


def _everything_is_readable(
    graph: respx.MockRouter, writes: Callable[[respx.MockRouter], respx.Route] = _writes
) -> respx.Route:
    _the_message_is(graph)
    _the_deck_is(graph)
    return writes(graph)


CHAT_MESSAGE = {"chat_id": CHAT_ID, "message": "The build is green"}
CHANNEL_POST = {"team_id": TEAM_ID, "channel_id": CHANNEL_ID, "message": "v2 ships on Friday"}
WITH_THE_DECK = {"attachments": [DECK_URI]}
WITH_FILES = [
    ("teams_send_channel_message_with_files", CHANNEL_POST),
    ("teams_send_chat_message_with_files", CHAT_MESSAGE),
]
OTHER_SENDER = {
    "user": {
        "@odata.type": "#microsoft.graph.teamworkUserIdentity",
        "id": "00000000-0000-4000-8000-000000000002",
        "displayName": "Grace Hopper",
        "userIdentityType": "aadUser",
    }
}

EVERY_PROPOSAL = [
    pytest.param("teams_send_chat_message", CHAT_MESSAGE, "Nothing was sent.", id="chat-message"),
    pytest.param(
        "teams_send_channel_message", CHANNEL_POST, "Nothing was posted.", id="channel-post"
    ),
    pytest.param(
        "teams_send_chat_message_with_files",
        {**CHAT_MESSAGE, **WITH_THE_DECK},
        "Nothing was sent.",
        id="chat-message-with-file",
    ),
    pytest.param(
        "teams_send_channel_message_with_files",
        {**CHANNEL_POST, **WITH_THE_DECK},
        "Nothing was posted.",
        id="channel-post-with-file",
    ),
    pytest.param(
        "teams_edit_message",
        {"uri": MESSAGE_URI, "message": "Launch on 14 June"},
        "No message was changed.",
        id="correction",
    ),
    pytest.param(
        "teams_delete_message", {"uri": MESSAGE_URI}, "No message was deleted.", id="deletion"
    ),
    pytest.param(
        "teams_react_to_message",
        {"uri": MESSAGE_URI, "reaction": THUMBS_UP},
        "No reaction was changed.",
        id="reaction",
    ),
]


class TestAMessageIsPostedAfterMiaApproves:
    async def test_it_posts_a_chat_message_with_a_mention_of_a_member_after_she_approves(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-teams_list_chat_members-first")
        post = graph.post(f"/chats/{quote(RECORDED_CHAT_ID, safe='')}/messages").mock(
            return_value=httpx.Response(201, json=message_payload(message_id="1770000000001"))
        )
        mia = Person()

        sent = await call(
            "teams_send_chat_message",
            person=mia,
            chat_id=RECORDED_CHAT_ID,
            message="the build is green",
            mentions=[{"user_id": TOM_ID, "name": "Tom Berger"}],
        )

        assert len(mia.asked) == 1 and "Tom Berger" in mia.asked[0] and TOM_ID in mia.asked[0]
        body = _request_body(post)
        mentioned = cast(
            "Row", cast("Row", cast("list[Row]", body["mentions"])[0]["mentioned"])["user"]
        )
        assert mentioned["id"] == TOM_ID
        content = cast("str", cast("Row", body["body"])["content"])
        assert '<at id="0">Tom Berger</at>' in content and "the build is green" in content
        assert sent["chat_id"] == RECORDED_CHAT_ID

    async def test_it_posts_nothing_when_mia_declines(self, graph: respx.MockRouter) -> None:
        writes = _writes(graph)
        mia = Person(approval="no")

        message = await _refused_by(mia, "teams_send_chat_message", **CHAT_MESSAGE)

        assert "Nothing was sent." in message and NOT_AGREED in message
        assert len(mia.asked) == 1
        assert writes.call_count == 0

    async def test_it_does_not_mention_a_person_who_is_not_in_the_chat_and_asks_nobody(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-teams_list_chat_members-first")
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(
            mia,
            "teams_send_chat_message",
            chat_id=RECORDED_CHAT_ID,
            message="please review the plan",
            mentions=[{"user_id": PRIYA_ID, "name": "Priya Rao"}],
        )

        assert (
            f"no named member of this chat for this Microsoft Entra object id: '{PRIYA_ID}'"
            in message
        )
        assert "Nothing was sent." in message
        assert mia.asked == []
        assert writes.call_count == 0

    async def test_it_puts_a_reply_into_the_thread_and_makes_no_new_post(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_list_message_replies-reply")
        channel = await _seed_channel()
        mia = Person()
        post = await call("teams_send_channel_message", person=mia, **channel, message=THREAD_POST)

        reply = await call(
            "teams_send_channel_message",
            person=mia,
            **channel,
            message=THREAD_REPLY,
            reply_to_id=post["message_id"],
        )

        thread = await call("teams_list_message_replies", uri=post["uri"])
        assert _uncalled(routes) == []
        assert THREAD_REPLY in mia.asked[1]
        assert reply["reply_to_id"] == post["message_id"]
        assert [message["body"] for message in _rows(thread["messages"])] == [
            f"<p>{THREAD_REPLY}</p>"
        ]
        channel_path = f"/teams/{channel['team_id']}/channels/{channel['channel_id']}/messages"
        assert _request_body(routes[("POST", f"{channel_path}/{post['message_id']}/replies")])[
            "body"
        ] == {"contentType": "html", "content": f"<p>{THREAD_REPLY}</p>"}
        assert (
            cast("Row", _request_body(routes[("POST", channel_path)])["body"])["content"]
            == f"<p>{THREAD_POST}</p>"
        )

    async def test_it_makes_a_new_top_level_post_after_mia_approves_it(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_send_channel_message-post")
        channel = await _seed_channel()
        mia = Person()

        sent = await call("teams_send_channel_message", person=mia, **channel, message=HELLO_TEAM)

        assert _uncalled(routes) == []
        assert len(mia.asked) == 1 and HELLO_TEAM in mia.asked[0]
        assert sent["reply_to_id"] is None
        assert sent["body"] == f"<p>{HELLO_TEAM}</p>"
        posted = routes[
            ("POST", f"/teams/{channel['team_id']}/channels/{channel['channel_id']}/messages")
        ]
        assert cast("Row", _request_body(posted)["body"])["content"] == f"<p>{HELLO_TEAM}</p>"

    async def test_it_attaches_a_file_that_is_in_sharepoint_to_a_channel_post(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_send_channel_message_with_files-post")
        notes = await _notes_uri()
        channel = await _seed_channel()
        mia = Person()

        _ = await call(
            "teams_send_channel_message_with_files",
            person=mia,
            **channel,
            message="v2 ships on Friday",
            attachments=[notes],
        )

        assert _uncalled(routes) == []
        assert NOTES in mia.asked[0]
        post = routes[
            ("POST", f"/teams/{channel['team_id']}/channels/{channel['channel_id']}/messages")
        ]
        (attachment,) = _rows(_request_body(post)["attachments"])
        assert attachment["name"] == NOTES
        assert attachment["id"] == NOTES_GUID
        assert attachment["contentUrl"] == NOTES_URL
        assert _request_body(post)["body"] == {
            "contentType": "html",
            "content": f'<p>v2 ships on Friday</p> <attachment id="{NOTES_GUID}"></attachment>',
        }

    async def test_it_attaches_a_file_that_is_in_sharepoint_to_a_chat_message(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_send_chat_message_with_files-group")
        notes = await _notes_uri()
        chat_id = (await new_group_chat())["chat_id"]
        mia = Person()

        _ = await call(
            "teams_send_chat_message_with_files",
            person=mia,
            chat_id=chat_id,
            message="The build is green",
            attachments=[notes],
        )

        assert _uncalled(routes) == []
        assert NOTES in mia.asked[0]
        post = routes[("POST", f"/chats/{chat_id}/messages")]
        (attachment,) = _rows(_request_body(post)["attachments"])
        assert attachment["name"] == NOTES
        assert attachment["contentUrl"] == NOTES_URL
        assert _request_body(post)["body"] == {
            "contentType": "html",
            "content": f'<p>The build is green</p> <attachment id="{NOTES_GUID}"></attachment>',
        }

    @pytest.mark.parametrize(("tool", "target"), WITH_FILES, ids=["channel-post", "chat-message"])
    async def test_it_does_not_post_a_file_that_is_in_a_personal_onedrive(
        self, graph: respx.MockRouter, tool: str, target: Row
    ) -> None:
        _the_deck_is(graph, drive_type="personal")
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(mia, tool, **target, **WITH_THE_DECK)

        assert (
            "Microsoft Teams can attach a file only when the file is already in SharePoint"
            in message
        )
        assert mia.asked == [] and writes.call_count == 0


class TestMiaChangesOnlyHerOwnMessages:
    async def test_it_corrects_her_own_message_in_place(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-teams_edit_message-post")
        mia = Person()
        posted = await call(
            "teams_send_channel_message", person=mia, **await _seed_channel(), message=BEFORE
        )

        corrected = await call("teams_edit_message", person=mia, uri=posted["uri"], message=AFTER)

        assert _uncalled(routes) == []
        assert f"'{BEFORE}'" in mia.asked[1] and AFTER in mia.asked[1]
        assert corrected["text"] == AFTER
        assert corrected["uri"] == posted["uri"]

    async def test_it_deletes_her_own_message_after_she_approves_the_deletion(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_delete_message-post")
        mia = Person()
        posted = await call(
            "teams_send_channel_message", person=mia, **await _seed_channel(), message=DOOMED
        )

        deleted = await call("teams_delete_message", person=mia, uri=posted["uri"])

        assert _uncalled(routes) == []
        assert len(mia.asked) == 2 and DOOMED in mia.asked[1]
        assert deleted == {"uri": posted["uri"], "deleted": True}

    async def test_it_gives_a_message_a_thumbs_up_after_she_approves_the_reaction(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_react_to_message-post")
        mia = Person()
        posted = await call(
            "teams_send_channel_message", person=mia, **await _seed_channel(), message=TARGET
        )

        reacted = await call(
            "teams_react_to_message", person=mia, uri=posted["uri"], reaction=THUMBS_UP
        )

        assert _uncalled(routes) == []
        assert len(mia.asked) == 2 and THUMBS_UP in mia.asked[1]
        post_path = f"/teams/{posted['team_id']}/channels/{posted['channel_id']}/messages"
        react = routes[("POST", f"{post_path}/{posted['message_id']}/setReaction")]
        assert _request_body(react)["reactionType"] == THUMBS_UP
        assert reacted["removed"] is False


class TestWhenMicrosoftCannotPostTheMessage:
    async def test_it_tells_mia_to_sign_in_again_and_posts_nothing(
        self, graph: respx.MockRouter
    ) -> None:
        post = _the_chat_answers_the_post_with(
            graph, httpx.Response(401, json=_error("InvalidAuthenticationToken", "expired"))
        )

        message = await _refused("teams_send_chat_message", **CHAT_MESSAGE)

        assert "sign in to this connector again" in message
        assert post.call_count == 1

    async def test_it_tells_mia_that_an_administrator_must_grant_the_access(
        self, graph: respx.MockRouter
    ) -> None:
        _ = _the_chat_answers_the_post_with(
            graph, httpx.Response(403, json=_error("Forbidden", "denied"))
        )

        message = await _refused("teams_send_chat_message", **CHAT_MESSAGE)

        assert "ChatMessage.Send" in message and "administrator" in message

    async def test_it_does_not_report_a_chat_that_microsoft_cannot_find_as_deleted(
        self, graph: respx.MockRouter
    ) -> None:
        _ = _the_chat_answers_the_post_with(
            graph, httpx.Response(404, json=_error("NotFound", "no chat"))
        )

        message = await _refused("teams_send_chat_message", **CHAT_MESSAGE)

        assert "has no such item" in message and "not allowed to know it exists" in message
        assert "deleted" not in message

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_it_tells_mia_how_long_to_wait_and_does_not_ask_again_sooner(
        self, graph: respx.MockRouter
    ) -> None:
        post = _the_chat_answers_the_post_with(
            graph,
            httpx.Response(
                429, headers={"Retry-After": "30"}, json=_error("TooManyRequests", "slow")
            ),
        )

        message = await _refused("teams_send_chat_message", **CHAT_MESSAGE)

        assert "30 seconds" in message and "not sooner" in message
        assert post.call_count == 1

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.Response(500, json=_error("InternalServerError", "boom")),
            httpx.ReadTimeout("no answer in time"),
            httpx.Response(200, text="<html>x</html>", headers={"content-type": "text/html"}),
        ],
        ids=["internal-error", "timeout", "unreadable-answer"],
    )
    async def test_it_does_not_send_a_failed_message_again_before_the_chat_is_checked(
        self, graph: respx.MockRouter, failure: httpx.Response | Exception
    ) -> None:
        post = _the_chat_answers_the_post_with(graph, failure)

        message = await _refused("teams_send_chat_message", **CHAT_MESSAGE)

        assert "does not know if Microsoft 365 made the change" in message
        assert "Do not call this tool again first." in message
        assert "use teams_list_chat_messages" in message
        assert post.call_count == 1

    async def test_it_reports_the_reason_when_microsoft_rejects_the_message(
        self, graph: respx.MockRouter
    ) -> None:
        post = _the_chat_answers_the_post_with(
            graph, httpx.Response(400, json=_error("BadRequest", "The body is not valid"))
        )

        message = await _refused("teams_send_chat_message", **CHAT_MESSAGE)

        assert 'gave this reason: "The body is not valid"' in message
        assert "will fail the same way" in message
        assert post.call_count == 1

    async def test_it_reports_a_rejection_that_comes_without_a_reason_as_one_without_a_reason(
        self, graph: respx.MockRouter
    ) -> None:
        post = _the_chat_answers_the_post_with(
            graph, httpx.Response(400, json={"error": {"code": "BadRequest"}})
        )

        message = await _refused("teams_send_chat_message", **CHAT_MESSAGE)

        assert "it is a bad request" in message and "gave this reason" not in message
        assert "will fail the same way" in message
        assert post.call_count == 1


class TestNothingChangesUnlessMiaClearlyAgrees:
    async def test_it_does_not_post_in_a_channel_when_mia_declines(
        self, graph: respx.MockRouter
    ) -> None:
        writes = _writes(graph)

        message = await _refused_by(
            Person(approval="no"), "teams_send_channel_message", **CHANNEL_POST
        )

        assert "Nothing was posted." in message and NOT_AGREED in message
        assert writes.call_count == 0

    async def test_it_does_not_send_a_message_with_a_file_when_mia_declines(
        self, graph: respx.MockRouter
    ) -> None:
        writes = _everything_is_readable(graph)

        message = await _refused_by(
            Person(approval="no"),
            "teams_send_chat_message_with_files",
            **CHAT_MESSAGE,
            **WITH_THE_DECK,
        )

        assert "Nothing was sent." in message and NOT_AGREED in message
        assert writes.call_count == 0

    @pytest.mark.parametrize(
        ("tool", "arguments", "nothing"),
        EVERY_PROPOSAL[4:],
        ids=["correction", "deletion", "reaction"],
    )
    async def test_it_leaves_a_message_as_it_was_when_mia_declines_the_change(
        self, graph: respx.MockRouter, tool: str, arguments: Row, nothing: str
    ) -> None:
        writes = _everything_is_readable(graph)

        message = await _refused_by(Person(approval="no"), tool, **arguments)

        assert nothing in message and NOT_AGREED in message
        assert writes.call_count == 0

    @pytest.mark.parametrize(("tool", "arguments", "nothing"), EVERY_PROPOSAL)
    async def test_it_changes_nothing_when_the_chat_program_answers_the_question_with_an_error(
        self, graph: respx.MockRouter, tool: str, arguments: Row, nothing: str
    ) -> None:
        writes = _everything_is_readable(graph)

        message = await _refused_by(Person(approval="unanswered"), tool, **arguments)

        assert nothing in message
        assert "received no answer" in message and "can make the same request again" in message
        assert writes.call_count == 0

    async def test_it_sends_nothing_when_the_chat_program_cannot_show_a_question(
        self, graph: respx.MockRouter
    ) -> None:
        writes = _writes(graph)

        message = await _call_from_a_client_that_cannot_ask(
            "teams_send_chat_message", **CHAT_MESSAGE
        )

        assert "Nothing was sent." in message
        assert "their client cannot ask them to agree" in message
        assert "do this task in the Microsoft 365 app" in message
        assert writes.call_count == 0


class TestWhatTeamsCannotTake:
    @pytest.mark.parametrize(
        ("tool", "arguments", "told"),
        [
            (
                "teams_edit_message",
                {"uri": MESSAGE_URI, "message": "Launch on 14 June"},
                "is deleted",
            ),
            ("teams_delete_message", {"uri": MESSAGE_URI}, "already deleted"),
            (
                "teams_react_to_message",
                {"uri": MESSAGE_URI, "reaction": THUMBS_UP},
                "already deleted",
            ),
        ],
        ids=["correction", "deletion", "reaction"],
    )
    async def test_it_does_not_change_a_message_that_is_already_deleted(
        self, graph: respx.MockRouter, tool: str, arguments: Row, told: str
    ) -> None:
        _the_message_is(graph, deleted_at="2026-02-11T10:00:00Z")
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(mia, tool, **arguments)

        assert told in message
        assert mia.asked == [] and writes.call_count == 0

    @pytest.mark.parametrize(
        ("tool", "extra"),
        [
            ("teams_send_channel_message", {}),
            ("teams_send_channel_message_with_files", WITH_THE_DECK),
        ],
        ids=["post", "post-with-file"],
    )
    async def test_it_refuses_a_reply_with_a_subject_and_asks_nobody(
        self, graph: respx.MockRouter, tool: str, extra: Row
    ) -> None:
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(
            mia, tool, **CHANNEL_POST, **extra, reply_to_id=POST_ID, subject="Release news"
        )

        assert "sets a subject only on a new channel post, never on a reply" in message
        assert "omit `reply_to_id`" in message and "omit `subject`" in message
        assert mia.asked == [] and writes.call_count == 0

    @pytest.mark.parametrize(("tool", "target"), WITH_FILES, ids=["channel-post", "chat-message"])
    async def test_it_does_not_attach_a_folder_to_a_post(
        self, graph: respx.MockRouter, tool: str, target: Row
    ) -> None:
        _the_deck_is(graph, facet={"folder": {"childCount": 3}})
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(mia, tool, **target, attachments=[DECK_URI])

        assert "names a folder, and this tool attaches files only" in message
        assert mia.asked == [] and writes.call_count == 0

    @pytest.mark.parametrize(("tool", "target"), WITH_FILES, ids=["channel-post", "chat-message"])
    async def test_it_does_not_attach_a_file_whose_details_microsoft_does_not_send(
        self, graph: respx.MockRouter, tool: str, target: Row
    ) -> None:
        _the_deck_is(graph, etag=None)
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(mia, tool, **target, **WITH_THE_DECK)

        assert "Tell the user to attach the file in Microsoft Teams instead" in message
        assert mia.asked == [] and writes.call_count == 0

    @pytest.mark.parametrize(("tool", "target"), WITH_FILES, ids=["channel-post", "chat-message"])
    async def test_it_does_not_take_a_folder_handle_for_a_file(
        self, graph: respx.MockRouter, tool: str, target: Row
    ) -> None:
        writes = _writes(graph)

        message = await _refused(
            tool, **target, attachments=[DriveFolderHandle(DRIVE_ID, "01SYNTHETICFOLDER0").uri]
        )

        assert "is not a file handle" in message
        assert writes.call_count == 0 and not graph.calls


class TestAChatProgramOfTheNewerKind:
    @pytest.mark.parametrize(("tool", "arguments", "nothing"), EVERY_PROPOSAL)
    async def test_it_makes_an_approved_change_once_when_the_question_comes_in_the_answer(
        self, graph: respx.MockRouter, tool: str, arguments: Row, nothing: str
    ) -> None:
        _ = nothing
        writes = _everything_is_readable(graph, _the_writes_are_answered)
        mia = Person()

        _ = await call_on_the_newer_protocol(tool, person=mia, **arguments)

        assert len(mia.asked) == 1
        assert writes.call_count == 1

    @pytest.mark.parametrize(("tool", "arguments", "nothing"), EVERY_PROPOSAL)
    @pytest.mark.parametrize(
        "reply",
        [Person(approval="no"), Says(1), Says("maybe")],
        ids=["declines", "the word for no", "a word that is no choice"],
    )
    async def test_it_changes_nothing_unless_the_answer_is_the_word_for_yes(
        self, graph: respx.MockRouter, tool: str, arguments: Row, nothing: str, reply: Person | Says
    ) -> None:
        writes = _everything_is_readable(graph, _the_writes_are_answered)

        message = await refused_on_the_newer_protocol(tool, person=reply, **arguments)

        assert nothing in message and NOT_AGREED in message
        assert writes.call_count == 0


class TestAReferenceThatTheAssistantMadeUp:
    @pytest.mark.parametrize(
        ("tool", "arguments"),
        [
            ("teams_edit_message", {"message": "Launch on 14 June"}),
            ("teams_delete_message", {}),
            ("teams_react_to_message", {"reaction": THUMBS_UP}),
        ],
        ids=["correction", "deletion", "reaction"],
    )
    async def test_it_refuses_a_message_reference_that_is_not_one_and_asks_nobody(
        self, graph: respx.MockRouter, tool: str, arguments: Row
    ) -> None:
        mia = Person()

        message = await _refused_by(mia, tool, uri="the Launch message", **arguments)

        assert "exactly three shapes" in message
        assert mia.asked == [] and not graph.calls


class TestWhatMiaMayChangeInAMessage:
    @pytest.mark.parametrize(
        ("tool", "arguments"),
        [
            ("teams_edit_message", {"uri": MESSAGE_URI, "message": "Launch on 14 June"}),
            ("teams_delete_message", {"uri": MESSAGE_URI}),
        ],
        ids=["correction", "deletion"],
    )
    async def test_it_does_not_change_a_message_that_another_person_sent_and_asks_nobody(
        self, graph: respx.MockRouter, tool: str, arguments: Row
    ) -> None:
        _the_message_is(graph, sender=OTHER_SENDER)
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(mia, tool, **arguments)

        assert "only a message that the signed-in user sent" in message
        assert mia.asked == [] and writes.call_count == 0

    async def test_it_does_not_correct_a_message_with_a_mention_of_a_person_who_is_not_in_the_chat(
        self, graph: respx.MockRouter
    ) -> None:
        _the_message_is(graph)
        _ = graph.get(f"{CHAT_PATH}/members").mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(
            mia,
            "teams_edit_message",
            uri=MESSAGE_URI,
            message="Launch on 14 June",
            mentions=[{"user_id": PRIYA_ID, "name": "Priya Rao"}],
        )

        assert (
            f"no named member of this chat for this Microsoft Entra object id: '{PRIYA_ID}'"
            in message
        )
        assert "No message was changed." in message
        assert mia.asked == [] and writes.call_count == 0


class TestAMentionNeedsANamedMemberOfTheChat:
    @staticmethod
    def _the_members_are(graph: respx.MockRouter, *members: Row, more: bool = False) -> None:
        answer: Row = {"value": list(members)}
        if more:
            answer = {**answer, "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"}
        _ = graph.get(f"{CHAT_PATH}/members").mock(return_value=httpx.Response(200, json=answer))

    async def test_it_does_not_mention_a_member_whom_microsoft_names_by_no_user(
        self, graph: respx.MockRouter
    ) -> None:
        self._the_members_are(
            graph,
            {
                "@odata.type": "#microsoft.graph.conversationMember",
                "id": "m1",
                "displayName": "Guest",
            },
            {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "id": "m2",
                "displayName": "Priya Rao",
            },
        )
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(
            mia,
            "teams_send_chat_message",
            **CHAT_MESSAGE,
            mentions=[{"user_id": PRIYA_ID, "name": "Priya Rao"}],
        )

        assert (
            f"no named member of this chat for this Microsoft Entra object id: '{PRIYA_ID}'"
            in message
        )
        assert mia.asked == [] and writes.call_count == 0

    async def test_it_sends_no_file_with_a_mention_of_a_person_who_is_not_a_member(
        self, graph: respx.MockRouter
    ) -> None:
        self._the_members_are(graph)
        writes = _everything_is_readable(graph)
        mia = Person()

        message = await _refused_by(
            mia,
            "teams_send_chat_message_with_files",
            **CHAT_MESSAGE,
            **WITH_THE_DECK,
            mentions=[{"user_id": PRIYA_ID, "name": "Priya Rao"}],
        )

        assert "no named member of this chat" in message and "Nothing was sent." in message
        assert mia.asked == [] and writes.call_count == 0

    async def test_it_says_when_it_read_only_part_of_a_very_large_chat_to_find_the_member(
        self, graph: respx.MockRouter
    ) -> None:
        self._the_members_are(
            graph,
            *(
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "id": f"m{n}",
                    "displayName": f"Member {n}",
                    "userId": f"{n:08d}-0000-4000-8000-000000000000",
                }
                for n in range(MAX_SCANNED_ITEMS)
            ),
            more=True,
        )
        writes = _writes(graph)
        mia = Person()

        message = await _refused_by(
            mia,
            "teams_send_chat_message",
            **CHAT_MESSAGE,
            mentions=[{"user_id": PRIYA_ID, "name": "Priya Rao"}],
        )

        assert f"shows more than {MAX_SCANNED_ITEMS} members of this chat" in message
        assert mia.asked == [] and writes.call_count == 0


async def _seed_chat() -> str:
    chats = await call("teams_list_chats", topic_contains="seed-v1 case-teams-send")
    return cast("str", _rows(chats["chats"])[0]["chat_id"])


async def _post_and_reply(mia: Person, label: str) -> tuple[Row, Row]:
    channel = await _seed_channel()
    post = await call(
        "teams_send_channel_message", person=mia, **channel, message=f"seed-v1 case-{label} post"
    )
    reply = await call(
        "teams_send_channel_message",
        person=mia,
        **channel,
        message=f"seed-v1 case-{label} target",
        reply_to_id=post["message_id"],
    )
    return post, reply


class TestACorrectionInTheChatOrInTheThread:
    async def test_it_corrects_a_message_of_a_chat_in_place(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-teams_edit_message-chat")
        mia = Person()
        chat_id = await _seed_chat()
        sent = await call(
            "teams_send_chat_message",
            person=mia,
            chat_id=chat_id,
            message="seed-v1 case-teams_edit_message-chat before",
        )

        corrected = await call(
            "teams_edit_message",
            person=mia,
            uri=sent["uri"],
            message="seed-v1 case-teams_edit_message-chat after",
        )

        assert _uncalled(routes) == []
        assert corrected["uri"] == sent["uri"]
        patch = routes[("PATCH", f"/chats/{chat_id}/messages/{sent['message_id']}")]
        assert "after" in cast("str", cast("Row", _request_body(patch)["body"])["content"])

    async def test_it_corrects_a_reply_of_a_thread_in_place(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-teams_edit_message-reply")
        mia = Person()
        _post, reply = await _post_and_reply(mia, "teams_edit_message-reply")

        corrected = await call(
            "teams_edit_message",
            person=mia,
            uri=reply["uri"],
            message="seed-v1 case-teams_edit_message-reply after",
        )

        assert _uncalled(routes) == []
        assert corrected["uri"] == reply["uri"]
        assert any(
            verb == "PATCH" and "/replies/" in path and route.called
            for (verb, path), route in routes.items()
        )


class TestAReactionInAChatInAPostAndInAThread:
    async def test_it_takes_a_reaction_back_from_a_chat_message(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_react_to_message-chat-remove")
        mia = Person()
        sent = await call(
            "teams_send_chat_message",
            person=mia,
            chat_id=await _seed_chat(),
            message="seed-v1 case-teams_react_to_message-chat-remove target",
        )
        _ = await call("teams_react_to_message", person=mia, uri=sent["uri"], reaction=THUMBS_UP)

        taken = await call(
            "teams_react_to_message",
            person=mia,
            uri=sent["uri"],
            reaction=THUMBS_UP,
            remove=True,
        )

        assert _uncalled(routes) == []
        assert taken["removed"] is True
        assert THUMBS_UP in mia.asked[-1]

    async def test_it_takes_a_reaction_back_from_a_channel_post(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_react_to_message-post-remove")
        mia = Person()
        post = await call(
            "teams_send_channel_message",
            person=mia,
            **await _seed_channel(),
            message="seed-v1 case-teams_react_to_message-post-remove target",
        )
        _ = await call("teams_react_to_message", person=mia, uri=post["uri"], reaction=THUMBS_UP)

        taken = await call(
            "teams_react_to_message", person=mia, uri=post["uri"], reaction=THUMBS_UP, remove=True
        )

        assert _uncalled(routes) == []
        assert taken["removed"] is True

    async def test_it_gives_a_reply_of_a_thread_a_reaction_and_takes_it_back(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_react_to_message-reply")
        mia = Person()
        _post, reply = await _post_and_reply(mia, "teams_react_to_message-reply")

        added = await call(
            "teams_react_to_message", person=mia, uri=reply["uri"], reaction=THUMBS_UP
        )
        taken = await call(
            "teams_react_to_message",
            person=mia,
            uri=reply["uri"],
            reaction=THUMBS_UP,
            remove=True,
        )

        assert _uncalled(routes) == []
        assert (added["removed"], taken["removed"]) == (False, True)


class TestAFileInAReplyAndAMentionInAPost:
    async def test_it_attaches_a_file_that_is_in_sharepoint_to_a_reply(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_send_channel_message_with_files-reply")
        notes = await _notes_uri()
        channel = await _seed_channel()
        mia = Person()
        post = await call(
            "teams_send_channel_message",
            person=mia,
            **channel,
            message="seed-v1 case-teams_send_channel_message_with_files-reply post",
        )

        reply = await call(
            "teams_send_channel_message_with_files",
            person=mia,
            **channel,
            message="seed-v1 case-teams_send_channel_message_with_files-reply notes",
            attachments=[notes],
            reply_to_id=post["message_id"],
        )

        assert _uncalled(routes) == []
        assert reply["reply_to_id"] == post["message_id"]
        assert NOTES in mia.asked[-1]

    async def test_it_mentions_a_person_in_a_channel_post_after_mia_approves(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_send_channel_message-mention")
        mia = Person()

        sent = await call(
            "teams_send_channel_message",
            person=mia,
            **await _seed_channel(),
            message="seed-v1 case-teams_send_channel_message-mention hello",
            mentions=[{"user_id": TOM_ID, "name": "Tom Berger"}],
        )

        assert _uncalled(routes) == []
        assert "It mentions" in mia.asked[0] and TOM_ID in mia.asked[0]
        assert [one["user_id"] for one in _rows(sent["mentions"])] == [TOM_ID]
