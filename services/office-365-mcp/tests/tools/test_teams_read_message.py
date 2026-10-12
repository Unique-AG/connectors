from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared import handles, identity
from office_365_mcp.shared.handles import MessageHandle
from office_365_mcp.tools import teams_read_message, teams_search_messages
from office_365_mcp.tools.teams_search_messages import SearchCriteria

from .conftest import ME, chat_hit, message_payload, reaction_payload, search_response

_CHAT_ID = "19:release@thread.v2"
_MESSAGE_ID = "1770000000000"
_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"

_CHAT_URI = f"teams:///chats/19%3Arelease%40thread.v2/messages/{_MESSAGE_ID}"

_CHAT_PATH = f"/chats/19%3Arelease%40thread.v2/messages/{_MESSAGE_ID}"
_CHANNEL_PATH = f"/teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/{_MESSAGE_ID}"

_REPLY_ID = "1770000000002"
_REPLY_PATH = f"{_CHANNEL_PATH}/replies/{_REPLY_ID}"

_CHAT_HANDLE = MessageHandle(message_id=_MESSAGE_ID, chat_id=_CHAT_ID)
_CHANNEL_HANDLE = MessageHandle(message_id=_MESSAGE_ID, team_id=_TEAM_ID, channel_id=_CHANNEL_ID)
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

        _ = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert route.called

    async def test_a_channel_handle_reads_the_channel_message_endpoint(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_CHANNEL_PATH).mock(
            return_value=httpx.Response(200, json=message_payload())
        )

        _ = await teams_read_message.teams_read_message(client, handle=_CHANNEL_HANDLE)

        assert route.called

    async def test_a_reply_handle_reads_it_under_the_post_it_answers(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_REPLY_PATH).mock(
            return_value=httpx.Response(
                200, json=message_payload(message_id=_REPLY_ID, reply_to_id=_MESSAGE_ID)
            )
        )

        message = await teams_read_message.teams_read_message(client, handle=_REPLY_HANDLE)

        assert route.called
        assert message.message_id == _REPLY_ID
        assert message.reply_to_id == _MESSAGE_ID
        assert message.uri == _REPLY_HANDLE.uri, "the handle is echoed as it was given"

    async def test_a_reply_graph_named_no_parent_for_is_still_placed_in_its_thread(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_REPLY_PATH).mock(
            return_value=httpx.Response(200, json=message_payload(message_id=_REPLY_ID))
        )

        message = await teams_read_message.teams_read_message(client, handle=_REPLY_HANDLE)

        assert message.reply_to_id == _MESSAGE_ID

    async def test_it_makes_one_request_and_narrows_it_with_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert route.call_count == 1, "one message, one request"
        assert route.calls.last.request.url.query == b"", "no $select and no $expand"
        assert [mention.text for mention in message.mentions] == ["Ada"]
        assert [attachment.name for attachment in message.attachments] == ["plan.xlsx"]

    async def test_it_asks_for_the_message_type_graph_hides_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_CHAT_PATH).mock(return_value=httpx.Response(200, json=message_payload()))

        _ = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert route.calls.last.request.headers["prefer"] == "include-unknown-enum-members"

    async def test_the_prefer_header_is_not_added_to_every_other_graph_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())
        profile = graph.get("/me").mock(return_value=httpx.Response(200, json=ME))

        _ = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)
        _ = await identity.signed_in_user(client)

        assert "prefer" not in profile.calls.last.request.headers


class TestWhatItReportsAboutTheMessage:
    async def test_it_answers_with_the_handle_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.uri == _CHAT_URI
        assert (message.message_id, message.chat_id) == (_MESSAGE_ID, _CHAT_ID)
        assert (message.team_id, message.channel_id) == (None, None)

    async def test_the_sender_is_the_teams_identity_shape_with_no_email(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.sender is not None
        assert message.sender.display_name == "Ada Lovelace"
        assert message.sender.user_id == "00000000-0000-4000-8000-000000000001"
        assert message.sender.email is None

    async def test_a_sender_graph_gave_no_name_is_still_identified(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

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

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.sender is not None
        assert (message.sender.display_name, message.sender.user_id) == ("Release Bot", None)
        assert message.sender.application_id == "0dbc0b2f-e0d6-4a1f-b2f4-8f2b3f3f0e8c"

    async def test_edits_and_reactions_are_not_confused_for_each_other(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
                last_modified_at="2026-02-11T11:00:00Z", last_edited_at="2026-02-11T10:00:00Z"
            ),
        )

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.last_edited_at is not None
        assert message.last_edited_at.isoformat() == "2026-02-11T10:00:00+00:00"

    async def test_an_unedited_message_says_so(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

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

        message = await teams_read_message.teams_read_message(client, handle=_CHANNEL_HANDLE)

        assert message.reply_to_id == "1770000000001"
        assert message.web_url is not None


class TestReactions:
    async def test_a_reaction_names_what_it_is_who_added_it_and_when(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_CHAT_PATH).mock(
            return_value=httpx.Response(
                200,
                json=message_payload(
                    reactions=[
                        reaction_payload(
                            reaction_type="\U0001f44d",
                            user_id="00000000-0000-4000-8000-000000000002",
                            display_name="Grace Hopper",
                            created_at="2026-02-11T09:20:00Z",
                        )
                    ]
                ),
            )
        )

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert route.calls.last.request.url.query == b"", "no widening was needed for it"
        assert len(message.reactions) == 1
        reaction = message.reactions[0]
        assert reaction.reaction_type == "\U0001f44d"
        assert reaction.user_id == "00000000-0000-4000-8000-000000000002"
        assert reaction.display_name == "Grace Hopper"
        assert reaction.created_at is not None
        assert reaction.created_at.isoformat() == "2026-02-11T09:20:00+00:00"

    async def test_a_custom_reaction_is_named_by_its_own_display_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
                reactions=[reaction_payload(reaction_type="custom", display_name="microsoft_teams")]
            ),
        )

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.reactions[0].reaction_type == "custom"

    async def test_several_reactions_are_all_reported(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
                reactions=[
                    reaction_payload(reaction_type="\U0001f44d", user_id="a"),
                    reaction_payload(reaction_type="❤️", user_id="b"),
                ]
            ),
        )

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert [reaction.reaction_type for reaction in message.reactions] == [
            "\U0001f44d",
            "❤️",
        ]

    async def test_a_message_nobody_reacted_to_has_an_empty_list_rather_than_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.reactions == []

    async def test_a_reaction_graph_named_no_reactor_for_still_reports_the_reaction(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
                reactions=[
                    reaction_payload(reaction_type="\U0001f44d", user_id=None, display_name=None)
                ]
            ),
        )

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert len(message.reactions) == 1
        assert message.reactions[0].user_id is None


class TestTheBodyAsGraphSendsIt:
    async def test_plain_text_content_is_flagged_as_plain_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload(content="cut the release on Friday", content_type="text"))

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.body == "cut the release on Friday"
        assert message.body_is_plain_text

    async def test_html_comes_back_untouched_and_a_link_keeps_its_url(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        html = (
            '<p>Read <a href="https://contoso.sharepoint.com/sites/x/Q3.pptx">Q3 deck</a> '
            + '&amp; <at id="0">Ada</at></p><attachment id="7"></attachment>'
        )
        _reads(graph, message_payload(content=html))

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.body == html
        assert not message.body_is_plain_text

    async def test_the_mentions_and_the_attachments_stay_as_lists_beside_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
                content='<p><at id="0">Ada Lovelace</at> see this</p>',
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
                attachments=[
                    {
                        "id": "7",
                        "contentType": "reference",
                        "contentUrl": "https://contoso.sharepoint.invalid/Shared/plan.xlsx",
                        "name": "plan.xlsx",
                    }
                ],
            ),
        )

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert [(m.text, m.user_id) for m in message.mentions] == [
            ("Ada Lovelace", "00000000-0000-4000-8000-000000000001")
        ]
        assert [(a.name, a.content_type, a.url) for a in message.attachments] == [
            ("plan.xlsx", "reference", "https://contoso.sharepoint.invalid/Shared/plan.xlsx")
        ]

    async def test_a_mention_of_everyone_is_not_reported_as_a_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert [(m.text, m.user_id) for m in message.mentions] == [("Everyone", None)]

    async def test_a_forwarded_message_has_no_url_because_its_content_is_json(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(
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

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.attachments[0].url is None


class TestDeletedMessagesAndSystemEvents:
    async def test_a_deleted_message_is_not_presented_as_content(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(deleted_at="2026-02-12T08:00:00Z", content="<div></div>"),
        )

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.body is None
        assert message.deleted_at is not None
        assert message.deleted_at.isoformat() == "2026-02-12T08:00:00+00:00"

    async def test_a_system_event_says_what_happened(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.event == "members joined"
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

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.event == expected

    async def test_an_event_graph_did_not_describe_is_still_not_reported_as_a_message(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(
            graph,
            message_payload(sender=None, content="", message_type="unknownFutureValue"),
        )

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.event is not None

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
        _reads(graph, message_payload(sender=sender, content=""))

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.sender is None
        assert message.event is not None, "a null sender must always be explained by an event"

    async def test_an_ordinary_message_has_no_event(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _reads(graph, message_payload())

        message = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

        assert message.event is None


class TestTheFailuresItPassesOn:
    async def test_a_message_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CHAT_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await teams_read_message.teams_read_message(client, handle=_CHAT_HANDLE)

    async def test_a_refused_permission_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CHANNEL_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await teams_read_message.teams_read_message(client, handle=_CHANNEL_HANDLE)


class TestTheRefusalOfAValueThatIsNotAMessageHandle:
    @pytest.mark.parametrize(
        "uri",
        [
            "19:release@thread.v2",
            "teams:///chats/19%3Arelease%40thread.v2",
            "outlook:///messages/AAMkSYNTHETIC",
        ],
    )
    async def test_it_shows_the_three_shapes_and_no_stale_claim(
        self,
        transport: httpx.AsyncClient,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        uri: str,
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        teams_read_message.register(mcp, transport)
        tool = await mcp.get_tool(teams_read_message.TOOL_NAME)
        assert isinstance(tool, FunctionTool)

        with pytest.raises(ToolError) as refused:
            _ = cast("object", await tool.fn(uri=uri, ctx=cast("Context", object()), client=client))

        text = str(refused.value)
        assert text.startswith("teams_read_message takes the `uri` handle of a Teams message")
        assert "teams:///chats/{chat_id}/messages/{message_id}" in text
        assert "teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}" in text
        assert (
            "teams:///teams/{team_id}/channels/{channel_id}/messages/{root_id}/replies/{reply_id}"
        ) in text
        assert (
            "teams_search_messages, teams_browse_channel, teams_list_message_replies and "
            + "teams_list_chat_messages give a message handle."
        ) in text
        assert "teams_browse_channel produced" not in text
        assert "no mail, files or sites" not in text
        assert len(graph.calls) == 0


class TestTheAdviceForAReplyItCannotRead:
    def test_it_names_both_tools_that_emit_a_reply_handle(self) -> None:
        advice = teams_read_message.GRAPH_NOT_FOUND

        assert "teams_list_message_replies" in advice
        assert "teams_browse_channel" in advice
        assert "needs the handle of the post that the reply answers" in advice
        assert "is the only tool that emits a reply's own handle" not in advice

    def test_it_sends_a_search_hit_that_is_a_reply_to_the_browse(self) -> None:
        advice = teams_read_message.GRAPH_NOT_FOUND

        assert "does not name its post, so teams_browse_channel is its only route" in advice


class TestTheRoundTripFromASearchResult:
    async def test_a_hit_from_search_is_read_by_its_own_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )
        uri = found.messages[0].uri
        assert uri is not None
        handle = handles.message_handle(uri)
        assert handle is not None, f"search produced a handle teams_read_message rejects: {uri}"
        message = await teams_read_message.teams_read_message(client, handle=handle)

        assert route.called
        assert message.uri == uri
        assert message.body == "<p>cut the release on Friday</p>", (
            "the point of the round trip: search has no body, and this is where the body comes from"
        )
        assert message.sender is not None
        assert message.sender.display_name == found.messages[0].sender.display_name, (
            "the same person, whichever tool reported them"
        )
