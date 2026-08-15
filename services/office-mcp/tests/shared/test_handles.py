"""The `teams:///` grammar: what round-trips, and what is not a handle of a given family.

The families are separate because the tools and the permissions behind them are, so the assertions
that matter most here are the negative ones — a message handle must not parse as a meeting's, and a
meeting's must not parse as a message's. Every id below is invented.
"""

import pytest

from office_mcp.shared import handles

# A join URL shaped like the ones Graph actually stores: `%3a` and `%40` already percent-escaped, a
# `?context=` query with `%7b`/`%22` in its value, and an `&` parameter after it. Every one of those
# is a character a handle has to carry through one path segment and hand back byte-identical.
JOIN_WEB_URL = (
    "https://teams.microsoft.invalid/l/meetup-join/"
    + "19%3ameeting_TjAwMDAwMDAwMDAwMA%40thread.v2/0"
    + "?context=%7b%22Tid%22%3a%228a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81%22%7d&anon=true"
)

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
    """The three shapes a Teams message is addressed by, and everything that is not one of them.

    `search_messages` mints two of these and `browse_channel` the third; `read_message` reads all
    three back. That is exactly why the grammar is neither tool's — a handle one minted and another
    answers 404 to does not look like a disagreement — so it is tested here, once, rather than
    beside whichever tool happens to write it.
    """

    def test_it_reads_the_two_shapes_search_emits_and_decodes_their_ids(self) -> None:
        """The ids in a handle are percent-encoded because a Teams id is full of `:` and `@`, so
        reading one back means decoding them."""
        chat = handles.message_handle(_CHAT_URI)
        channel = handles.message_handle(_CHANNEL_URI)

        assert chat == _CHAT_HANDLE
        assert channel == _CHANNEL_HANDLE

    def test_it_reads_the_reply_shape_that_only_browsing_a_channel_can_mint(self) -> None:
        """The third shape. Graph addresses a reply in a channel thread under the post it answers,
        and the search projection carries no `replyToId` — so a search hit on a reply becomes the
        root-post shape and cannot be read, while `browse_channel` walks a channel post by post and
        knows each reply's parent. The grammar still lives here, with the other two: two modules
        that each knew how to write a handle would be free to disagree.
        """
        reply = handles.message_handle(_REPLY_URI)

        assert reply == _REPLY_HANDLE
        assert reply is not None and reply.uri == _REPLY_URI

    def test_a_handle_survives_the_round_trip_it_came_from(self) -> None:
        chat = handles.message_handle(_CHAT_URI)
        channel = handles.message_handle(_CHANNEL_URI)

        assert chat is not None and chat.uri == _CHAT_URI
        assert channel is not None and channel.uri == _CHANNEL_URI

    def test_an_unencoded_id_still_resolves(self) -> None:
        """A caller that copied a handle out of a log rather than out of a response has ids that
        were never encoded; `:` and `@` are unambiguous in a path segment, so those are read too."""
        handle = handles.message_handle(f"teams:///chats/{_CHAT_ID}/messages/{_MESSAGE_ID}")

        assert handle == _CHAT_HANDLE

    def test_it_says_which_permission_each_shape_is_read_under(self) -> None:
        """Graph's permissions for a message read are per surface and the handle is the only
        thing that knows which surface, so a 403 on a chat read can only be about `Chat.Read` —
        naming the channel permission alongside it would send an administrator after one that was
        never missing."""
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
            # Right scheme, wrong shape.
            "teams:///chats/19%3Arelease%40thread.v2",
            "teams:///messages/1770000000000",
            "teams:///chats//messages/1770000000000",
            "teams:///chats/19%3Arelease%40thread.v2/messages/",
            # A chat has no replies in Graph's addressing — only a channel thread does.
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000/replies/1770000000001",
            "teams:///teams/8a9c3c47/channels/19%3Ageneral/messages/1770000000000/replies/",
            "teams:///teams/8a9c3c47/channels/19%3Ageneral/messages//replies/1770000000001",
            "teams:///teams/8a9c3c47/messages/1770000000000",
            "teams:///chats/19%3Arelease%40thread.v2/messages/%20",
            # A Teams web link, which is what a model reaches for when it has no handle.
            "https://teams.microsoft.invalid/l/message/19%3Ageneral/1770000000000",
            "1770000000000",
            "",
        ],
    )
    def test_it_refuses_everything_else(self, uri: str) -> None:
        assert handles.message_handle(uri) is None


class TestTheHandleGrammar:
    def test_a_meeting_handle_survives_the_join_url_it_carries(self) -> None:
        """A join URL is full of `:`, `/`, `?`, `&` and `%` and must come back byte-identical:
        Graph matches it against what it stored, character for character."""
        uri = handles.meeting_uri_for(JOIN_WEB_URL)
        assert uri is not None

        parsed = handles.meeting_handle(uri)

        assert parsed is not None
        assert parsed.join_web_url == JOIN_WEB_URL
        assert "/" not in uri.removeprefix("teams:///meetings/"), (
            "the join URL is one path segment; an unencoded slash would make it several"
        )

    @pytest.mark.parametrize(
        "uri",
        [
            # Another family's shape, which is the negative that matters: the first segment is what
            # tells the families apart, and a parser that ignored it would answer for all of them.
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            "teams:///meetings/",
            "teams:///meetings/%20",
            "teams:///meetings/a/b",
            # The handle a model re-spelled by hand: the slashes in a raw join URL make it several
            # path segments. Refusing it is the point — half of it, carried as if it were the whole,
            # is a lookup Graph answers nothing for and a "no such meeting" nobody could explain.
            f"teams:///meetings/{JOIN_WEB_URL}",
            # The schemes a polymorphic reader would advertise and this connector cannot serve.
            "mail:///messages/AAMkAGI2",
            "site:///sites/contoso/pages/1",
            # The bare URL, which is what a model reaches for when it has no handle at all.
            JOIN_WEB_URL,
            "",
        ],
    )
    def test_what_is_not_a_meeting_handle(self, uri: str) -> None:
        assert handles.meeting_handle(uri) is None

    @pytest.mark.parametrize("join_web_url", [None, "", "   "])
    def test_no_join_url_means_no_handle_rather_than_an_empty_one(
        self, join_web_url: str | None
    ) -> None:
        """The case the design has to survive: Graph gives a meeting chat no join URL, so there is
        no route to its meeting and nothing may pretend otherwise."""
        assert handles.meeting_uri_for(join_web_url) is None
