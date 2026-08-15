"""`read_message`: what a read asks Graph for, and what a Teams body really holds.

Every payload is synthesised from Microsoft's own documented shapes — the Teams-identity sender, the
authorless `<systemEventMessage/>`, the `<at>`/`<emoji>`/`<attachment>` decorations a Teams body
carries. Nothing here came from a tenant.

Which strings are handles at all is `shared/handles.py`'s question, not this tool's:
`TestTheMessageHandleGrammar` in `tests/shared/test_handles.py` covers the three shapes and
everything that is not one of them. What is covered here is what a read does with a handle it was
given.
"""

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import GraphForbidden, GraphNotFound
from office_mcp.shared import handles, identity
from office_mcp.shared.handles import MessageHandle
from office_mcp.tools import read_message, search_messages
from office_mcp.tools.search_messages import SearchCriteria

from .conftest import ME, chat_hit, message_payload, search_response

_CHAT_ID = "19:release@thread.v2"
_MESSAGE_ID = "1770000000000"
_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"

_CHAT_URI = f"teams:///chats/19%3Arelease%40thread.v2/messages/{_MESSAGE_ID}"

# The path the ids above address once Graph has them. The SDK re-encodes them for the URL, so this
# is what a percent-decoded handle has to come back out as.
_CHAT_PATH = f"/chats/19%3Arelease%40thread.v2/messages/{_MESSAGE_ID}"
_CHANNEL_PATH = f"/teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/{_MESSAGE_ID}"

_REPLY_ID = "1770000000002"
_REPLY_PATH = f"{_CHANNEL_PATH}/replies/{_REPLY_ID}"

_CHAT_HANDLE = MessageHandle(message_id=_MESSAGE_ID, chat_id=_CHAT_ID)
_CHANNEL_HANDLE = MessageHandle(message_id=_MESSAGE_ID, team_id=_TEAM_ID, channel_id=_CHANNEL_ID)
# A reply is addressed under the post it answers: the parent's id is `reply_to_id`, and the reply's
# own id is the message this handle names.
_REPLY_HANDLE = MessageHandle(
    message_id=_REPLY_ID, team_id=_TEAM_ID, channel_id=_CHANNEL_ID, reply_to_id=_MESSAGE_ID
)


def _reads(graph: respx.MockRouter, payload: dict[str, object], path: str = _CHAT_PATH) -> None:
    _ = graph.get(path).mock(return_value=httpx.Response(200, json=payload))


class TestTheRequestItMakes:
    async def test_a_chat_handle_reads_the_chat_message_endpoint(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_CHAT_PATH).mock(return_value=httpx.Response(200, json=message_payload()))

        _ = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert route.called

    async def test_a_channel_handle_reads_the_channel_message_endpoint(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_CHANNEL_PATH).mock(
            return_value=httpx.Response(200, json=message_payload())
        )

        _ = await read_message.read_message(client, handle=_CHANNEL_HANDLE)

        assert route.called

    async def test_a_reply_handle_reads_it_under_the_post_it_answers(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The only way Graph addresses a channel reply. The reply's own id beside its siblings is
        a 404, which is the failure a search hit on a reply produces — so the handle names both ids
        and the request nests them.
        """
        route = graph.get(_REPLY_PATH).mock(
            return_value=httpx.Response(
                200, json=message_payload(message_id=_REPLY_ID, reply_to_id=_MESSAGE_ID)
            )
        )

        message = await read_message.read_message(client, handle=_REPLY_HANDLE)

        assert route.called
        assert message.message_id == _REPLY_ID
        assert message.reply_to_id == _MESSAGE_ID
        assert message.uri == _REPLY_HANDLE.uri, "the handle is echoed as it was given"

    async def test_a_reply_graph_named_no_parent_for_is_still_placed_in_its_thread(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`replyToId` is the message's own property and the handle is only the fallback — but the
        fallback matters: a reply reported without a parent would read as a root post."""
        _ = graph.get(_REPLY_PATH).mock(
            return_value=httpx.Response(200, json=message_payload(message_id=_REPLY_ID))
        )

        message = await read_message.read_message(client, handle=_REPLY_HANDLE)

        assert message.reply_to_id == _MESSAGE_ID

    async def test_it_makes_one_request_and_narrows_it_with_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The claim this tool's prose makes about Graph, asserted rather than carried across.
        `chatmessage-get` "doesn't support the OData query parameters", so there is no `$select` to
        narrow the read with and no `$expand` to widen it — which is only survivable because the
        whole message, mentions and attachments included, arrives from one unparameterised GET.
        Every other test here mocks by path alone and would keep passing with a query string on the
        wire and a second request behind it.
        """
        route = graph.get(_CHAT_PATH).mock(
            return_value=httpx.Response(
                200,
                json=message_payload(
                    content='<p>see <at id="0">Ada</at></p><attachment id="7"></attachment>',
                    mentions=[{"id": 0, "mentionText": "Ada", "mentioned": {}}],
                    attachments=[{"id": "7", "contentType": "reference", "name": "plan.xlsx"}],
                ),
            )
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert route.call_count == 1, "one message, one request"
        assert route.calls.last.request.url.query == b"", "no $select and no $expand"
        assert message.text == "see @Ada\n[attachment: plan.xlsx]"
        assert [mention.text for mention in message.mentions] == ["Ada"]
        assert [attachment.name for attachment in message.attachments] == ["plan.xlsx"]

    async def test_it_asks_for_the_message_type_graph_hides_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`messageType` is an evolvable enum: without this header Graph reports
        `systemEventMessage` as `unknownFutureValue`, which names nothing."""
        route = graph.get(_CHAT_PATH).mock(return_value=httpx.Response(200, json=message_payload()))

        _ = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert route.calls.last.request.headers["prefer"] == "include-unknown-enum-members"

    async def test_the_prefer_header_is_not_added_to_every_other_graph_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """kiota's `RequestConfiguration.headers` defaults to one `HeadersCollection` shared by
        every configuration in the process, so a header added to the default leaks into unrelated
        calls. This is the check that the reader builds its own.

        The unrelated call is `shared/identity.py`'s `GET /me`, and what makes it a witness is that
        it passes a `RequestConfiguration` of its own. A second call that passes none would send no
        `Prefer` header whether or not the default was polluted, so this test would keep passing
        while the leak came back — it would stop witnessing anything, silently, and nothing here
        would say so. Reaching for one of `shared/`'s calls rather than another tool's is also what
        keeps it from breaking when that other tool moves.
        """
        _reads(graph, message_payload())
        profile = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))

        _ = await read_message.read_message(client, handle=_CHAT_HANDLE)
        _ = await identity.signed_in_user(client)

        assert "prefer" not in profile.calls.last.request.headers


class TestWhatItReportsAboutTheMessage:
    async def test_it_answers_with_the_handle_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.uri == _CHAT_URI
        assert (message.message_id, message.chat_id) == (_MESSAGE_ID, _CHAT_ID)
        assert (message.team_id, message.channel_id) == (None, None)

    async def test_the_sender_is_the_teams_identity_shape_with_no_email(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A read gives `teamworkUserIdentity`, which has no email property at all — so the field
        search fills in is null here, and `user_id` is what carries the sender instead."""
        _reads(graph, message_payload())

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.sender is not None
        assert message.sender.display_name is None, "an empty name is not a name"
        assert message.sender.user_id == "00000000-0000-4000-8000-000000000002"

    async def test_a_bot_is_named_by_its_application(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The read path is where the application shape actually arrives, so it is where
        `application_id` has to be carried: a bot's id is reported, and never as `user_id`, which
        the `mentions` parameter takes and which only a person has."""
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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.sender is not None
        assert (message.sender.display_name, message.sender.user_id) == ("Release Bot", None)
        assert message.sender.application_id == "0dbc0b2f-e0d6-4a1f-b2f4-8f2b3f3f0e8c"

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.last_edited_at is not None
        assert message.last_edited_at.isoformat() == "2026-02-11T10:00:00+00:00"

    async def test_an_unedited_message_says_so(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHANNEL_HANDLE)

        assert message.reply_to_id == "1770000000001"
        assert message.web_url is not None


class TestTheBodyItNormalises:
    async def test_plain_text_content_is_left_alone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload(content="cut the release on Friday", content_type="text"))

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "[image]"

    async def test_a_body_with_nothing_in_it_is_null_rather_than_empty(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload(content="<div>   </div>"))

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text is None


# One adaptive card, as Microsoft's own example shapes it: the payload lives in the attachment's
# `content` and the attachment's `contentType` is what names it a card.
_CARD_PAYLOAD = (
    '{"type":"AdaptiveCard","version":"1.4",'
    + '"body":[{"type":"TextBlock","text":"Deploy build #7?"}]}'
)
_CARD_ATTACHMENT: dict[str, object] = {
    "id": "74d20c7f34aa4a7fb74e2b30004247c5",
    "contentType": "application/vnd.microsoft.card.adaptive",
    "content": _CARD_PAYLOAD,
    "name": None,
}


class TestWhatCountsAsACard:
    """A card is attachment metadata, never the shape of the body text.

    Microsoft marks a card in `attachments[].contentType` —
    `application/vnd.microsoft.card.adaptive` and its siblings
    (https://learn.microsoft.com/en-us/graph/api/resources/chatmessageattachment,
    https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/cards-reference)
    — and the card's payload in `attachment.content`. Going by the body text instead means a
    developer who pastes JSON into Teams has their message reported as a card and its content
    thrown away, in the one tool that is the only route to a message's text.
    """

    async def test_a_pasted_json_object_is_a_message_and_comes_back_whole(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The defect this class exists for: brace-and-`"type"` text is what a developer sends all
        day, and no part of it may be traded for `[card]`."""
        pasted = '{"type":"service","replicas":3,"image":"office-mcp:1.4.0"}'
        _reads(graph, message_payload(content=f"<div><p>{pasted}</p></div>"))

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == pasted
        assert message.attachments == [], "nothing was attached, so nothing was a card"

    async def test_json_that_is_only_part_of_a_sentence_keeps_the_sentence(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
                content='<p>{"type":"TextBlock"} — is this the bit that broke prod?</p>'
            ),
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == '{"type":"TextBlock"} — is this the bit that broke prod?'

    async def test_a_card_attachment_reads_as_a_card_where_its_placeholder_sat(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The ordinary shape of a card message: the body carries the `<attachment id="…">`
        placeholder and the payload is in `attachments[]`. Teams gives a card no `name`, so without
        reading its `contentType` the card would read as an anonymous `[attachment]`."""
        _reads(
            graph,
            message_payload(
                content=(
                    "<p>ready?</p>"
                    + '<attachment id="74d20c7f34aa4a7fb74e2b30004247c5"></attachment>'
                ),
                attachments=[_CARD_ATTACHMENT],
            ),
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "ready?\n[card]"
        assert [a.content_type for a in message.attachments] == [
            "application/vnd.microsoft.card.adaptive"
        ]

    @pytest.mark.parametrize(
        ("content_type", "expected"),
        [
            ("application/vnd.microsoft.card.adaptive", "[card]"),
            ("application/vnd.microsoft.card.hero", "[card]"),
            ("application/vnd.microsoft.card.thumbnail", "[card]"),
            ("application/vnd.microsoft.card.receipt", "[card]"),
            ("application/vnd.microsoft.card.signin", "[card]"),
            ("application/vnd.microsoft.card.codesnippet", "[card]"),
            ("application/vnd.microsoft.card.announcement", "[card]"),
            ("application/vnd.microsoft.teams.card.list", "[card]"),
            ("application/vnd.microsoft.teams.card.o365connector", "[card]"),
            # The card type Microsoft publishes next: the namespace is the documented shape, so
            # matching it covers what a table of today's nine values would answer `[attachment]` to.
            ("application/vnd.microsoft.card.somethingNew", "[card]"),
            # Not cards. `reference` is a file and `forwardedMessageReference` is a message.
            ("reference", "[attachment]"),
            ("forwardedMessageReference", "[attachment]"),
        ],
    )
    async def test_every_card_namespace_teams_documents_names_itself_a_card(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        content_type: str,
        expected: str,
    ) -> None:
        _reads(
            graph,
            message_payload(
                content='<attachment id="1727881360458"></attachment>',
                attachments=[
                    {"id": "1727881360458", "contentType": content_type, "name": None},
                ],
            ),
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == expected

    async def test_a_named_card_is_named_rather_than_generically_marked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`name` is more use to a reader than the word `card`, so a card that has one keeps it."""
        _reads(
            graph,
            message_payload(
                content='<attachment id="1727881360458"></attachment>',
                attachments=[
                    {
                        "id": "1727881360458",
                        "contentType": "application/vnd.microsoft.card.codesnippet",
                        "name": "deploy.sh",
                    }
                ],
            ),
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "[attachment: deploy.sh]"

    async def test_a_card_teams_left_in_the_body_is_not_dumped_into_the_answer(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Teams sometimes puts the card's own JSON in `body.content` instead of the placeholder.
        That body is the attachment's payload repeated, so `[card]` loses nothing — and the
        attachment is the evidence, which is what makes this safe where a text heuristic was not."""
        _reads(graph, message_payload(content=_CARD_PAYLOAD, attachments=[_CARD_ATTACHMENT]))

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "[card]"

    async def test_the_same_payload_formatted_differently_is_still_the_same_card(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The comparison is between parsed payloads, so indentation and key order do not decide
        whether a model gets a screenful of layout JSON."""
        _reads(
            graph,
            message_payload(
                content=(
                    '{\n  "version": "1.4",\n  "type": "AdaptiveCard",\n'
                    + '  "body": [ { "text": "Deploy build #7?", "type": "TextBlock" } ]\n}'
                ),
                attachments=[_CARD_ATTACHMENT],
            ),
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "[card]"

    async def test_a_payload_carrying_a_non_breaking_space_is_still_the_card_it_came_from(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The normalisation turns Teams' non-breaking spaces into plain ones for a reader. A card's
        own layout text carries them too, so a comparison against the rewritten text sees a payload
        that no longer matches the attachment it is a copy of — and answers with the layout JSON."""
        payload = (
            '{"type":"AdaptiveCard","version":"1.4",'
            + '"body":[{"type":"TextBlock","text":"Deploy\xa0build #7?"}]}'
        )
        _reads(
            graph,
            message_payload(
                content=payload, attachments=[{**_CARD_ATTACHMENT, "content": payload}]
            ),
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "[card]"

    async def test_a_payload_carrying_markup_is_still_the_card_it_came_from(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The same asymmetry from the other lossy rewrite: the tag strip that makes Teams HTML
        readable deletes `<b>` from a card's own text, and `attachment.content` still holds it."""
        payload = (
            '{"type":"AdaptiveCard","version":"1.4",'
            + '"body":[{"type":"TextBlock","text":"<b>Deploy</b> build #7?"}]}'
        )
        _reads(
            graph,
            message_payload(
                content=payload, attachments=[{**_CARD_ATTACHMENT, "content": payload}]
            ),
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "[card]"

    async def test_a_payload_graph_escaped_on_its_way_into_the_body_is_still_that_card(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The encoding difference Graph itself makes, and one reason the body is compared in more
        than one form: it HTML-escapes a body and never escapes `attachment.content`."""
        payload = (
            '{"type":"AdaptiveCard","version":"1.4",'
            + '"body":[{"type":"TextBlock","text":"Ship & tell <b>everyone</b>"}]}'
        )
        escaped = (
            '{"type":"AdaptiveCard","version":"1.4",'
            + '"body":[{"type":"TextBlock","text":"Ship &amp; tell &lt;b&gt;everyone&lt;/b&gt;"}]}'
        )
        _reads(
            graph,
            message_payload(
                content=escaped, attachments=[{**_CARD_ATTACHMENT, "content": payload}]
            ),
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "[card]"

    @pytest.mark.parametrize(
        "wrapper",
        [
            "<div>{payload}</div>",
            "<p>{payload}</p>",
            "<div><p>{payload}</p></div>",
            "{payload}<br>",
        ],
    )
    async def test_a_payload_teams_wrapped_in_markup_is_still_the_card_it_came_from(
        self, client: GraphServiceClient, graph: respx.MockRouter, wrapper: str
    ) -> None:
        """The other direction of the same asymmetry, and why the rewritten body is compared too. A
        body is only reached here when Graph typed it `html`, so a wrapped payload is the likelier
        shape of the two: deleting the tags is what uncovers the JSON to compare."""
        payload = (
            '{"type":"AdaptiveCard","version":"1.4",'
            + '"body":[{"type":"TextBlock","text":"Deploy build #7?"}]}'
        )
        _reads(
            graph,
            message_payload(
                content=wrapper.format(payload=payload),
                attachments=[{**_CARD_ATTACHMENT, "content": payload}],
            ),
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == "[card]"

    async def test_a_card_attachment_does_not_license_discarding_unrelated_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Both at once, which is the case a conjunction of the two old signals would still lose: a
        real card attachment *and* a body that is a person's own JSON rather than that card. The
        text is theirs, so it is returned in full and the card is reported in `attachments`."""
        pasted = '{"type":"Deployment","replicas":3}'
        _reads(graph, message_payload(content=f"<p>{pasted}</p>", attachments=[_CARD_ATTACHMENT]))

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == pasted
        assert [a.content_type for a in message.attachments] == [
            "application/vnd.microsoft.card.adaptive"
        ]

    async def test_json_text_with_no_card_attachment_survives_even_beside_a_file(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """An attachment that is not a card is not evidence of one."""
        pasted = '{"type":"service","port":9544}'
        _reads(
            graph,
            message_payload(
                content=f'<p>{pasted}</p><attachment id="1727881360458"></attachment>',
                attachments=[
                    {
                        "id": "1727881360458",
                        "contentType": "reference",
                        "contentUrl": "https://contoso.sharepoint.invalid/Shared/values.yaml",
                        "name": "values.yaml",
                    }
                ],
            ),
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.text == f"{pasted}\n[attachment: values.yaml]"


class TestTheMessagesThatHaveNoText:
    async def test_a_deleted_message_is_not_presented_as_content(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Whatever a tombstone's body holds, it is not what the author wrote."""
        _reads(
            graph,
            message_payload(deleted_at="2026-02-12T08:00:00Z", content="<div></div>"),
        )

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.event is not None
        assert message.text is None

    @pytest.mark.parametrize(
        "sender",
        [
            pytest.param(None, id="null-from"),
            pytest.param({}, id="identity-set-naming-nobody"),
            pytest.param({"user": {}}, id="empty-user-object"),
        ],
    )
    async def test_a_message_with_no_sender_always_says_what_happened_instead(
        self, client: GraphServiceClient, graph: respx.MockRouter, sender: dict[str, object] | None
    ) -> None:
        """`sender` promises it is "null only when nobody wrote it, which `event` then describes",
        so the two answers have to come from the same question. Graph names no author with a null
        `from` and with an identity set holding nobody, and either one left `event` null would be a
        message with no author and no explanation — a silent gap where a system event was."""
        _reads(graph, message_payload(sender=sender, content=""))

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

        assert message.sender is None
        assert message.event is not None, "a null sender must always be explained by an event"

    async def test_an_ordinary_message_has_no_event(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())

        message = await read_message.read_message(client, handle=_CHAT_HANDLE)

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
            _ = await read_message.read_message(client, handle=_CHAT_HANDLE)

    async def test_a_refused_permission_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CHANNEL_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await read_message.read_message(client, handle=_CHANNEL_HANDLE)


class TestTheRoundTripFromASearchResult:
    async def test_a_hit_from_search_is_read_by_its_own_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The contract between the two tools, end to end under the tool boundary: whatever
        `search_messages` puts in `uri`, `read_message` has to resolve without any part of it being
        reassembled by hand. It lives with the reader because the reader is the half that fails
        when the two disagree.
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

        found = await search_messages.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )
        uri = found.messages[0].uri
        assert uri is not None
        handle = handles.message_handle(uri)
        assert handle is not None, f"search produced a handle read_message rejects: {uri}"
        message = await read_message.read_message(client, handle=handle)

        assert route.called
        assert message.uri == uri
        assert message.text == "cut the release on Friday", (
            "the point of the round trip: search has no body, and this is where the text comes from"
        )
        assert message.sender is not None
        assert message.sender.display_name == found.messages[0].sender.display_name, (
            "the same person, whichever tool reported them"
        )
