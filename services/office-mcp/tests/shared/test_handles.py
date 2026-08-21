"""The `teams:///` grammar: what round-trips, and what is not a handle of a given family.

The families are separate because the tools and the permissions behind them are, so the negative
assertions are the ones that matter. Every id below is invented.
"""

import pytest

from office_mcp.shared import handles

# Shaped like the ones Graph stores: `%3a` and `%40` already escaped, a `?context=` query holding
# `%7b` and `%22`, and an `&` parameter after it.
JOIN_WEB_URL = (
    "https://teams.microsoft.invalid/l/meetup-join/"
    + "19%3ameeting_TjAwMDAwMDAwMDAwMA%40thread.v2/0"
    + "?context=%7b%22Tid%22%3a%228a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81%22%7d&anon=true"
)

MEETING_ID = "MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"

_TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0001"

_CHAT_ID = "19:release@thread.v2"
_MESSAGE_ID = "1770000000000"
_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"

_CHAT_URI = f"teams:///chats/19%3Arelease%40thread.v2/messages/{_MESSAGE_ID}"
_CHANNEL_URI = (
    f"teams:///teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/{_MESSAGE_ID}"
)

_ROOT_ID = "1760000000000"
_REPLY_URI = (
    f"teams:///teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2"
    + f"/messages/{_ROOT_ID}/replies/{_MESSAGE_ID}"
)

_CHAT_HANDLE = handles.MessageHandle(message_id=_MESSAGE_ID, chat_id=_CHAT_ID)
_CHANNEL_HANDLE = handles.MessageHandle(
    message_id=_MESSAGE_ID, team_id=_TEAM_ID, channel_id=_CHANNEL_ID
)
_REPLY_HANDLE = handles.MessageHandle(
    message_id=_MESSAGE_ID, team_id=_TEAM_ID, channel_id=_CHANNEL_ID, reply_to_id=_ROOT_ID
)


class TestTheMessageHandleGrammar:
    """`search_messages` mints two of these, `browse_channel` the third, and `read_message` reads
    all three back. The grammar is neither tool's: a handle one mints and another 404s on does not
    look like a disagreement."""

    def test_it_reads_the_two_shapes_search_emits_and_decodes_their_ids(self) -> None:
        chat = handles.message_handle(_CHAT_URI)
        channel = handles.message_handle(_CHANNEL_URI)

        assert chat == _CHAT_HANDLE
        assert channel == _CHANNEL_HANDLE

    def test_it_reads_the_reply_shape_that_only_browsing_a_channel_can_mint(self) -> None:
        """Graph addresses a channel reply under the post it answers, and the search projection
        carries no `replyToId`, so a search hit on a reply degrades to the unreadable root-post
        shape; only `browse_channel`, walking post by post, knows each reply's parent."""
        reply = handles.message_handle(_REPLY_URI)

        assert reply == _REPLY_HANDLE
        assert reply is not None and reply.uri == _REPLY_URI

    def test_a_handle_survives_the_round_trip_it_came_from(self) -> None:
        chat = handles.message_handle(_CHAT_URI)
        channel = handles.message_handle(_CHANNEL_URI)

        assert chat is not None and chat.uri == _CHAT_URI
        assert channel is not None and channel.uri == _CHANNEL_URI

    def test_an_unencoded_id_still_resolves(self) -> None:
        """`:` and `@` are unambiguous in a path segment, so a handle copied out of a log, whose
        ids were never encoded, is read too."""
        handle = handles.message_handle(f"teams:///chats/{_CHAT_ID}/messages/{_MESSAGE_ID}")

        assert handle == _CHAT_HANDLE

    def test_it_says_which_permission_each_shape_is_read_under(self) -> None:
        """Graph's read permissions are per surface and only the handle knows which surface, so a
        403 on a chat read can name `Chat.Read` and no permission that was never missing."""
        assert _CHAT_HANDLE.permission == "Chat.Read"
        assert _CHANNEL_HANDLE.permission == "ChannelMessage.Read.All"
        assert _REPLY_HANDLE.permission == "ChannelMessage.Read.All"

    @pytest.mark.parametrize(
        "uri",
        [
            # The schemes a polymorphic reader would advertise and this connector cannot serve.
            "mail:///messages/AAMkAGI2",
            "calendar:///events/AAMkAGI2",
            "drive:///items/01ABC",
            "site:///sites/contoso/pages/1",
            "teams:///chats/19%3Arelease%40thread.v2",
            "teams:///messages/1770000000000",
            "teams:///chats//messages/1770000000000",
            "teams:///chats/19%3Arelease%40thread.v2/messages/",
            # A chat has no replies in Graph's addressing. Only a channel thread does.
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000/replies/1770000000001",
            "teams:///teams/8a9c3c47/channels/19%3Ageneral/messages/1770000000000/replies/",
            "teams:///teams/8a9c3c47/channels/19%3Ageneral/messages//replies/1770000000001",
            "teams:///teams/8a9c3c47/messages/1770000000000",
            "teams:///chats/19%3Arelease%40thread.v2/messages/%20",
            "https://teams.microsoft.invalid/l/message/19%3Ageneral/1770000000000",
            "1770000000000",
            "",
        ],
    )
    def test_it_refuses_everything_else(self, uri: str) -> None:
        assert handles.message_handle(uri) is None


class TestTheHandleGrammar:
    def test_a_meeting_handle_survives_the_join_url_it_carries(self) -> None:
        """It must come back byte-identical: Graph matches a join URL against what it stored,
        character for character."""
        uri = handles.meeting_uri_for(JOIN_WEB_URL)
        assert uri is not None

        parsed = handles.meeting_handle(uri)

        assert parsed is not None
        assert parsed.join_web_url == JOIN_WEB_URL
        assert "/" not in uri.removeprefix("teams:///meetings/"), (
            "the join URL is one path segment; an unencoded slash would make it several"
        )

    def test_a_transcript_handle_round_trips_both_ids(self) -> None:
        handle = handles.TranscriptHandle("MSo1N2Y5:ZGFjYw==", "MSMjMCMj/0001")

        parsed = handles.transcript_handle(handle.uri)

        assert parsed is not None
        assert (parsed.meeting_id, parsed.transcript_id) == (
            "MSo1N2Y5:ZGFjYw==",
            "MSMjMCMj/0001",
        )

    @pytest.mark.parametrize(
        "uri",
        [
            # The first segment is what tells the families apart.
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            f"teams:///transcripts/{MEETING_ID}/{_TRANSCRIPT_ID}",
            "teams:///meetings/",
            "teams:///meetings/%20",
            "teams:///meetings/a/b",
            # Re-spelled by hand: the slashes in a raw join URL make it several path segments, and
            # half a join URL is a lookup Graph answers with a "no such meeting" nobody can explain.
            f"teams:///meetings/{JOIN_WEB_URL}",
            "mail:///messages/AAMkAGI2",
            "site:///sites/contoso/pages/1",
            JOIN_WEB_URL,
            "",
        ],
    )
    def test_what_is_not_a_meeting_handle(self, uri: str) -> None:
        assert handles.meeting_handle(uri) is None

    @pytest.mark.parametrize(
        "uri",
        [
            # The family a transcript is reached *from*: a lister takes one and mints the other.
            handles.MeetingHandle(JOIN_WEB_URL).uri,
            "teams:///transcripts/only-one-id",
            "teams:///transcripts//a",
            "teams:///transcripts/a/%20",
            "teams:///transcripts/a/b/c",
            "",
        ],
    )
    def test_what_is_not_a_transcript_handle(self, uri: str) -> None:
        assert handles.transcript_handle(uri) is None

    @pytest.mark.parametrize("join_web_url", [None, "", "   "])
    def test_no_join_url_means_no_handle_rather_than_an_empty_one(
        self, join_web_url: str | None
    ) -> None:
        """Graph gives some meeting chats no join URL, so there is no route to the meeting."""
        assert handles.meeting_uri_for(join_web_url) is None
