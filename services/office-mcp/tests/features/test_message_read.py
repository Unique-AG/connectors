"""`read_message`' feature half: which handle addresses what, and what a Teams body really holds.

Every payload is synthesised from Microsoft's own documented shapes — the Teams-identity sender, the
authorless `<systemEventMessage/>`, the `<at>`/`<emoji>`/`<attachment>` decorations a Teams body
carries. Nothing here came from a tenant.
"""

from typing import cast

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.features import message_read, message_search
from office_mcp.features.message_read import MessageHandle
from office_mcp.features.message_search import SearchCriteria
from office_mcp.graph_client import GraphForbidden, GraphNotFound

from .conftest import chat_hit, message_payload, search_response

_CHAT_ID = "19:release@thread.v2"
_MESSAGE_ID = "1770000000000"
_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"

_CHAT_URI = f"teams:///chats/19%3Arelease%40thread.v2/messages/{_MESSAGE_ID}"
_CHANNEL_URI = (
    f"teams:///teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/{_MESSAGE_ID}"
)

# The path the ids above address once Graph has them. The SDK re-encodes them for the URL, so this
# is what a percent-decoded handle has to come back out as.
_CHAT_PATH = f"/chats/19%3Arelease%40thread.v2/messages/{_MESSAGE_ID}"
_CHANNEL_PATH = f"/teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/{_MESSAGE_ID}"

_CHAT_HANDLE = MessageHandle(message_id=_MESSAGE_ID, chat_id=_CHAT_ID)
_CHANNEL_HANDLE = MessageHandle(message_id=_MESSAGE_ID, team_id=_TEAM_ID, channel_id=_CHANNEL_ID)


def _reads(graph: respx.MockRouter, payload: dict[str, object], path: str = _CHAT_PATH) -> None:
    _ = graph.get(path).mock(return_value=httpx.Response(200, json=payload))


class TestTheHandlesItAccepts:
    def test_it_reads_the_two_shapes_search_emits_and_decodes_their_ids(self) -> None:
        """The handle is `search_messages`' contract: the ids in it are percent-encoded because a
        Teams id is full of `:` and `@`, so parsing it means decoding them back."""
        chat = message_read.message_handle(_CHAT_URI)
        channel = message_read.message_handle(_CHANNEL_URI)

        assert chat == _CHAT_HANDLE
        assert channel == _CHANNEL_HANDLE

    def test_a_handle_survives_the_round_trip_it_came_from(self) -> None:
        assert message_read.message_handle(_CHAT_URI) is not None
        assert cast("MessageHandle", message_read.message_handle(_CHAT_URI)).uri == _CHAT_URI
        assert cast("MessageHandle", message_read.message_handle(_CHANNEL_URI)).uri == _CHANNEL_URI

    def test_an_unencoded_id_still_resolves(self) -> None:
        """A caller that copied a handle out of a log rather than out of a response has ids that
        were never encoded; `:` and `@` are unambiguous in a path segment, so those are read too."""
        handle = message_read.message_handle(f"teams:///chats/{_CHAT_ID}/messages/{_MESSAGE_ID}")

        assert handle == _CHAT_HANDLE

    def test_it_says_which_permission_each_shape_is_read_under(self) -> None:
        """Graph's permissions for a message read are per surface, so a 403 on a chat read can
        only be about `Chat.Read` — naming the channel permission alongside it would send an
        administrator after one that was never missing."""
        assert _CHAT_HANDLE.permission == "Chat.Read"
        assert _CHANNEL_HANDLE.permission == "ChannelMessage.Read.All"

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
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000/replies/1770000000001",
            "teams:///teams/8a9c3c47/messages/1770000000000",
            "teams:///chats/19%3Arelease%40thread.v2/messages/%20",
            # A Teams web link, which is what a model reaches for when it has no handle.
            "https://teams.microsoft.com/l/message/19%3Ageneral/1770000000000",
            "1770000000000",
            "",
        ],
    )
    def test_it_refuses_everything_else(self, uri: str) -> None:
        assert message_read.message_handle(uri) is None


class TestTheRequestItMakes:
    async def test_a_chat_handle_reads_the_chat_message_endpoint(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_CHAT_PATH).mock(return_value=httpx.Response(200, json=message_payload()))

        _ = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert route.called

    async def test_a_channel_handle_reads_the_channel_message_endpoint(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_CHANNEL_PATH).mock(
            return_value=httpx.Response(200, json=message_payload())
        )

        _ = await message_read.read_message(client, handle=_CHANNEL_HANDLE)

        assert route.called

    async def test_it_asks_for_the_message_type_graph_hides_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`messageType` is an evolvable enum: without this header Graph reports
        `systemEventMessage` as `unknownFutureValue`, which names nothing."""
        route = graph.get(_CHAT_PATH).mock(return_value=httpx.Response(200, json=message_payload()))

        _ = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert route.calls.last.request.headers["prefer"] == "include-unknown-enum-members"

    async def test_the_prefer_header_is_not_added_to_every_other_graph_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """kiota's `RequestConfiguration.headers` defaults to one `HeadersCollection` shared by
        every configuration in the process, so a header added to the default leaks into unrelated
        calls. This is the check that the reader builds its own."""
        _reads(graph, message_payload())
        chats = graph.get("/me/chats").mock(return_value=httpx.Response(200, json={"value": []}))

        _ = await message_read.read_message(client, handle=_CHAT_HANDLE)
        from office_mcp.features import chats as chats_feature

        _ = await chats_feature.list_recent_chats(client, limit=1, include_member_emails=False)

        assert "prefer" not in chats.calls.last.request.headers


class TestWhatItReportsAboutTheMessage:
    async def test_it_answers_with_the_handle_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.uri == _CHAT_URI
        assert (message.message_id, message.chat_id) == (_MESSAGE_ID, _CHAT_ID)
        assert (message.team_id, message.channel_id) == (None, None)

    async def test_the_sender_is_the_teams_identity_shape_with_no_email(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A read gives `teamworkUserIdentity`, which has no email property at all — so the field
        search fills in is null here, and the id is what the two shapes have in common."""
        _reads(graph, message_payload())

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.sender is not None
        assert message.sender.display_name == "Ada Lovelace"
        assert message.sender.user_id == "00000000-0000-4000-8000-000000000001"
        assert message.sender.email is None

    async def test_a_sender_graph_gave_no_name_is_still_identified(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`displayName` is documented Optional and is genuinely absent for federated and external
        users. A blank name must not read as an anonymous sender."""
        _reads(
            graph,
            message_payload(
                sender={
                    "user": {
                        "@odata.type": "#microsoft.graph.teamworkUserIdentity",
                        "id": "00000000-0000-4000-8000-000000000002",
                        "displayName": "",
                        "userIdentityType": "federatedUser",
                    }
                }
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.sender is not None
        assert message.sender.display_name is None, "an empty name is not a name"
        assert message.sender.user_id == "00000000-0000-4000-8000-000000000002"

    async def test_a_bot_is_named_by_its_application(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
                sender={
                    "application": {
                        "@odata.type": "#microsoft.graph.teamworkApplicationIdentity",
                        "id": "0dbc0b2f-e0d6-4a1f-b2f4-8f2b3f3f0e8c",
                        "displayName": "Release Bot",
                    }
                }
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.sender is not None
        assert (message.sender.display_name, message.sender.user_id) == ("Release Bot", None)

    async def test_edits_and_reactions_are_not_confused_for_each_other(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`lastModifiedDateTime` moves when somebody adds a reaction; `lastEditedDateTime` is the
        one that means the author changed the text, so it is the one reported."""
        _reads(
            graph,
            message_payload(
                last_modified_at="2026-02-11T11:00:00Z", last_edited_at="2026-02-11T10:00:00Z"
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.last_edited_at is not None
        assert message.last_edited_at.isoformat() == "2026-02-11T10:00:00+00:00"

    async def test_an_unedited_message_says_so(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.last_edited_at is None
        assert message.deleted_at is None

    async def test_a_channel_reply_carries_the_post_it_replies_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
                reply_to_id="1770000000001",
                web_url="https://teams.microsoft.invalid/l/message/19%3Ageneral/1770000000000",
            ),
            _CHANNEL_PATH,
        )

        message = await message_read.read_message(client, handle=_CHANNEL_HANDLE)

        assert message.reply_to_id == "1770000000001"
        assert message.web_url is not None


class TestTheBodyItNormalises:
    async def test_plain_text_content_is_left_alone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload(content="cut the release on Friday", content_type="text"))

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "cut the release on Friday"

    async def test_teams_html_becomes_readable_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The whole pipeline over one body: wrapper divs, paragraphs, breaks, a list, formatting
        tags and HTML entities. Handing any of this to a model verbatim is the quality bug."""
        _reads(
            graph,
            message_payload(
                content=(
                    '<div><div itemprop="copy-paste-block"><p>Ship <strong>today</strong> '
                    + "&amp; tell&nbsp;support.</p><p>Blockers:</p><ul><li>build #7</li>"
                    + "<li>docs</li></ul>done<br/>thanks</div></div>"
                )
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == (
            "Ship today & tell support.\nBlockers:\n- build #7\n- docs\ndone\nthanks"
        )

    async def test_a_mention_reads_as_the_person_it_names(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """An `<at id="0">` left in the text would be a key to nothing, and dropping it would read
        as the author addressing nobody."""
        _reads(
            graph,
            message_payload(
                content='<p><at id="0">Ada Lovelace</at> can you review?</p>',
                mentions=[
                    {
                        "id": 0,
                        "mentionText": "Ada Lovelace",
                        "mentioned": {
                            "user": {
                                "id": "00000000-0000-4000-8000-000000000001",
                                "displayName": "Ada Lovelace",
                                "userIdentityType": "aadUser",
                            }
                        },
                    }
                ],
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "@Ada Lovelace can you review?"
        assert [(m.text, m.user_id) for m in message.mentions] == [
            ("Ada Lovelace", "00000000-0000-4000-8000-000000000001")
        ]

    async def test_a_mention_with_no_text_of_its_own_is_resolved_from_the_mentions_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft documents the `<at>` element's `id` as corresponding to `mentions[].id`, which
        is the authority — the element's own text is sometimes empty."""
        _reads(
            graph,
            message_payload(
                content='<p><at id="3"></at> heads up</p>',
                mentions=[{"id": 3, "mentionText": "Release planning", "mentioned": {}}],
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "@Release planning heads up"

    async def test_a_mention_of_everyone_is_not_reported_as_a_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """An @everyone arrives as a conversation identity with `user: null`, so a null `user_id`
        is not a failure to resolve somebody."""
        _reads(
            graph,
            message_payload(
                content='<p><at id="0">Everyone</at> standup moved</p>',
                mentions=[
                    {
                        "id": 0,
                        "mentionText": "Everyone",
                        "mentioned": {
                            "conversation": {
                                "id": _CHAT_ID,
                                "displayName": "Release planning",
                                "conversationIdentityType": "chat",
                            }
                        },
                    }
                ],
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert [(m.text, m.user_id) for m in message.mentions] == [("Everyone", None)]

    async def test_an_attachment_placeholder_names_what_was_attached(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The body carries only `<attachment id="…">`; the name lives in `attachments[]`, so
        without resolving one against the other the message reads as if nothing was attached."""
        _reads(
            graph,
            message_payload(
                content='<p>see this</p><attachment id="1727881360458"></attachment>',
                attachments=[
                    {
                        "id": "1727881360458",
                        "contentType": "reference",
                        "contentUrl": "https://contoso.sharepoint.invalid/Shared/plan.xlsx",
                        "name": "plan.xlsx",
                    }
                ],
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "see this\n[attachment: plan.xlsx]"
        assert [(a.name, a.content_type) for a in message.attachments] == [
            ("plan.xlsx", "reference")
        ]
        assert message.attachments[0].url is not None

    async def test_an_unnamed_attachment_is_still_marked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
                content='<attachment id="1727881360458"></attachment>',
                attachments=[
                    {
                        "id": "1727881360458",
                        "contentType": "forwardedMessageReference",
                        "content": '{"originalMessageId":"1770000000000"}',
                        "name": None,
                    }
                ],
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "[attachment]"
        assert message.attachments[0].url is None, (
            "a forwarded message's `content` is a JSON payload, not a location"
        )

    async def test_emoji_survive_the_tags_that_carry_them(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`<emoji alt="👀">` holds the character in an attribute, so stripping tags without
        reading it deletes the emoji from the message."""
        _reads(
            graph,
            message_payload(
                content='<p>looking <emoji id="1f440_eyes" alt="\U0001f440" title="Eyes"></emoji>'
                + '<customemoji id="x" alt="teams_party" source="https://x.invalid"></customemoji>'
                + "</p>"
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "looking \U0001f440teams_party"

    async def test_an_inline_image_is_reported_rather_than_dropped(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
                content=(
                    '<div><img height="63" src="https://graph.microsoft.com/v1.0/chats/x/'
                    + 'messages/y/hostedContents/z/$value" width="67"></div>'
                )
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "[image]"

    async def test_an_adaptive_card_is_not_dumped_into_the_answer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
                content='{"type":"AdaptiveCard","version":"1.4","body":[{"type":"TextBlock"}]}'
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "[card]"

    async def test_a_body_with_nothing_in_it_is_null_rather_than_empty(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload(content="<div>   </div>"))

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.text is None


class TestTheMessagesThatHaveNoText:
    async def test_a_deleted_message_is_not_presented_as_content(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Whatever a tombstone's body holds, it is not what the author wrote."""
        _reads(
            graph,
            message_payload(deleted_at="2026-02-12T08:00:00Z", content="<div></div>"),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.text is None
        assert message.deleted_at is not None
        assert message.deleted_at.isoformat() == "2026-02-12T08:00:00+00:00"

    async def test_a_system_event_says_what_happened_instead_of_the_literal_tag(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The one Graph is most misleading about: `from` is null and the body is the literal
        `<systemEventMessage/>`. The sentence Teams shows is written by the Teams client and never
        sent, so `eventDetail`'s type is the only thing that names the event."""
        _reads(
            graph,
            message_payload(
                sender=None,
                content="<systemEventMessage/>",
                message_type="systemEventMessage",
                event_detail={
                    "@odata.type": "#microsoft.graph.membersJoinedEventMessageDetail",
                    "visibleHistoryStartDateTime": "0001-01-01T00:00:00Z",
                    "members": [{"id": "00000000-0000-4000-8000-000000000002"}],
                },
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.event == "members joined"
        assert message.text is None, "`<systemEventMessage/>` is not text"
        assert message.sender is None

    @pytest.mark.parametrize(
        ("odata_type", "expected"),
        [
            ("#microsoft.graph.chatRenamedEventMessageDetail", "chat renamed"),
            ("#microsoft.graph.callEndedEventMessageDetail", "call ended"),
            ("#microsoft.graph.callTranscriptEventMessageDetail", "call transcript"),
            ("#microsoft.graph.teamsAppInstalledEventMessageDetail", "teams app installed"),
            (
                "#microsoft.graph.conversationMemberRoleUpdatedEventMessageDetail",
                "conversation member role updated",
            ),
            # The subtype Microsoft adds next: reading the type is what covers it, where a table of
            # the 31 that exist today would answer "unknown".
            ("#microsoft.graph.somethingNewEventMessageDetail", "something new"),
        ],
    )
    async def test_every_event_type_names_itself(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        odata_type: str,
        expected: str,
    ) -> None:
        _reads(
            graph,
            message_payload(
                sender=None,
                content="<systemEventMessage/>",
                message_type="systemEventMessage",
                event_detail={"@odata.type": odata_type},
            ),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.event == expected

    async def test_an_event_graph_did_not_describe_is_still_not_reported_as_a_message(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A `chatEvent` or `typing` message carries no `eventDetail` at all, and without the
        `Prefer` header its type would arrive as `unknownFutureValue`. Either way it is not
        something a person wrote."""
        _reads(
            graph,
            message_payload(sender=None, content="", message_type="unknownFutureValue"),
        )

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.event is not None
        assert message.text is None

    async def test_an_ordinary_message_has_no_event(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())

        message = await message_read.read_message(client, handle=_CHAT_HANDLE)

        assert message.event is None


class TestTheFailuresItPassesOn:
    async def test_a_message_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph answers 'deleted', 'never existed' and 'you may not see it' identically; the
        classification stops here and the tool layer is what refuses to guess between them."""
        _ = graph.get(_CHAT_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await message_read.read_message(client, handle=_CHAT_HANDLE)

    async def test_a_refused_permission_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CHANNEL_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await message_read.read_message(client, handle=_CHANNEL_HANDLE)


class TestTheRoundTripFromASearchResult:
    async def test_a_hit_from_search_is_read_by_its_own_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The contract between the two tools, end to end at the feature level: whatever
        `search_messages` puts in `uri`, `read_message` has to resolve without any part of it being
        reassembled by hand.
        """
        _ = graph.post("/search/query").mock(
            return_value=httpx.Response(
                200, json=search_response([chat_hit(chat_id=_CHAT_ID, message_id=_MESSAGE_ID)])
            )
        )
        route = graph.get(_CHAT_PATH).mock(
            return_value=httpx.Response(
                200, json=message_payload(content="<p>cut the release on Friday</p>")
            )
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )
        uri = found.messages[0].uri
        assert uri is not None
        handle = message_read.message_handle(uri)
        assert handle is not None, f"search produced a handle read_message rejects: {uri}"
        message = await message_read.read_message(client, handle=handle)

        assert route.called
        assert message.uri == uri
        assert message.text == "cut the release on Friday", (
            "the point of the round trip: search has no body, and this is where the text comes from"
        )
        assert message.sender is not None
        assert message.sender.display_name == found.messages[0].sender.display_name, (
            "the same person, whichever tool reported them"
        )
