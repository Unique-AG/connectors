from collections.abc import Sequence

import pytest
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.chat_message_importance import ChatMessageImportance
from pydantic import ValidationError

from office_365_mcp.shared.messages import (
    CHANNEL_POST,
    CHAT_SEND,
    ChannelImportance,
    ChatImportance,
    Mention,
    mention_fields,
    outgoing_message,
    send_binding,
    send_question,
    subject_on_a_reply,
)

_JANE = Mention(user_id="00000000-0000-4000-8000-000000000003", name="Jane Smith")
_ADA = Mention(user_id="00000000-0000-4000-8000-000000000001", name="Ada Lovelace")

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
            + "'19:release@thread.v2' now? It mentions 'Jane Smith', 'Ada Lovelace'. This cannot "
            + "be recalled once sent."
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


def _bound(
    message: str = _MESSAGE,
    chat_id: str = _CHAT_ID,
    mentions: Sequence[Mention] = (),
    *,
    subject: str | None = None,
    importance: ChatImportance | None = None,
) -> str:
    return send_binding((chat_id,), message, mentions, subject=subject, importance=importance)


class TestSendBinding:
    def test_the_same_request_is_bound_the_same_way_twice(self) -> None:
        assert _bound(mentions=(_JANE,)) == _bound(mentions=(_JANE,))

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


def _bound_in_channel(
    *,
    team_id: str = _TEAM_ID,
    channel_id: str = _CHANNEL_ID,
    reply_to_id: str | None = None,
    mentions: Sequence[Mention] = (),
    subject: str | None = None,
    importance: ChannelImportance | None = None,
) -> str:
    return send_binding(
        (team_id, channel_id, repr(reply_to_id)),
        _MESSAGE,
        mentions,
        subject=subject,
        importance=importance,
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
