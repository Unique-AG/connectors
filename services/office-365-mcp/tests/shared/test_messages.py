import pytest
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.chat_message_importance import ChatMessageImportance
from pydantic import ValidationError

from office_365_mcp.shared.messages import Mention, outgoing_message

_JANE = Mention(user_id="00000000-0000-4000-8000-000000000003", name="Jane Smith")
_ADA = Mention(user_id="00000000-0000-4000-8000-000000000001", name="Ada Lovelace")


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
