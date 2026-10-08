from collections.abc import Mapping, Sequence

import httpx
import pytest
import respx
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.chat_message_from_identity_set import ChatMessageFromIdentitySet
from msgraph.generated.models.chat_message_importance import ChatMessageImportance
from msgraph.generated.models.identity import Identity
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.user import User
from msgraph.graph_service_client import GraphServiceClient
from pydantic import ValidationError

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, GraphForbidden
from office_365_mcp.shared.files import AttachableFile
from office_365_mcp.shared.handles import DriveFileHandle, MessageHandle
from office_365_mcp.shared.messages import (
    CHANNEL_POST,
    CHAT_SEND,
    ChannelImportance,
    ChatImportance,
    Mention,
    MentionedMember,
    OutgoingMention,
    TeamsMessage,
    chat_in_question,
    mention_fields,
    mentioned_members,
    message_in_question,
    not_the_sender,
    outgoing_message,
    send_binding,
    send_question,
    sent_by,
    subject_on_a_reply,
    unknown_enum_headers,
)
from office_365_mcp.shared.prose import PREVIEW_CHARACTERS

from .conftest import GRAPH_V1

_JANE = Mention(user_id="00000000-0000-4000-8000-000000000003", name="Jane Smith")
_ADA = Mention(user_id="00000000-0000-4000-8000-000000000001", name="Ada Lovelace")

_JANE_LABELED = (
    "the person with the Microsoft Entra object id '00000000-0000-4000-8000-000000000003' "
    + "(the name 'Jane Smith' is only a label from the request)"
)
_ADA_LABELED = (
    "the person with the Microsoft Entra object id '00000000-0000-4000-8000-000000000001' "
    + "(the name 'Ada Lovelace' is only a label from the request)"
)

_BUDGET = AttachableFile(
    attachment_id="153fa47d-18c9-4179-be08-9879815a9f90",
    web_dav_url="https://contoso.sharepoint.invalid/sites/finance/Shared%20Documents/Budget.docx",
    name="Budget.docx",
)
_PLAN = AttachableFile(
    attachment_id="0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    web_dav_url="https://contoso.sharepoint.invalid/sites/finance/Shared%20Documents/Plan.pptx",
    name="Plan <draft>.pptx",
)

_BUDGET_HANDLE = DriveFileHandle("b!SYNTHETICDRIVE0000", "01SYNTHETICFILE0000")
_PLAN_HANDLE = DriveFileHandle("b!SYNTHETICDRIVE0000", "01SYNTHETICFILE0001")

_CHAT_ID = "19:release@thread.v2"
_TO_THE_CHAT = f"to chat {_CHAT_ID!r}"
_MESSAGE = "Ship it Friday."
_SUBJECT = "Release plan"

_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"
_ROOT_ID = "1770000000001"
_TO_THE_CHANNEL = f"to channel {_CHANNEL_ID!r} in team {_TEAM_ID!r}"


class TestOutgoingMessage:
    def test_a_message_with_no_mention_is_plain_text(self) -> None:
        built = outgoing_message("Ship it <b>Friday</b>.")

        assert built.body is not None
        assert built.body.content == "Ship it <b>Friday</b>."
        assert built.body.content_type == BodyType.Text
        assert built.mentions is None

    def test_the_mentions_come_first_in_the_order_given(self) -> None:
        built = outgoing_message("Ship it Friday.", mentions=[_JANE, _ADA])

        assert built.body is not None
        assert built.body.content_type == BodyType.Html
        assert built.body.content == (
            '<at id="0">Jane Smith</at> <at id="1">Ada Lovelace</at> Ship it Friday.'
        )

    def test_each_mention_names_its_person_by_the_entra_id(self) -> None:
        built = outgoing_message("Ship it Friday.", mentions=[_JANE, _ADA])

        assert built.mentions is not None
        assert [mention.id for mention in built.mentions] == [0, 1]
        assert [mention.mention_text for mention in built.mentions] == [
            "Jane Smith",
            "Ada Lovelace",
        ]
        first = built.mentions[0].mentioned
        assert first is not None
        assert first.user is not None
        assert first.user.id == _JANE.user_id
        assert first.user.display_name == "Jane Smith"
        assert first.user.additional_data == {"userIdentityType": "aadUser"}

    def test_markup_in_the_name_and_the_text_is_escaped(self) -> None:
        named = Mention(user_id=_JANE.user_id, name='Jane <b> & "Co"')

        built = outgoing_message('a < b & "c"', mentions=[named])

        assert built.body is not None
        assert built.body.content == (
            '<at id="0">Jane &lt;b&gt; &amp; &quot;Co&quot;</at> a &lt; b &amp; &quot;c&quot;'
        )
        assert built.mentions is not None
        assert built.mentions[0].mention_text == 'Jane <b> & "Co"'

    def test_a_newline_becomes_a_line_break(self) -> None:
        built = outgoing_message("first line\nsecond line", mentions=[_JANE])

        assert built.body is not None
        assert built.body.content == '<at id="0">Jane Smith</at> first line<br>second line'

    @pytest.mark.parametrize("mentions", [(), (_JANE,)])
    def test_a_message_built_without_them_sets_no_importance_and_no_subject(
        self, mentions: tuple[Mention, ...]
    ) -> None:
        built = outgoing_message("Ship it Friday.", mentions=mentions)

        assert (built.importance, built.subject) == (None, None)

    @pytest.mark.parametrize("mentions", [(), (_JANE,)])
    @pytest.mark.parametrize(
        "importance",
        [ChatMessageImportance.Normal, ChatMessageImportance.High, ChatMessageImportance.Urgent],
    )
    def test_the_importance_and_the_subject_go_out_as_given(
        self, mentions: tuple[Mention, ...], importance: ChatMessageImportance
    ) -> None:
        built = outgoing_message(
            "Ship it Friday.", mentions=mentions, importance=importance, subject="Release plan"
        )

        assert built.importance is importance
        assert built.subject == "Release plan"

    @pytest.mark.parametrize("mentions", [(), (_JANE,)])
    def test_a_message_built_without_files_carries_no_attachment(
        self, mentions: tuple[Mention, ...]
    ) -> None:
        assert outgoing_message("Ship it.", mentions=mentions).attachments is None

    def test_an_attachment_makes_the_text_escaped_html_with_the_tag_after_it(self) -> None:
        built = outgoing_message('a < b & "c"\nnext', attachments=[_BUDGET])

        assert built.body is not None
        assert built.body.content_type == BodyType.Html
        assert built.body.content == (
            "a &lt; b &amp; &quot;c&quot;<br>next "
            + '<attachment id="153fa47d-18c9-4179-be08-9879815a9f90"></attachment>'
        )
        assert built.mentions is None

    def test_each_attachment_is_a_reference_to_its_webdav_address(self) -> None:
        built = outgoing_message("Ship it.", attachments=[_BUDGET, _PLAN])

        assert built.attachments is not None
        assert [
            (attachment.id, attachment.content_type, attachment.content_url, attachment.name)
            for attachment in built.attachments
        ] == [
            (_BUDGET.attachment_id, "reference", _BUDGET.web_dav_url, "Budget.docx"),
            (_PLAN.attachment_id, "reference", _PLAN.web_dav_url, "Plan <draft>.pptx"),
        ]

    def test_the_mentions_come_first_and_the_attachments_last_in_the_order_given(self) -> None:
        built = outgoing_message("Ship it.", mentions=[_JANE], attachments=[_BUDGET, _PLAN])

        assert built.body is not None
        assert built.body.content == (
            '<at id="0">Jane Smith</at> Ship it. '
            + '<attachment id="153fa47d-18c9-4179-be08-9879815a9f90"></attachment> '
            + '<attachment id="0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"></attachment>'
        )
        assert built.mentions is not None
        assert len(built.mentions) == 1

    def test_a_mentioned_member_posts_the_name_that_microsoft_365_gives(self) -> None:
        member = MentionedMember(user_id=_JANE.user_id, name="Jane Smith (Finance)")

        built = outgoing_message("Ship it.", mentions=[member])

        assert built.body is not None
        assert built.body.content == '<at id="0">Jane Smith (Finance)</at> Ship it.'
        assert built.mentions is not None
        assert built.mentions[0].mention_text == "Jane Smith (Finance)"
        mentioned = built.mentions[0].mentioned
        assert mentioned is not None
        assert mentioned.user is not None
        assert (mentioned.user.id, mentioned.user.display_name) == (
            _JANE.user_id,
            "Jane Smith (Finance)",
        )


class TestMention:
    @pytest.mark.parametrize(
        "user_id",
        ["", "jane@example.invalid", "Jane Smith", "00000000-0000-4000-8000-00000000000"],
    )
    def test_a_user_id_that_is_not_a_guid_is_refused(self, user_id: str) -> None:
        with pytest.raises(ValidationError):
            _ = Mention(user_id=user_id, name="Jane Smith")

    def test_an_empty_name_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _ = Mention(user_id=_JANE.user_id, name="")


class TestSendQuestion:
    def test_a_plain_message_names_the_text_the_chat_and_that_it_cannot_be_recalled(self) -> None:
        question = send_question(
            CHAT_SEND, _MESSAGE, _TO_THE_CHAT, (), subject=None, importance=None
        )

        assert question == (
            "Send 'Ship it Friday.' to chat '19:release@thread.v2' now? This cannot be recalled "
            + "once sent."
        )

    def test_an_importance_alone_follows_the_text(self) -> None:
        question = send_question(
            CHAT_SEND, _MESSAGE, _TO_THE_CHAT, (), subject=None, importance="urgent"
        )

        assert question == (
            "Send 'Ship it Friday.' with urgent importance to chat '19:release@thread.v2' now? "
            + "This cannot be recalled once sent."
        )

    def test_it_names_the_subject_the_importance_and_each_person_it_mentions(self) -> None:
        question = send_question(
            CHAT_SEND, _MESSAGE, _TO_THE_CHAT, (_JANE, _ADA), subject=_SUBJECT, importance="high"
        )

        assert question == (
            "Send 'Ship it Friday.' with the subject 'Release plan' and high importance to chat "
            + f"'19:release@thread.v2' now? It mentions {_JANE_LABELED}, {_ADA_LABELED}. This "
            + "cannot be recalled once sent."
        )

    def test_a_mention_shows_its_object_id_and_its_name_only_as_a_label(self) -> None:
        question = send_question(
            CHAT_SEND, _MESSAGE, _TO_THE_CHAT, (_JANE,), subject=None, importance=None
        )

        assert (
            "It mentions the person with the Microsoft Entra object id "
            + "'00000000-0000-4000-8000-000000000003' (the name 'Jane Smith' is only a label "
            + "from the request)."
        ) in question

    def test_a_name_of_another_person_still_shows_the_object_id_that_graph_binds(self) -> None:
        misnamed = Mention(user_id=_JANE.user_id, name="Ada Lovelace")

        question = send_question(
            CHAT_SEND, _MESSAGE, _TO_THE_CHAT, (misnamed,), subject=None, importance=None
        )

        assert _JANE.user_id in question
        assert _ADA.user_id not in question
        assert "(the name 'Ada Lovelace' is only a label from the request)" in question

    def test_a_mentioned_member_shows_its_object_id_and_the_name_from_microsoft_365(self) -> None:
        member = MentionedMember(user_id=_JANE.user_id, name="Jane Smith (Finance)")

        question = send_question(
            CHAT_SEND, _MESSAGE, _TO_THE_CHAT, (member,), subject=None, importance=None
        )

        assert question == (
            "Send 'Ship it Friday.' to chat '19:release@thread.v2' now? It mentions the person "
            + "with the Microsoft Entra object id '00000000-0000-4000-8000-000000000003' (the "
            + "name 'Jane Smith (Finance)' comes from Microsoft 365). This cannot be recalled "
            + "once sent."
        )

    def test_a_long_label_is_cut_and_the_object_id_is_kept(self) -> None:
        long = Mention(user_id=_JANE.user_id, name="J" * (PREVIEW_CHARACTERS + 1))

        question = send_question(
            CHAT_SEND, _MESSAGE, _TO_THE_CHAT, (long,), subject=None, importance=None
        )

        assert _JANE.user_id in question
        assert "J" * (PREVIEW_CHARACTERS + 1) not in question
        assert f"'{'J' * PREVIEW_CHARACTERS}…' is only a label from the request" in question

    def test_the_files_come_after_the_mentions_in_the_order_given(self) -> None:
        question = send_question(
            CHAT_SEND,
            _MESSAGE,
            _TO_THE_CHAT,
            (_JANE,),
            subject=None,
            importance=None,
            files=(_BUDGET, _PLAN),
        )

        assert question == (
            "Send 'Ship it Friday.' to chat '19:release@thread.v2' now? It mentions "
            + f"{_JANE_LABELED}. It attaches 'Budget.docx', 'Plan <draft>.pptx'. This cannot be "
            + "recalled once sent."
        )

    def test_a_channel_post_names_the_channel_the_team_and_that_it_cannot_be_recalled(
        self,
    ) -> None:
        question = send_question(
            CHANNEL_POST, _MESSAGE, _TO_THE_CHANNEL, (), subject=None, importance=None
        )

        assert question == (
            "Post 'Ship it Friday.' to channel '19:general@thread.tacv2' in team "
            + "'8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81' now? This cannot be recalled once posted."
        )

    def test_a_channel_post_names_the_subject_the_importance_the_mentions_and_the_files(
        self,
    ) -> None:
        question = send_question(
            CHANNEL_POST,
            _MESSAGE,
            _TO_THE_CHANNEL,
            (_JANE,),
            subject=_SUBJECT,
            importance="high",
            files=(_BUDGET,),
        )

        assert question == (
            "Post 'Ship it Friday.' with the subject 'Release plan' and high importance to channel "
            + "'19:general@thread.tacv2' in team '8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81' now? It "
            + f"mentions {_JANE_LABELED}. It attaches 'Budget.docx'. This cannot be recalled once "
            + "posted."
        )


def _bound(
    message: str = _MESSAGE,
    chat_id: str = _CHAT_ID,
    mentions: Sequence[OutgoingMention] = (),
    *,
    subject: str | None = None,
    importance: ChatImportance | None = None,
    files: Sequence[DriveFileHandle] = (),
) -> str:
    return send_binding(
        (chat_id,), message, mentions, subject=subject, importance=importance, files=files
    )


class TestSendBinding:
    def test_the_same_request_is_bound_the_same_way_twice(self) -> None:
        assert _bound(mentions=(_JANE,), files=(_BUDGET_HANDLE,)) == _bound(
            mentions=(_JANE,), files=(_BUDGET_HANDLE,)
        )

    def test_two_messages_with_the_same_120_char_preview_are_bound_apart(self) -> None:
        common_prefix = "x" * 120

        assert _bound(common_prefix + " short tail") != _bound(
            common_prefix + " a very different, much longer tail"
        )

    def test_the_same_message_to_a_different_chat_is_bound_apart(self) -> None:
        assert _bound(chat_id=_CHAT_ID) != _bound(chat_id="19:other@thread.v2")

    def test_each_importance_is_bound_apart(self) -> None:
        importances: tuple[ChatImportance | None, ...] = (None, "normal", "high", "urgent")

        assert len({_bound(importance=importance) for importance in importances}) == 4

    def test_each_subject_is_bound_apart(self) -> None:
        subjects = (None, _SUBJECT, "Release plan, revised")

        assert len({_bound(subject=subject) for subject in subjects}) == 3

    def test_the_subject_and_the_message_are_bound_apart(self) -> None:
        assert _bound("Ship it", subject="Friday") != _bound("Ship it Friday")

    def test_each_set_of_mentions_is_bound_apart(self) -> None:
        sets: tuple[tuple[Mention, ...], ...] = (
            (),
            (_JANE,),
            (_ADA,),
            (_JANE, _ADA),
            (_ADA, _JANE),
            (Mention(user_id=_JANE.user_id, name="Ada Lovelace"),),
        )

        assert len({_bound(mentions=mentions) for mentions in sets}) == 6

    def test_each_set_of_files_is_bound_apart_and_their_order_counts(self) -> None:
        sets: tuple[tuple[DriveFileHandle, ...], ...] = (
            (),
            (_BUDGET_HANDLE,),
            (_PLAN_HANDLE,),
            (_BUDGET_HANDLE, _PLAN_HANDLE),
            (_PLAN_HANDLE, _BUDGET_HANDLE),
        )

        assert len({_bound(files=attached) for attached in sets}) == 5

    def test_a_mention_a_subject_or_an_importance_beside_a_file_is_bound_apart(self) -> None:
        cases: tuple[tuple[tuple[Mention, ...], str | None, ChatImportance | None], ...] = (
            ((), None, None),
            ((_JANE,), None, None),
            ((), _SUBJECT, None),
            ((), None, "urgent"),
        )

        bindings = {
            _bound(
                mentions=mentions,
                subject=subject,
                importance=importance,
                files=(_BUDGET_HANDLE,),
            )
            for mentions, subject, importance in cases
        }

        assert len(bindings) == 4


def _bound_in_channel(
    *,
    team_id: str = _TEAM_ID,
    channel_id: str = _CHANNEL_ID,
    reply_to_id: str | None = None,
    mentions: Sequence[Mention] = (),
    subject: str | None = None,
    importance: ChannelImportance | None = None,
    files: Sequence[DriveFileHandle] = (),
) -> str:
    return send_binding(
        (team_id, channel_id, repr(reply_to_id)),
        _MESSAGE,
        mentions,
        subject=subject,
        importance=importance,
        files=files,
    )


class TestSendBindingInAChannel:
    def test_the_same_message_to_another_team_or_another_channel_is_bound_apart(self) -> None:
        bindings = {
            _bound_in_channel(),
            _bound_in_channel(team_id="0d1e2f3a-4b5c-4d6e-8f70-8192a3b4c5d6"),
            _bound_in_channel(channel_id="19:other@thread.tacv2"),
        }

        assert len(bindings) == 3

    def test_a_new_post_and_a_reply_in_each_thread_are_bound_apart(self) -> None:
        roots = (None, _ROOT_ID, "1770000000009")

        assert len({_bound_in_channel(reply_to_id=root) for root in roots}) == 3

    def test_each_importance_of_a_channel_post_is_bound_apart(self) -> None:
        importances: tuple[ChannelImportance | None, ...] = (None, "normal", "high")

        assert len({_bound_in_channel(importance=importance) for importance in importances}) == 3

    def test_each_file_set_mention_subject_importance_and_thread_is_bound_apart(self) -> None:
        bindings = {
            _bound_in_channel(files=(_BUDGET_HANDLE,)),
            _bound_in_channel(files=(_PLAN_HANDLE,)),
            _bound_in_channel(files=(_BUDGET_HANDLE, _PLAN_HANDLE)),
            _bound_in_channel(files=(_PLAN_HANDLE, _BUDGET_HANDLE)),
            _bound_in_channel(files=(_BUDGET_HANDLE,), mentions=(_JANE,)),
            _bound_in_channel(files=(_BUDGET_HANDLE,), subject=_SUBJECT),
            _bound_in_channel(files=(_BUDGET_HANDLE,), importance="high"),
            _bound_in_channel(files=(_BUDGET_HANDLE,), reply_to_id=_ROOT_ID),
        }

        assert len(bindings) == 8


class TestSubjectOnAReply:
    def test_it_names_the_tool_says_nothing_was_posted_and_that_a_retry_fails(self) -> None:
        assert subject_on_a_reply("teams_send_channel_message") == (
            "teams_send_channel_message received both `subject` and `reply_to_id`. This tool sets "
            + "a subject only on a new channel post, never on a reply. To reply in the thread, "
            + "omit `subject`. To start a new post with a subject, omit `reply_to_id`. Nothing was "
            + "posted. If you call this tool again with the same arguments, the call will fail the "
            + "same way."
        )


class TestMentionFields:
    def test_the_count_comes_first_then_each_id_and_name_in_the_order_given(self) -> None:
        assert mention_fields((_JANE, _ADA)) == (
            "2",
            _JANE.user_id,
            "Jane Smith",
            _ADA.user_id,
            "Ada Lovelace",
        )

    def test_no_mention_is_a_count_of_zero(self) -> None:
        assert mention_fields(()) == ("0",)

    def test_a_mentioned_member_binds_its_id_and_the_name_from_microsoft_365(self) -> None:
        member = MentionedMember(user_id=_JANE.user_id, name="Jane Smith (Finance)")

        assert mention_fields((member,)) == ("1", _JANE.user_id, "Jane Smith (Finance)")


def _chat_message(*, sender: str | None, text: str | None) -> TeamsMessage:
    message = ChatMessage(
        id="1770000000000",
        from_=None
        if sender is None
        else ChatMessageFromIdentitySet(user=Identity(id=_JANE.user_id, display_name=sender)),
        body=None if text is None else ItemBody(content=text, content_type=BodyType.Text),
    )
    return TeamsMessage.from_message(
        message, handle=MessageHandle("1770000000000", chat_id=_CHAT_ID)
    )


_CHAT_PATH = "/chats/19%3Arelease%40thread.v2"
_MEMBERS_PATH = f"{_CHAT_PATH}/members"
_ADA_MEMBERSHIP = "MCMjU1lOVEhFVElDMCMj"
_GRACE_MEMBERSHIP = "MCMjU1lOVEhFVElDMSMj"


def _member(membership_id: str, name: str | None, user_id: str) -> Mapping[str, object]:
    return {
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "id": membership_id,
        "displayName": name,
        "userId": user_id,
        "email": None,
        "roles": ["owner"],
    }


_ADA_MEMBER = _member(_ADA_MEMBERSHIP, "Ada Lovelace", _ADA.user_id)
_JANE_MEMBER = _member(_GRACE_MEMBERSHIP, "Jane Smith", _JANE.user_id)


def _names_the_chat(graph: respx.MockRouter, topic: str | None) -> respx.Route:
    return graph.get(_CHAT_PATH).mock(
        return_value=httpx.Response(200, json={"id": _CHAT_ID, "topic": topic, "chatType": "group"})
    )


def _lists_members(graph: respx.MockRouter, *members: Mapping[str, object]) -> respx.Route:
    return graph.get(_MEMBERS_PATH).mock(
        return_value=httpx.Response(200, json={"value": [dict(member) for member in members]})
    )


class TestChatInQuestion:
    async def test_a_chat_with_a_topic_is_named_by_its_topic_and_its_members_are_not_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _names_the_chat(graph, _SUBJECT)
        members = _lists_members(graph, _ADA_MEMBER)

        named = await chat_in_question(client, _CHAT_ID)

        assert named == "the Teams chat 'Release plan'"
        assert members.call_count == 0

    @pytest.mark.parametrize("topic", [None, "", "   "], ids=["null", "empty", "blank"])
    async def test_a_chat_with_no_topic_is_named_by_its_members(
        self, client: GraphServiceClient, graph: respx.MockRouter, topic: str | None
    ) -> None:
        _ = _names_the_chat(graph, topic)
        _ = _lists_members(graph, _ADA_MEMBER, _JANE_MEMBER)

        named = await chat_in_question(client, _CHAT_ID)

        assert named == "the Teams chat with 'Ada Lovelace, Jane Smith'"

    async def test_the_member_left_out_is_not_named(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _names_the_chat(graph, None)
        _ = _lists_members(graph, _ADA_MEMBER, _JANE_MEMBER)

        named = await chat_in_question(client, _CHAT_ID, leaving_out=_ADA_MEMBERSHIP)

        assert named == "the Teams chat with 'Jane Smith'"

    async def test_a_member_with_no_name_is_not_named(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _names_the_chat(graph, None)
        _ = _lists_members(
            graph,
            _member("MCMjU1lOVEhFVElDMiMj", None, _JANE.user_id),
            _member("MCMjU1lOVEhFVElDMyMj", "  ", _JANE.user_id),
            _JANE_MEMBER,
        )

        named = await chat_in_question(client, _CHAT_ID)

        assert named == "the Teams chat with 'Jane Smith'"

    @pytest.mark.parametrize(
        ("members", "leaving_out"),
        [
            pytest.param((), None, id="no-member"),
            pytest.param((_member(_ADA_MEMBERSHIP, None, _ADA.user_id),), None, id="no-name"),
            pytest.param((_ADA_MEMBER,), _ADA_MEMBERSHIP, id="only-the-one-left-out"),
        ],
    )
    async def test_a_chat_with_no_name_to_show_is_a_chat_that_has_no_topic(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        members: Sequence[Mapping[str, object]],
        leaving_out: str | None,
    ) -> None:
        _ = _names_the_chat(graph, None)
        _ = _lists_members(graph, *members)

        named = await chat_in_question(client, _CHAT_ID, leaving_out=leaving_out)

        assert named == "a Teams chat that has no topic"

    async def test_a_long_topic_is_cut(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        long = "t" * (PREVIEW_CHARACTERS + 1)
        _ = _names_the_chat(graph, long)

        named = await chat_in_question(client, _CHAT_ID)

        assert named == f"the Teams chat {'t' * PREVIEW_CHARACTERS + '…'!r}"

    async def test_a_long_member_list_is_cut(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _names_the_chat(graph, None)
        _ = _lists_members(
            graph,
            *(
                _member(f"MCMj{index:04d}", f"Member number {index:04d}", _JANE.user_id)
                for index in range(20)
            ),
        )

        named = await chat_in_question(client, _CHAT_ID)

        listed = named.removeprefix("the Teams chat with ")
        assert listed != named
        assert len(listed) == len(repr("m" * PREVIEW_CHARACTERS + "…"))
        assert listed.startswith("'Member number 0000, Member number 0001")
        assert listed.endswith("…'")

    async def test_the_chat_id_and_the_user_ids_are_not_in_the_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _names_the_chat(graph, None)
        _ = _lists_members(graph, _ADA_MEMBER, _JANE_MEMBER)

        named = await chat_in_question(client, _CHAT_ID)

        assert _CHAT_ID not in named
        assert _ADA.user_id not in named
        assert _JANE.user_id not in named
        assert _ADA_MEMBERSHIP not in named

    async def test_a_refused_chat_read_passes_on_the_refusal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_CHAT_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )
        members = _lists_members(graph, _ADA_MEMBER)

        with pytest.raises(GraphForbidden):
            _ = await chat_in_question(client, _CHAT_ID)

        assert members.call_count == 0


_OUTSIDER_ID = "00000000-0000-4000-8000-000000000009"

_SECOND_MEMBERS_PAGE = f"{GRAPH_V1}{_MEMBERS_PATH}?$skiptoken=second"


def _lists_members_on_two_pages(
    graph: respx.MockRouter,
    first: Sequence[Mapping[str, object]],
    second: Sequence[Mapping[str, object]],
) -> tuple[respx.Route, respx.Route]:
    later = graph.get(_MEMBERS_PATH, params={"$skiptoken": "second"}).mock(
        return_value=httpx.Response(200, json={"value": [dict(member) for member in second]})
    )
    earlier = graph.get(_MEMBERS_PATH).mock(
        return_value=httpx.Response(
            200,
            json={
                "value": [dict(member) for member in first],
                "@odata.nextLink": _SECOND_MEMBERS_PAGE,
            },
        )
    )
    return earlier, later


class TestMentionedMembers:
    async def test_each_mention_takes_its_name_from_the_members_of_the_chat_in_one_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        members = _lists_members(
            graph, _ADA_MEMBER, _member(_GRACE_MEMBERSHIP, "Jane Smith (Finance)", _JANE.user_id)
        )
        misnamed = Mention(user_id=_JANE.user_id, name="Grace Hopper")

        resolved = await mentioned_members(client, _CHAT_ID, (misnamed, _ADA))

        assert resolved == (
            MentionedMember(user_id=_JANE.user_id, name="Jane Smith (Finance)"),
            MentionedMember(user_id=_ADA.user_id, name="Ada Lovelace"),
        )
        assert members.call_count == 1

    async def test_the_ids_compare_without_case(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists_members(graph, _JANE_MEMBER)
        shouted = Mention(user_id=_JANE.user_id.upper(), name="Jane")

        resolved = await mentioned_members(client, _CHAT_ID, (shouted,))

        assert resolved == (MentionedMember(user_id=_JANE.user_id, name="Jane Smith"),)

    async def test_no_mention_reads_no_member(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        members = _lists_members(graph, _JANE_MEMBER)

        resolved = await mentioned_members(client, _CHAT_ID, ())

        assert resolved == ()
        assert members.call_count == 0

    async def test_a_person_outside_the_chat_is_refused_and_nothing_is_sent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists_members(graph, _ADA_MEMBER)
        outsider = Mention(user_id=_OUTSIDER_ID, name="Jane Smith")

        refused = await mentioned_members(client, _CHAT_ID, (_ADA, outsider))

        assert refused == (
            "Microsoft 365 shows no named member of this chat for this Microsoft Entra object id: "
            + "'00000000-0000-4000-8000-000000000009'. This tool mentions only a member of the "
            + "chat, by the name that Microsoft 365 gives. Copy each `user_id` from a "
            + "teams_list_chat_members row for this chat. Nobody was mentioned. Nothing was sent. "
            + "If you call this tool again with the same arguments, the call will fail the same "
            + "way."
        )

    async def test_every_person_outside_the_chat_is_named_in_the_refusal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists_members(graph, _ADA_MEMBER)

        refused = await mentioned_members(
            client, _CHAT_ID, (_JANE, Mention(user_id=_OUTSIDER_ID, name="Bob"))
        )

        assert isinstance(refused, str)
        assert (
            "for these Microsoft Entra object ids: '00000000-0000-4000-8000-000000000003', "
            + "'00000000-0000-4000-8000-000000000009'."
        ) in refused
        assert "Nobody was mentioned. Nothing was sent." in refused

    async def test_the_caller_gives_the_outcome_that_the_refusal_states(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists_members(graph, _ADA_MEMBER)

        refused = await mentioned_members(
            client, _CHAT_ID, (_JANE,), nothing_happened="No message was changed."
        )

        assert isinstance(refused, str)
        assert refused.endswith(
            "Nobody was mentioned. No message was changed. If you call this tool again with the "
            + "same arguments, the call will fail the same way."
        )
        assert CHAT_SEND.nothing_sent not in refused

    @pytest.mark.parametrize(
        "member",
        [
            pytest.param(_member(_GRACE_MEMBERSHIP, None, _JANE.user_id), id="no-name"),
            pytest.param(_member(_GRACE_MEMBERSHIP, "  ", _JANE.user_id), id="blank-name"),
            pytest.param(
                {
                    **_member(_GRACE_MEMBERSHIP, "Jane Smith", _JANE.user_id),
                    "@odata.type": "#microsoft.graph.anonymousGuestConversationMember",
                },
                id="not-an-entra-user",
            ),
        ],
    )
    async def test_a_member_with_no_name_or_no_entra_id_is_refused(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        member: Mapping[str, object],
    ) -> None:
        _ = _lists_members(graph, member)

        refused = await mentioned_members(client, _CHAT_ID, (_JANE,))

        assert isinstance(refused, str)
        assert repr(_JANE.user_id) in refused
        assert "Nobody was mentioned. Nothing was sent." in refused

    async def test_the_label_of_the_request_never_reaches_the_binding(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _lists_members(graph, _JANE_MEMBER)

        bindings: set[str] = set()
        for label in ("Jane Smith", "Grace Hopper"):
            resolved = await mentioned_members(
                client, _CHAT_ID, (Mention(user_id=_JANE.user_id, name=label),)
            )
            assert not isinstance(resolved, str)
            bindings.add(_bound(mentions=resolved))

        assert len(bindings) == 1

    async def test_a_refused_member_read_passes_on_the_refusal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_MEMBERS_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await mentioned_members(client, _CHAT_ID, (_JANE,))

    async def test_the_first_page_of_members_is_not_the_whole_chat(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        first, second = _lists_members_on_two_pages(graph, (_ADA_MEMBER,), (_JANE_MEMBER,))

        resolved = await mentioned_members(client, _CHAT_ID, (_JANE, _ADA))

        assert resolved == (
            MentionedMember(user_id=_JANE.user_id, name="Jane Smith"),
            MentionedMember(user_id=_ADA.user_id, name="Ada Lovelace"),
        )
        assert (first.call_count, second.call_count) == (1, 1)

    async def test_a_person_on_no_page_is_refused_after_every_page_is_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        first, second = _lists_members_on_two_pages(graph, (_ADA_MEMBER,), (_JANE_MEMBER,))

        refused = await mentioned_members(
            client, _CHAT_ID, (_ADA, Mention(user_id=_OUTSIDER_ID, name="Bob"))
        )

        assert refused == (
            "Microsoft 365 shows no named member of this chat for this Microsoft Entra object id: "
            + "'00000000-0000-4000-8000-000000000009'. This tool mentions only a member of the "
            + "chat, by the name that Microsoft 365 gives. Copy each `user_id` from a "
            + "teams_list_chat_members row for this chat. Nobody was mentioned. Nothing was sent. "
            + "If you call this tool again with the same arguments, the call will fail the same "
            + "way."
        )
        assert (first.call_count, second.call_count) == (1, 1)

    async def test_no_page_is_read_after_every_mention_is_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        first, second = _lists_members_on_two_pages(
            graph, (_ADA_MEMBER, _JANE_MEMBER), (_member(_ADA_MEMBERSHIP, "Ada", _OUTSIDER_ID),)
        )

        resolved = await mentioned_members(client, _CHAT_ID, (_JANE, _ADA))

        assert resolved == (
            MentionedMember(user_id=_JANE.user_id, name="Jane Smith"),
            MentionedMember(user_id=_ADA.user_id, name="Ada Lovelace"),
        )
        assert (first.call_count, second.call_count) == (1, 0)

    async def test_a_chat_with_more_members_than_the_scan_reads_is_refused_and_says_so(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        crowd = tuple(
            _member(
                f"MCMj{index:04d}", f"Member {index:04d}", f"10000000-0000-4000-8000-{index:012d}"
            )
            for index in range(MAX_SCANNED_ITEMS)
        )
        first, second = _lists_members_on_two_pages(graph, crowd, (_JANE_MEMBER,))

        refused = await mentioned_members(client, _CHAT_ID, (_JANE,))

        assert refused == (
            "Microsoft 365 shows more than 1000 members of this chat, and this tool reads only the "
            + "first 1000. Among these members, Microsoft 365 shows no named member for this "
            + "Microsoft Entra object id: '00000000-0000-4000-8000-000000000003'. This tool "
            + "mentions only a member of the chat, by the name that Microsoft 365 gives. Nobody "
            + "was mentioned. Nothing was sent. If you call this tool again with the same "
            + "arguments, the call will fail the same way."
        )
        assert (first.call_count, second.call_count) == (1, 0)


class TestMessageInQuestion:
    def test_it_names_the_sender_and_quotes_the_text(self) -> None:
        said = message_in_question(_chat_message(sender="Jane Smith", text=_MESSAGE))

        assert said == "the Teams message from 'Jane Smith' that says 'Ship it Friday.'"

    def test_a_message_with_no_sender_names_nobody(self) -> None:
        said = message_in_question(_chat_message(sender=None, text=_MESSAGE))

        assert said == "the Teams message that says 'Ship it Friday.'"

    def test_a_message_with_no_text_says_so(self) -> None:
        said = message_in_question(_chat_message(sender="Jane Smith", text=None))

        assert said == "the Teams message from 'Jane Smith' that has no text"

    def test_a_long_text_is_cut(self) -> None:
        long = "a" * (PREVIEW_CHARACTERS + 1)

        said = message_in_question(_chat_message(sender=None, text=long))

        assert long not in said
        assert f"{'a' * PREVIEW_CHARACTERS}…" in said


_SENDER_ID = "9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f"


def _sent(sender: ChatMessageFromIdentitySet | None) -> TeamsMessage:
    return TeamsMessage.from_message(
        ChatMessage(id="1770000000000", from_=sender),
        handle=MessageHandle("1770000000000", chat_id=_CHAT_ID),
    )


def _sent_by_user(user_id: str | None) -> TeamsMessage:
    return _sent(ChatMessageFromIdentitySet(user=Identity(id=user_id, display_name="Grace Hopper")))


class TestWhoSentTheMessage:
    def test_the_sender_is_the_signed_in_user(self) -> None:
        assert sent_by(_sent_by_user(_SENDER_ID), User(id=_SENDER_ID))

    def test_another_person_is_not_the_signed_in_user(self) -> None:
        assert not sent_by(_sent_by_user(_JANE.user_id), User(id=_SENDER_ID))

    def test_the_ids_compare_without_case(self) -> None:
        assert sent_by(_sent_by_user(_SENDER_ID.upper()), User(id=_SENDER_ID))

    @pytest.mark.parametrize(
        "message",
        [
            pytest.param(_sent(None), id="no-sender"),
            pytest.param(
                _sent(
                    ChatMessageFromIdentitySet(
                        application=Identity(id=_SENDER_ID, display_name="Release bot")
                    )
                ),
                id="application",
            ),
            pytest.param(_sent_by_user(None), id="no-id"),
        ],
    )
    def test_a_message_that_names_no_user_is_not_sent_by_the_user(
        self, message: TeamsMessage
    ) -> None:
        assert not sent_by(message, User(id=_SENDER_ID))

    def test_a_user_with_no_id_sent_nothing(self) -> None:
        assert not sent_by(_sent_by_user(_SENDER_ID), User())


class TestNotTheSender:
    def test_the_refusal_says_what_the_tool_does_only_for_the_sender(self) -> None:
        refused = not_the_sender("changes", tail="No message was changed.")

        assert refused == (
            "Microsoft 365 does not name the signed-in user as the sender of this message. This "
            + "tool changes only a message that the signed-in user sent. No message was changed."
        )


class TestUnknownEnumHeaders:
    def test_asks_graph_for_the_unknown_enum_members(self) -> None:
        assert unknown_enum_headers().get_all() == {"prefer": {"include-unknown-enum-members"}}

    def test_every_call_builds_its_own_collection(self) -> None:
        assert unknown_enum_headers() is not unknown_enum_headers()
