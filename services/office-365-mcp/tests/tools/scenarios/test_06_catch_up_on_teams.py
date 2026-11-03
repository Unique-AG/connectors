import json
from collections.abc import Mapping
from datetime import UTC, datetime, tzinfo
from typing import Self, cast, override
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from office_365_mcp.shared import meetings
from office_365_mcp.shared.handles import meeting_uri_for
from office_365_mcp.tools import teams_read_transcript as transcript_reader
from tests.tools.conftest import (
    JOIN_WEB_URL,
    ME,
    MEETING_ID,
    channel_hit,
    chat_hit,
    meeting_payload,
    message_payload,
    reaction_payload,
    recording_payload,
    search_response,
    transcript_payload,
)
from tests.tools.scenarios.support import Person, call, serve
from tests.tools.teams_recordings import aad_member, chat_payload, online_meeting_info

type Row = Mapping[str, object]

TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
CHANNEL_ID = "19:releases@thread.tacv2"
MEETING_CHAT_ID = "19:meeting_TjAwMDAwMDAwMDAwMA@thread.v2"
TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0001"
OTHER_TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0002"
MEETING_URI = meeting_uri_for(JOIN_WEB_URL)
CONTENT_PATH = f"/me/onlineMeetings/{MEETING_ID}/transcripts/{TRANSCRIPT_ID}/content"
TRANSCRIPTS_PATH = f"/me/onlineMeetings/{MEETING_ID}/transcripts"
CHANNEL_MESSAGES_PATH = f"/teams/{TEAM_ID}/channels/{CHANNEL_ID.replace(':', '%3A')}/messages"
TRANSCRIPT_URI = f"teams:///transcripts/{MEETING_ID}/{TRANSCRIPT_ID}"
CHANNEL_POST_URI = f"teams:///teams/{TEAM_ID}/channels/{quote(CHANNEL_ID, safe='')}/messages"

DESIGN_REVIEW = """WEBVTT

00:00:05.000 --> 00:00:09.000
<v Anna Meier>Let us ship the new layout on Friday.</v>

00:00:10.000 --> 00:00:14.000
<v Tom Berger>I will send the offer to the customer.</v>
"""


def _stamp(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}.000"


def _the_clock_reads(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    class Frozen(datetime):
        @override
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls.fromtimestamp(moment.timestamp(), tz)

    monkeypatch.setattr(meetings, "datetime", Frozen)


def _rows(result: Row, key: str) -> list[Row]:
    return cast("list[Row]", result[key])


def _uncalled(routes: Mapping[tuple[str, str], respx.Route]) -> list[tuple[str, str]]:
    return [key for key, route in routes.items() if not route.called]


def _row(value: object) -> Row:
    return cast("Row", value)


async def _refused(tool: str, /, **arguments: object) -> str:
    with pytest.raises(ToolError) as raised:
        _ = await call(tool, person=None, **arguments)
    return str(raised.value)


def _chats_are(graph: respx.MockRouter, *chats: Row) -> respx.Route:
    return graph.get("/me/chats").mock(
        return_value=httpx.Response(200, json={"value": [dict(chat) for chat in chats]})
    )


def _design_review_chat() -> Row:
    return chat_payload(
        MEETING_CHAT_ID,
        chat_type="meeting",
        topic="Design review",
        online_meeting_info=online_meeting_info(),
    )


def _the_meeting_has(
    graph: respx.MockRouter, *transcripts: Row, meeting: Row | None = None
) -> respx.Route:
    graph.get("/me/onlineMeetings").mock(
        return_value=httpx.Response(200, json={"value": [dict(meeting or meeting_payload())]})
    )
    return graph.get(TRANSCRIPTS_PATH).mock(
        return_value=httpx.Response(200, json={"value": [dict(one) for one in transcripts]})
    )


def _the_transcript_says(graph: respx.MockRouter, vtt: str = DESIGN_REVIEW) -> respx.Route:
    return graph.get(CONTENT_PATH).mock(return_value=httpx.Response(200, content=vtt.encode()))


async def _list_transcripts() -> Row:
    return await call("teams_list_meeting_transcripts", meeting_uri=MEETING_URI)


def _error(code: str, message: str) -> Row:
    return {"error": {"code": code, "message": message}}


def _query_sent(route: respx.Route) -> str:
    body = cast("Row", json.loads(route.calls.last.request.content))
    request = cast("Row", cast("list[object]", body["requests"])[0])
    return cast("str", cast("Row", request["query"])["queryString"])


class TestWhichChatsNeedMia:
    async def test_it_shows_a_chat_without_a_title_by_its_members(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-teams_list_chats-all")

        result = await call("teams_list_chats", include_member_emails=True, limit=10)

        titled, untitled = _rows(result, "chats")[:2]
        assert titled["topic"] is not None and titled["members"] is None
        assert untitled["topic"] is None
        assert {member["display_name"] for member in _rows(untitled, "members")} == {
            "Mia Keller",
            "synthetic text 03",
        }

    async def test_it_marks_a_crowded_chat_whose_members_may_be_cut(
        self, graph: respx.MockRouter
    ) -> None:
        crowded = chat_payload(
            "19:crowd@thread.v2",
            topic=None,
            members=[aad_member(f"Member {n}") for n in range(25)],
        )
        small = chat_payload(
            "19:small@thread.v2", topic=None, members=[aad_member("Anna Meier"), aad_member("Tom")]
        )
        _ = _chats_are(graph, crowded, small)

        result = await call("teams_list_chats", chat_type="group")

        crowded_row, small_row = _rows(result, "chats")
        assert len(_rows(crowded_row, "members")) == 25
        assert crowded_row["members_may_be_incomplete"] is True
        assert small_row["members_may_be_incomplete"] is False

    @pytest.mark.parametrize("count", [25, 40])
    async def test_it_names_every_member_that_microsoft_listed_and_warns(
        self, graph: respx.MockRouter, count: int
    ) -> None:
        crowded = chat_payload(
            "19:crowd@thread.v2",
            topic=None,
            members=[aad_member(f"Member {n}") for n in range(count)],
        )
        _ = _chats_are(graph, crowded)

        (row,) = _rows(await call("teams_list_chats", chat_type="group"), "chats")

        assert len(_rows(row, "members")) == count
        assert row["members_may_be_incomplete"] is True

    async def test_it_reports_that_chats_beyond_the_newest_fifty_may_exist(
        self, graph: respx.MockRouter
    ) -> None:
        sent = "2026-02-11T09:15:22Z"
        chats = [
            chat_payload(
                f"19:chat{n}@thread.v2",
                last_message_at=sent,
                last_read_at="2026-02-11T09:00:00Z" if n < 4 else "2026-02-11T09:30:00Z",
            )
            for n in range(50)
        ]
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": chats,
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/chats?$skiptoken=more",
                },
            )
        )

        result = await call("teams_list_chats", limit=50)

        rows = _rows(result, "chats")
        assert len(rows) == 50
        assert [row["unread"] for row in rows].count(True) == 4
        assert result["capped"] is True

    async def test_it_says_the_list_is_complete_when_no_older_chat_exists(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_list_chats-all")

        result = await call("teams_list_chats", limit=50)

        assert _uncalled(routes) == []
        assert len(_rows(result, "chats")) == 3
        assert result["capped"] is False

    async def test_it_finds_unread_posts_of_channels_through_the_read_state_search(
        self, graph: respx.MockRouter
    ) -> None:
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response(
                    [
                        channel_hit(message_id="1770000000001"),
                        channel_hit(message_id="1770000000002"),
                    ]
                ),
            )
        )

        result = await call("teams_search_messages", is_read=False)

        posts = _rows(result, "messages")
        assert [post["message_id"] for post in posts] == ["1770000000001", "1770000000002"]
        assert all(post["team_id"] == TEAM_ID and post["sender"] for post in posts)
        assert "IsRead:false" in _query_sent(route)


class TestFindingAMessage:
    async def test_it_finds_a_topic_in_a_chat_and_in_a_channel(
        self, graph: respx.MockRouter
    ) -> None:
        tom = {"emailAddress": {"name": "Tom Berger", "address": "tom@example.invalid"}}
        priya = {"emailAddress": {"name": "Priya Rao", "address": "priya@example.invalid"}}
        hits = [
            chat_hit(chat_id="19:tom-and-mia@thread.v2", message_id="1", sender=tom),
            channel_hit(team_id=TEAM_ID, channel_id="19:sales@thread.tacv2", message_id="2"),
        ]
        hits[1]["resource"] = {**cast("Row", hits[1]["resource"]), "from": priya}
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response(hits))
        )

        result = await call("teams_search_messages", query="pricing change")

        in_chat, in_channel = _rows(result, "messages")
        assert (_row(in_chat["sender"])["display_name"], in_chat["chat_id"]) == (
            "Tom Berger",
            "19:tom-and-mia@thread.v2",
        )
        assert (_row(in_channel["sender"])["display_name"], in_channel["channel_id"]) == (
            "Priya Rao",
            "19:sales@thread.tacv2",
        )
        assert "pricing change" in _query_sent(route)

    async def test_it_reads_a_hit_in_full(self, graph: respx.MockRouter) -> None:
        _ = graph.post("/search/query").mock(
            return_value=httpx.Response(
                200, json=search_response([chat_hit(chat_id="19:release@thread.v2")])
            )
        )
        _ = graph.get("/chats/19%3Arelease%40thread.v2/messages/1770000000000").mock(
            return_value=httpx.Response(200, json=message_payload(content="cut it on Friday"))
        )
        hit = _rows(await call("teams_search_messages", query="release"), "messages")[0]

        message = await call("teams_read_message", uri=hit["uri"])

        assert message["body"] == "cut it on Friday"

    async def test_it_searches_for_messages_that_mention_mia(self, graph: respx.MockRouter) -> None:
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(
                200, json=search_response([chat_hit(message_id="1"), channel_hit(message_id="2")])
            )
        )

        result = await call("teams_search_messages", mentions_me=True)

        assert [hit["message_id"] for hit in _rows(result, "messages")] == ["1", "2"]
        assert "IsMentioned:true" in _query_sent(route)

    async def test_it_searches_the_messages_of_one_person_in_a_time_window(
        self, graph: respx.MockRouter
    ) -> None:
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(
                200, json=search_response([chat_hit(message_id="1"), channel_hit(message_id="2")])
            )
        )

        result = await call(
            "teams_search_messages",
            sender="Tom",
            sent_after="2026-02-10",
            sent_before="2026-02-10",
        )

        assert len(_rows(result, "messages")) == 2
        sent = _query_sent(route)
        assert "from:Tom" in sent
        assert "sent>=2026-02-10" in sent and "sent<=2026-02-10" in sent

    async def test_it_refuses_a_search_with_nothing_to_look_for_before_it_asks_microsoft(
        self, graph: respx.MockRouter
    ) -> None:
        message = await _refused("teams_search_messages")

        assert "needs at least one of" in message
        assert not graph.calls

    async def test_it_reports_the_reason_when_microsoft_rejects_the_search(
        self, graph: respx.MockRouter
    ) -> None:
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(400, json=_error("BadRequest", "Unbalanced quote in KQL"))
        )

        message = await _refused("teams_search_messages", query="pricing change")

        assert 'gave this reason: "Unbalanced quote in KQL"' in message
        assert "will fail the same way" in message
        assert route.call_count == 1


NO_HITS_CONTAINER: list[Row] = [{"value": []}, {"value": [{"hitsContainers": []}]}]


class TestSearchingFurther:
    async def test_it_shows_the_full_text_and_the_reactions_of_each_hit_when_mia_asks_for_it(
        self, graph: respx.MockRouter
    ) -> None:
        hits = [chat_hit(message_id="1770000000000"), channel_hit(message_id="1770000000001")]
        _ = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response(hits))
        )
        chat = graph.get("/chats/19%3Arelease%40thread.v2/messages/1770000000000").mock(
            return_value=httpx.Response(
                200,
                json=message_payload(
                    content="cut it on Friday", content_type="text", reactions=[reaction_payload()]
                ),
            )
        )
        channel_path = f"/teams/{TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages"
        channel = graph.get(f"{channel_path}/1770000000001").mock(
            return_value=httpx.Response(
                200, json=message_payload(message_id="1770000000001", content="v2 is out")
            )
        )

        result = await call("teams_search_messages", query="release", include_body=True)

        in_chat, in_channel = _rows(result, "messages")
        assert chat.call_count == 1 and channel.call_count == 1
        assert (in_chat["body"], in_chat["body_is_plain_text"]) == ("cut it on Friday", True)
        assert [one["display_name"] for one in _rows(in_chat, "reactions")] == ["Grace Hopper"]
        assert "v2 is out" in cast("str", in_channel["body"])

    async def test_it_shows_a_hit_without_its_text_when_microsoft_cannot_read_the_message(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.post("/search/query").mock(
            return_value=httpx.Response(
                200, json=search_response([channel_hit(message_id="1770000000001")])
            )
        )
        _ = graph.get(
            f"/teams/{TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/1770000000001"
        ).mock(return_value=httpx.Response(404, json=_error("NotFound", "gone")))

        (hit,) = _rows(
            await call("teams_search_messages", query="v2", include_body=True), "messages"
        )

        assert hit["body"] is None and hit["reactions"] == []

    async def test_it_gives_no_handle_and_reads_no_text_for_a_hit_that_has_no_address(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([chat_hit(chat_id=None)]))
        )

        (hit,) = _rows(
            await call("teams_search_messages", query="v2", include_body=True), "messages"
        )

        assert hit["uri"] is None and hit["body"] is None
        asked = cast("list[tuple[httpx.Request, object]]", list(graph.calls))
        assert [request.method for request, _ in asked] == ["POST"]

    async def test_it_leaves_out_a_hit_that_names_no_sender_or_no_message(
        self, graph: respx.MockRouter
    ) -> None:
        no_message = chat_hit(message_id="3")
        no_message["resource"] = {**cast("Row", no_message["resource"]), "id": None}
        hits = [chat_hit(message_id="1", sender=None), no_message, chat_hit(message_id="2")]
        _ = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response(hits))
        )

        result = await call("teams_search_messages", query="release")

        assert [hit["message_id"] for hit in _rows(result, "messages")] == ["2"]

    @pytest.mark.parametrize("answer", NO_HITS_CONTAINER)
    async def test_it_finds_nothing_when_microsoft_answers_with_no_hits_container(
        self, graph: respx.MockRouter, answer: Row
    ) -> None:
        _ = graph.post("/search/query").mock(return_value=httpx.Response(200, json=answer))

        result = await call("teams_search_messages", query="release")

        assert result["messages"] == [] and result["next_offset"] is None

    @pytest.mark.parametrize(
        ("condition", "expected"),
        [
            ({"recipient": "Anna"}, "to:Anna"),
            (
                {"mentions": "00000000-a6b4-4b6e-8a2b-9e1c3f1e88e1"},
                "mentions:00000000a6b44b6e8a2b9e1c3f1e88e1",
            ),
            ({"has_attachment": True}, "hasAttachment:true"),
            ({"sent_before": "2026-02-10T09:00:00+01:00"}, "sent<=2026-02-10T08:00:00Z"),
        ],
        ids=["to a person", "mentions a person", "with an attachment", "before a moment"],
    )
    async def test_it_narrows_a_search_by_one_more_condition(
        self, graph: respx.MockRouter, condition: Row, expected: str
    ) -> None:
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([chat_hit()]))
        )

        result = await call("teams_search_messages", person=None, query="release", **condition)

        assert len(_rows(result, "messages")) == 1
        assert expected in _query_sent(route)


class TestAChannelWithItsReplies:
    @staticmethod
    def _posts() -> list[Row]:
        replies = [
            message_payload(message_id=f"reply{n}", content=f"reply {n}", reply_to_id="post1")
            for n in range(4)
        ]
        return [
            {**message_payload(message_id="post1", content="v2 is out?"), "replies": replies},
            *(message_payload(message_id=f"post{n}", content=f"post {n}") for n in range(2, 6)),
        ]

    async def test_it_reads_posts_with_their_replies_and_reports_the_posts_it_did_not_read(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-teams_list_channels-all")
        team_id = cast("str", _rows(await call("teams_list_my_teams"), "teams")[0]["team_id"])
        channels = await call("teams_list_channels", team_id=team_id)
        channel_id = cast("str", _rows(channels, "channels")[0]["channel_id"])
        _ = graph.get(f"/teams/{team_id}/channels/{quote(channel_id, safe='')}/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": self._posts(),
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/next",
                },
            )
        )

        result = await call(
            "teams_browse_channel",
            team_id=team_id,
            channel_id=channel_id,
            limit=20,
            include_window_completeness=True,
        )

        messages = _rows(result, "messages")
        assert [message["body"] for message in messages[:5]] == [
            "v2 is out?",
            "reply 0",
            "reply 1",
            "reply 2",
            "reply 3",
        ]
        assert [message["reply_to_id"] for message in messages[1:5]] == ["post1"] * 4
        assert result["more_posts_in_channel"] is True

    async def test_it_has_no_date_bound_so_it_returns_the_older_posts_as_well(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(CHANNEL_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json={"value": self._posts()})
        )

        result = await call(
            "teams_browse_channel", team_id=TEAM_ID, channel_id=CHANNEL_ID, limit=20
        )

        assert len([m for m in _rows(result, "messages") if m["reply_to_id"] is None]) == 5

    async def test_it_reports_a_page_that_held_more_posts_than_the_limit(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(CHANNEL_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json={"value": self._posts()})
        )

        result = await call(
            "teams_browse_channel",
            team_id=TEAM_ID,
            channel_id=CHANNEL_ID,
            limit=3,
            include_window_completeness=True,
        )

        assert result["posts_cut_to_limit"] is True

    async def test_it_reads_a_thread_of_fifty_replies_and_says_that_more_exist(
        self, graph: respx.MockRouter
    ) -> None:
        replies = [message_payload(message_id=f"reply{n}", content=f"reply {n}") for n in range(50)]
        _ = graph.get(f"{CHANNEL_MESSAGES_PATH}/post1/replies").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": replies,
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/next",
                },
            )
        )
        post = f"teams:///teams/{TEAM_ID}/channels/{CHANNEL_ID.replace(':', '%3A')}/messages/post1"

        result = await call("teams_list_message_replies", uri=post, limit=50)

        assert len(_rows(result, "messages")) == 50
        assert result["more_replies"] is True


class TestReadingAChat:
    async def test_it_reads_the_newest_messages_of_a_group_chat_with_their_senders(
        self, graph: respx.MockRouter
    ) -> None:
        _ = serve(graph, "rec-tool-teams_list_chat_messages-first")
        chats = await call("teams_list_chats", chat_type="group", limit=5)
        chat_id = _rows(chats, "chats")[0]["chat_id"]

        result = await call("teams_list_chat_messages", chat_id=chat_id, limit=10)

        messages = _rows(result, "messages")
        (written,) = [m for m in messages if m["event"] is None]
        assert _row(written["sender"])["display_name"]
        assert len(messages) == 5

    async def test_it_says_that_older_messages_exist_when_microsoft_offers_more(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_read_message-chat")
        chats = await call("teams_list_chats", limit=5, include_member_emails=True)
        chat_id = _rows(chats, "chats")[0]["chat_id"]

        result = await call("teams_list_chat_messages", chat_id=chat_id, limit=5)

        newest = _rows(result, "messages")[0]
        opened = await call("teams_read_message", uri=newest["uri"])
        assert _uncalled(routes) == []
        assert len(_rows(result, "messages")) == 5
        assert result["more_messages"] is True
        assert opened["message_id"] == newest["message_id"]

    async def test_it_reads_each_unread_chat_and_names_the_sender_of_each_message(
        self, graph: respx.MockRouter
    ) -> None:
        ids = [f"19:unread{n}@thread.v2" for n in range(3)]
        _ = _chats_are(
            graph,
            *(
                chat_payload(
                    chat_id,
                    last_message_at="2026-02-11T09:15:22Z",
                    last_read_at="2026-02-11T09:00:00Z",
                )
                for chat_id in ids
            ),
        )
        for chat_id in ids:
            _ = graph.get(
                f"/chats/{chat_id.replace(':', '%3A').replace('@', '%40')}/messages"
            ).mock(
                return_value=httpx.Response(
                    200, json={"value": [message_payload(content=f"news of {chat_id}")]}
                )
            )

        unread = [c for c in _rows(await call("teams_list_chats"), "chats") if c["unread"]]
        read = [await call("teams_list_chat_messages", chat_id=chat["chat_id"]) for chat in unread]

        assert len(unread) == 3
        assert [_row(_rows(one, "messages")[0]["sender"])["display_name"] for one in read] == [
            "Ada Lovelace"
        ] * 3
        assert [_rows(one, "messages")[0]["body"] for one in read] == [
            f"news of {chat_id}" for chat_id in ids
        ]


class TestWhatAMeetingSaid:
    async def test_it_gives_who_said_what_in_a_transcript(self, graph: respx.MockRouter) -> None:
        _ = _chats_are(graph, _design_review_chat())
        _ = _the_meeting_has(graph, transcript_payload())
        _ = _the_transcript_says(graph)
        meeting = _rows(await call("teams_list_chats", chat_type="meeting"), "chats")[0]
        listed = await call("teams_list_meeting_transcripts", meeting_uri=meeting["meeting_uri"])
        uri = _rows(listed, "transcripts")[0]["uri"]

        read = await call("teams_read_transcript", uri=uri)

        assert [(turn["speaker"], turn["text"]) for turn in _rows(read, "turns")] == [
            ("Anna Meier", "Let us ship the new layout on Friday."),
            ("Tom Berger", "I will send the offer to the customer."),
        ]

    async def test_it_reads_a_transcript_of_three_hours_to_its_last_decision(
        self, graph: respx.MockRouter
    ) -> None:
        cues = [
            f"{_stamp(second)} --> {_stamp(second + 5)}\n<v Anna Meier>Point at {second}.</v>"
            for second in range(0, 3 * 3600 - 10, 120)
        ]
        decision = (
            f"{_stamp(3 * 3600 - 10)} --> {_stamp(3 * 3600 - 5)}\n<v Tom Berger>We ship v2.</v>"
        )
        _ = _the_transcript_says(graph, "WEBVTT\n\n" + "\n\n".join([*cues, decision]))
        turns: list[Row] = []
        pages = 0
        offset: int | None = 0

        while offset is not None:
            page = await call("teams_read_transcript", uri=TRANSCRIPT_URI, offset=offset, limit=40)
            turns += _rows(page, "turns")
            offset = cast("int | None", page["next_offset"])
            pages += 1

        assert pages == 3
        assert len(turns) == len(cues) + 1
        assert turns[-1]["text"] == "We ship v2."
        assert cast("float", turns[-1]["start_seconds"]) > 2.9 * 3600

    async def test_it_gives_the_summary_from_the_transcript_and_the_message_written_after_it(
        self, graph: respx.MockRouter
    ) -> None:
        _ = _the_meeting_has(graph, transcript_payload())
        _ = _the_transcript_says(graph)
        tom = {"emailAddress": {"name": "Tom Berger", "address": "tom@example.invalid"}}
        _ = graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response([chat_hit(summary="I send the <c0>offer</c0>", sender=tom)]),
            )
        )

        transcript = await call("teams_read_transcript", uri=TRANSCRIPT_URI)
        after = await call("teams_search_messages", query="Design review", sent_after="2026-02-10")

        assert "ship the new layout" in cast("str", _rows(transcript, "turns")[0]["text"])
        assert _row(_rows(after, "messages")[0]["sender"])["display_name"] == "Tom Berger"

    async def test_it_reports_a_meeting_that_nobody_transcribed(
        self, graph: respx.MockRouter
    ) -> None:
        content = _the_meeting_has(graph)

        result = await _list_transcripts()

        assert result["status"] == "not_transcribed"
        assert result["transcripts"] == []
        assert content.call_count == 1

    async def test_it_describes_a_recording_and_gives_none_of_its_content(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))
        _ = graph.get("/me/onlineMeetings").mock(
            return_value=httpx.Response(200, json={"value": [meeting_payload()]})
        )
        recording = recording_payload(
            created_at="2026-02-10T14:02:00Z", ended_at="2026-02-10T14:54:00Z"
        )
        _ = graph.get(f"/me/onlineMeetings/{MEETING_ID}/recordings").mock(
            return_value=httpx.Response(200, json={"value": [recording]})
        )

        result = await call("teams_list_meeting_recordings", meeting_uri=MEETING_URI)

        (row,) = _rows(result, "recordings")
        assert result["status"] == "available"
        assert row["duration_seconds"] == 52 * 60
        assert row["content_access"] == "organizer_only"
        assert row["organizer_user_id"]
        assert set(row) == {
            "recording_id",
            "started_at",
            "ended_at",
            "duration_seconds",
            "content_access",
            "organizer_user_id",
            "content_correlation_id",
        }

    async def test_it_tells_two_dates_of_a_recurring_meeting_apart(
        self, graph: respx.MockRouter
    ) -> None:
        october_5 = transcript_payload(created_at="2026-10-05T10:00:00Z")
        october_12 = transcript_payload(
            transcript_id=OTHER_TRANSCRIPT_ID, created_at="2026-10-12T10:00:00Z"
        )
        _ = _the_meeting_has(graph, october_5, october_12)

        rows = _rows(await _list_transcripts(), "transcripts")

        assert {row["uri"]: str(row["started_at"])[:10] for row in rows} == {
            TRANSCRIPT_URI: "2026-10-05",
            f"teams:///transcripts/{MEETING_ID}/{OTHER_TRANSCRIPT_ID}": "2026-10-12",
        }

    async def test_it_refuses_a_transcript_of_another_call_when_microsoft_drops_the_filter(
        self, graph: respx.MockRouter
    ) -> None:
        other_call = transcript_payload(
            transcript_id=OTHER_TRANSCRIPT_ID, content_correlation_id="another-call"
        )
        _ = _the_meeting_has(graph, other_call)

        message = await _refused(
            "teams_list_meeting_transcripts",
            meeting_uri=MEETING_URI,
            content_correlation_id="bc842d7a-2f6e-4b18-a1c7-73ef91d5c8e3",
        )

        assert "did not apply the filter" in message


class TestATranscriptThatCannotBeUsed:
    async def test_it_reports_a_transcript_that_the_company_switched_off_as_refused(
        self, graph: respx.MockRouter
    ) -> None:
        _ = _the_meeting_has(graph)
        refusal = {
            "error": {
                "code": "Forbidden",
                "message": "disabled",
                "innerError": {"code": "GraphAccessToTranscriptsDisabled"},
            }
        }
        _ = graph.get(TRANSCRIPTS_PATH).mock(return_value=httpx.Response(403, json=refusal))

        message = await _refused("teams_list_meeting_transcripts", meeting_uri=MEETING_URI)

        assert "switched OFF" in message and "administrator has to turn it on" in message
        assert "not_transcribed" not in message

    async def test_it_reports_a_transcript_that_microsoft_no_longer_returns_as_gone(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(CONTENT_PATH).mock(
            return_value=httpx.Response(404, json=_error("NotFound", "gone"))
        )

        message = await _refused("teams_read_transcript", uri=TRANSCRIPT_URI)

        assert "will not return this transcript" in message
        assert "about 60 days" in message

    async def test_it_refuses_a_transcript_of_one_byte_over_100_megabytes_as_too_long(
        self, graph: respx.MockRouter
    ) -> None:
        over = transcript_reader.MAX_TRANSCRIPT_BYTES + 1
        _ = graph.get(CONTENT_PATH).mock(
            return_value=httpx.Response(
                200, content=b"WEBVTT", headers={"content-length": str(over)}
            )
        )

        message = await _refused("teams_read_transcript", uri=TRANSCRIPT_URI)

        assert transcript_reader.MAX_TRANSCRIPT_BYTES == 100 * 1024 * 1024
        assert "too long to read here" in message
        assert "open the meeting in Teams" in message
        assert "no transcript exists" in message and "Do not report" in message

    async def test_it_reads_a_transcript_whose_size_equals_the_ceiling(
        self, graph: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(transcript_reader, "MAX_TRANSCRIPT_BYTES", len(DESIGN_REVIEW.encode()))
        _ = _the_transcript_says(graph)

        read = await call("teams_read_transcript", uri=TRANSCRIPT_URI)

        assert _rows(read, "turns")[-1]["text"] == "I will send the offer to the customer."

    async def test_it_does_not_summarize_a_transcript_that_stops_before_its_declared_end(
        self, graph: respx.MockRouter
    ) -> None:
        declared = len(DESIGN_REVIEW.encode()) * 2
        route = graph.get(CONTENT_PATH).mock(
            return_value=httpx.Response(
                200, content=DESIGN_REVIEW.encode(), headers={"content-length": str(declared)}
            )
        )

        message = await _refused("teams_read_transcript", uri=TRANSCRIPT_URI)

        assert "could not be reached or failed internally" in message
        assert route.called

    async def test_it_reports_a_transcript_that_is_not_ready_after_a_meeting_that_just_ended(
        self, graph: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _the_clock_reads(monkeypatch, datetime(2026, 2, 10, 16, 0, tzinfo=UTC))
        _ = _the_meeting_has(graph)

        result = await _list_transcripts()

        assert result["status"] == "not_ready"
        assert result["transcripts"] == []

    async def test_it_reports_a_meeting_that_microsoft_does_not_show_as_not_found(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/onlineMeetings").mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        listing = graph.get(TRANSCRIPTS_PATH)

        result = await _list_transcripts()

        assert result["status"] == "meeting_not_found"
        assert result["transcripts"] == []
        assert not listing.called


class TestWhenMicrosoftCannotDoWhatMiaAsked:
    async def test_it_tells_mia_to_sign_in_again_and_lists_no_chat(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/chats").mock(
            return_value=httpx.Response(401, json=_error("InvalidAuthenticationToken", "expired"))
        )

        message = await _refused("teams_list_chats")

        assert "sign in to this connector again" in message

    @pytest.mark.parametrize(
        ("problem", "told"),
        [
            (httpx.Response(500, json=_error("InternalServerError", "boom")), "failed internally"),
            (httpx.ReadTimeout("no answer in time"), "failed internally"),
            (
                httpx.Response(200, text="<html>x</html>", headers={"content-type": "text/html"}),
                "failed internally",
            ),
        ],
        ids=["internal-error", "timeout", "unreadable-answer"],
    )
    async def test_it_reports_a_read_that_microsoft_keeps_failing(
        self, graph: respx.MockRouter, problem: httpx.Response | Exception, told: str
    ) -> None:
        _ = (
            graph.get("/me/chats").mock(side_effect=problem)
            if isinstance(problem, Exception)
            else graph.get("/me/chats").mock(return_value=problem)
        )

        message = await _refused("teams_list_chats")

        assert told in message and "Retry once" in message

    async def test_it_reports_a_list_that_keeps_saying_more_follows_and_sends_none(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/chats?$skiptoken=x",
                },
            )
        )

        message = await _refused("teams_list_chats")

        assert "would not finish sending this list" in message

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_it_tells_mia_how_long_to_wait_when_a_channel_keeps_limiting_the_reads(
        self, graph: respx.MockRouter
    ) -> None:
        route = graph.get(CHANNEL_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                429, headers={"Retry-After": "30"}, json=_error("TooManyRequests", "slow")
            )
        )

        message = await _refused("teams_browse_channel", team_id=TEAM_ID, channel_id=CHANNEL_ID)

        assert "30 seconds" in message and "not sooner" in message
        assert route.call_count == 4

    async def test_it_reports_a_chat_that_microsoft_cannot_find_without_saying_it_was_deleted(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/chats/19%3Alaunch%40thread.v2/messages").mock(
            return_value=httpx.Response(404, json=_error("NotFound", "no chat"))
        )

        message = await _refused("teams_list_chat_messages", chat_id="19:launch@thread.v2")

        assert "has no such item" in message and "not allowed to know it exists" in message
        assert "deleted" not in message

    async def test_it_reports_a_channel_folder_that_microsoft_cannot_find_without_calling_it_empty(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(
            f"/teams/{TEAM_ID}/channels/{CHANNEL_ID.replace(':', '%3A')}/filesFolder"
        ).mock(return_value=httpx.Response(404, json=_error("NotFound", "no folder")))

        message = await _refused(
            "teams_get_channel_files_folder", team_id=TEAM_ID, channel_id=CHANNEL_ID
        )

        assert "has no such item" in message
        assert "empty" not in message


class TestAReferenceThatTheAssistantMadeUp:
    @pytest.mark.parametrize(
        ("tool", "arguments", "told"),
        [
            ("teams_read_message", {"uri": "the Launch message"}, "exactly three shapes"),
            ("teams_list_message_replies", {"uri": "the Launch post"}, "post handle has exactly"),
            (
                "teams_list_message_replies",
                {"uri": f"teams:///chats/{quote(MEETING_CHAT_ID, safe='')}/messages/1"},
                "A chat handle is not a post handle",
            ),
            (
                "teams_list_message_replies",
                {"uri": f"{CHANNEL_POST_URI}/1/replies/2"},
                "A reply handle ends in",
            ),
            ("teams_list_meeting_transcripts", {"meeting_uri": "Design review"}, "not this"),
            ("teams_list_meeting_recordings", {"meeting_uri": "Design review"}, "This is not one"),
            ("teams_read_transcript", {"uri": "Design review"}, "different shape"),
        ],
        ids=[
            "message",
            "post",
            "post given as a chat message",
            "post given as a reply",
            "transcripts",
            "recordings",
            "transcript",
        ],
    )
    async def test_it_refuses_a_reference_that_is_not_one_and_asks_microsoft_nothing(
        self, graph: respx.MockRouter, tool: str, arguments: Row, told: str
    ) -> None:
        message = await _refused(tool, **arguments)

        assert told in message
        assert not graph.calls

    @pytest.mark.parametrize(
        ("arguments", "told"),
        [
            ({"from_seconds": 90, "to_seconds": 30}, "from_seconds is later than to_seconds"),
            ({"speaker": "  "}, "A blank speaker filter"),
        ],
        ids=["a window that runs backwards", "a blank speaker"],
    )
    async def test_it_refuses_a_transcript_window_that_cannot_match_a_turn(
        self, graph: respx.MockRouter, arguments: Row, told: str
    ) -> None:
        message = await _refused("teams_read_transcript", uri=TRANSCRIPT_URI, **arguments)

        assert told in message
        assert not graph.calls


class TestTheRecordingsOfAMeeting:
    async def test_it_reports_a_meeting_that_microsoft_does_not_show_as_not_found(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me/onlineMeetings").mock(
            return_value=httpx.Response(200, json={"value": []})
        )

        result = await call("teams_list_meeting_recordings", meeting_uri=MEETING_URI)

        assert result["status"] == "meeting_not_found" and result["recordings"] == []

    @pytest.mark.parametrize(
        ("now", "status"),
        [
            (datetime(2026, 2, 10, 15, 10, tzinfo=UTC), "not_ready"),
            (datetime(2026, 2, 12, 15, 10, tzinfo=UTC), "not_recorded"),
        ],
        ids=["just ended", "ended days ago"],
    )
    async def test_it_tells_a_meeting_that_may_still_get_a_recording_from_one_that_has_none(
        self, graph: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, now: datetime, status: str
    ) -> None:
        _the_clock_reads(monkeypatch, now)
        _ = graph.get("/me/onlineMeetings").mock(
            return_value=httpx.Response(200, json={"value": [meeting_payload()]})
        )
        _ = graph.get(f"/me/onlineMeetings/{MEETING_ID}/recordings").mock(
            return_value=httpx.Response(200, json={"value": []})
        )

        result = await call("teams_list_meeting_recordings", meeting_uri=MEETING_URI)

        assert result["status"] == status and result["recordings"] == []

    async def test_it_says_unknown_when_microsoft_names_no_organizer_and_no_end_for_a_recording(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))
        _ = graph.get("/me/onlineMeetings").mock(
            return_value=httpx.Response(200, json={"value": [meeting_payload()]})
        )
        _ = graph.get(f"/me/onlineMeetings/{MEETING_ID}/recordings").mock(
            return_value=httpx.Response(
                200,
                json={"value": [recording_payload(organizer_user_id=None, ended_at=None)]},
            )
        )

        (row,) = _rows(
            await call("teams_list_meeting_recordings", meeting_uri=MEETING_URI), "recordings"
        )

        assert row["content_access"] == "unknown"
        assert row["organizer_user_id"] is None and row["duration_seconds"] is None


class TestATranscriptThatNeedsAnotherFormat:
    async def test_it_reads_the_text_without_speakers_when_the_company_forbids_speaker_names(
        self, graph: respx.MockRouter
    ) -> None:
        refusal = {
            "error": {
                "code": "Forbidden",
                "message": "no speakers",
                "innerError": {"code": "SpeakerAttributionNotAllowed"},
            }
        }
        plain = "WEBVTT\n\n00:00:05.000 --> 00:00:09.000\nLet us ship the new layout on Friday.\n"
        content = graph.get(CONTENT_PATH).mock(
            side_effect=[
                httpx.Response(403, json=refusal),
                httpx.Response(200, content=plain.encode()),
            ]
        )

        result = await call("teams_read_transcript", uri=TRANSCRIPT_URI)

        assert content.call_count == 2
        assert result["speaker_attribution"] is False
        assert [(turn["speaker"], turn["text"]) for turn in _rows(result, "turns")] == [
            (None, "Let us ship the new layout on Friday.")
        ]

    async def test_it_reports_any_other_refusal_of_the_transcript_without_a_second_try(
        self, graph: respx.MockRouter
    ) -> None:
        refusal = {
            "error": {
                "code": "Forbidden",
                "message": "disabled",
                "innerError": {"code": "GraphAccessToTranscriptsDisabled"},
            }
        }
        content = graph.get(CONTENT_PATH).mock(return_value=httpx.Response(403, json=refusal))

        message = await _refused("teams_read_transcript", uri=TRANSCRIPT_URI)

        assert "switched OFF" in message
        assert content.call_count == 1

    async def test_it_skips_a_turn_that_holds_no_words(self, graph: respx.MockRouter) -> None:
        _ = _the_transcript_says(
            graph,
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Anna Meier></v>\n\n"
            + "00:00:05.000 --> 00:00:09.000\n<v Tom Berger>I send the offer.</v>\n",
        )

        result = await call("teams_read_transcript", uri=TRANSCRIPT_URI)

        assert [(turn["speaker"], turn["text"]) for turn in _rows(result, "turns")] == [
            ("Tom Berger", "I send the offer.")
        ]

    async def test_it_lists_a_transcript_once_when_microsoft_sends_it_on_two_pages(
        self, graph: respx.MockRouter
    ) -> None:
        _ = _the_meeting_has(graph, transcript_payload(), transcript_payload())

        rows = _rows(await _list_transcripts(), "transcripts")

        assert [row["uri"] for row in rows] == [TRANSCRIPT_URI]


class TestWhatTheListsOfTeamsKeepApart:
    async def test_it_reports_no_channels_when_microsoft_ignores_the_kind_asked_for(
        self, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(f"/teams/{TEAM_ID}/channels").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        {"id": CHANNEL_ID, "displayName": "Secret", "membershipType": "private"}
                    ]
                },
            )
        )

        message = await _refused("teams_list_channels", team_id=TEAM_ID, membership_type="standard")

        assert "did not apply the filter" in message

    async def test_it_describes_a_system_event_and_a_post_of_a_bot_in_a_chat(
        self, graph: respx.MockRouter
    ) -> None:
        bot = {"application": {"id": "bot-1", "displayName": "Standup Bot"}}
        nobody = {"user": {"id": None, "displayName": None}}
        added = {"@odata.type": "#microsoft.graph.membersAddedEventMessageDetail"}
        unknown = {"@odata.type": "#microsoft.graph.somethingNewDetail"}
        messages = [
            message_payload(message_id="1", sender=bot, content="stand-up at 9"),
            message_payload(
                message_id="2", sender=None, message_type="systemEventMessage", event_detail=added
            ),
            message_payload(
                message_id="3", sender=None, message_type="systemEventMessage", event_detail=unknown
            ),
            message_payload(
                message_id="4",
                sender=None,
                message_type="systemEventMessage",
                event_detail={"callEnded": None},
            ),
            message_payload(message_id="5", sender=nobody),
        ]
        _ = graph.get(f"/chats/{quote(MEETING_CHAT_ID, safe='')}/messages").mock(
            return_value=httpx.Response(200, json={"value": messages})
        )

        rows = _rows(await call("teams_list_chat_messages", chat_id=MEETING_CHAT_ID), "messages")

        undescribed = "a system event Microsoft Graph sent no detail for"
        assert [row["event"] for row in rows] == [
            None,
            "members added",
            undescribed,
            undescribed,
            undescribed,
        ]
        assert _row(rows[0]["sender"])["display_name"] == "Standup Bot"


class TestOlderMessagesOfAChat:
    @pytest.mark.parametrize(
        ("before", "bound"),
        [("2026-11-04", "2026-11-05T00:00:00Z"), ("2026-11-04T09:30:00Z", "2026-11-04T09:30:01Z")],
        ids=["a day", "a moment"],
    )
    async def test_it_reads_the_messages_sent_before_a_day_or_a_moment(
        self, graph: respx.MockRouter, before: str, bound: str
    ) -> None:
        name = "day" if "T" not in before else "moment"
        routes = serve(graph, f"rec-tool-teams_list_chat_messages-before-{name}")
        chats = await call("teams_list_chats", topic_contains="seed-v1 case-teams-unread")
        chat_id = _rows(chats, "chats")[0]["chat_id"]

        result = await call(
            "teams_list_chat_messages", chat_id=chat_id, limit=10, sent_before=before
        )

        asked = routes[("GET", f"/chats/{chat_id}/messages")].calls.last.request.url.params
        assert asked["$filter"] == f"createdDateTime lt {bound}"
        assert _uncalled(routes) == []
        assert isinstance(result["messages"], list)


class TestAReplyReadByItsOwnReference:
    async def test_it_reads_one_reply_of_a_thread_in_full(self, graph: respx.MockRouter) -> None:
        routes = serve(graph, "rec-tool-teams_read_message-reply")
        teams = _rows(await call("teams_list_my_teams"), "teams")
        team_id = cast(
            "str", next(t for t in teams if t["display_name"] == "seed-v1 team")["team_id"]
        )
        channels = _rows(
            await call("teams_list_channels", team_id=team_id, membership_type="standard"),
            "channels",
        )
        channel_id = next(c for c in channels if c["display_name"] == "seed-v1 Posts")["channel_id"]
        posts = await call("teams_browse_channel", team_id=team_id, channel_id=channel_id, limit=10)
        post = next(m for m in _rows(posts, "messages") if m["subject"] == "seed-v1 post p02")
        replies = await call("teams_list_message_replies", uri=post["uri"])

        reply = await call("teams_read_message", uri=_rows(replies, "messages")[0]["uri"])

        assert _uncalled(routes) == []
        assert reply["body"] == "I bring the hosting costs."
        assert reply["reply_to_id"] == post["message_id"]


class TestAMeetingChatThatHoldsNoJoinAddress:
    async def test_it_lists_the_chat_without_a_meeting_reference(
        self, graph: respx.MockRouter
    ) -> None:
        chat = chat_payload(
            MEETING_CHAT_ID,
            chat_type="meeting",
            topic="Design review",
            online_meeting_info=online_meeting_info(join_web_url=None),
        )
        _ = _chats_are(graph, chat)

        (row,) = _rows(await call("teams_list_chats", chat_type="meeting"), "chats")

        assert row["meeting_uri"] is None


class TestTheReactionsOfAMessage:
    async def test_it_shows_who_reacted_to_a_message_of_a_chat(
        self, graph: respx.MockRouter
    ) -> None:
        routes = serve(graph, "rec-tool-teams_read_message-chat-reacted")
        mia = Person()
        chats = await call("teams_list_chats", topic_contains="seed-v1 case-teams-send")
        sent = await call(
            "teams_send_chat_message",
            person=mia,
            chat_id=_rows(chats, "chats")[0]["chat_id"],
            message="seed-v1 case-teams_read_message-chat-reacted target",
        )
        _ = await call("teams_react_to_message", person=mia, uri=sent["uri"], reaction="\U0001f44d")

        read = await call("teams_read_message", uri=sent["uri"])

        assert _uncalled(routes) == []
        (reaction,) = _rows(read, "reactions")
        assert reaction["user_id"] and reaction["reaction_type"] and reaction["created_at"]
