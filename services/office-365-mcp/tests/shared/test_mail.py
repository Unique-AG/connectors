import pytest
from msgraph.generated.models.followup_flag import FollowupFlag
from msgraph.generated.models.followup_flag_status import FollowupFlagStatus
from msgraph.generated.models.message import Message

from office_365_mcp.shared.mail import carries_category, copied_and_marked, has_flag_state


def _flagged_as(status: FollowupFlagStatus) -> Message:
    return Message(flag=FollowupFlag(flag_status=status))


class TestHasFlagState:
    @pytest.mark.parametrize(
        ("status", "flagged", "matches"),
        [
            (FollowupFlagStatus.Flagged, True, True),
            (FollowupFlagStatus.Flagged, False, False),
            (FollowupFlagStatus.Complete, True, False),
            (FollowupFlagStatus.Complete, False, True),
            (FollowupFlagStatus.NotFlagged, True, False),
            (FollowupFlagStatus.NotFlagged, False, True),
        ],
    )
    def test_only_the_status_flagged_counts_as_flagged(
        self, status: FollowupFlagStatus, flagged: bool, matches: bool
    ) -> None:
        assert has_flag_state(_flagged_as(status), flagged) is matches

    @pytest.mark.parametrize("flagged", [True, False])
    def test_a_message_with_no_flag_matches_neither_value(self, flagged: bool) -> None:
        assert has_flag_state(Message(), flagged) is False


class TestCarriesCategory:
    def test_the_match_ignores_case(self) -> None:
        message = Message(categories=["Red category", "invoices"])

        assert carries_category(message, "INVOICES") is True
        assert carries_category(message, "red CATEGORY") is True

    def test_a_part_of_a_name_is_not_the_name(self) -> None:
        assert carries_category(Message(categories=["Red category"]), "Red") is False

    def test_a_message_with_no_categories_carries_none(self) -> None:
        assert carries_category(Message(), "Invoices") is False
        assert carries_category(Message(categories=[]), "Invoices") is False


class TestCopiedAndMarked:
    def test_nothing_to_say_is_the_empty_text(self) -> None:
        assert copied_and_marked((), importance=None, categories=()) == ""

    def test_each_part_that_is_set_adds_one_sentence(self) -> None:
        said = copied_and_marked(
            ["ada@example.invalid", "bob@example.invalid"],
            importance="high",
            categories=["Invoices", "Red"],
        )

        assert said == (
            " It is copied to ada@example.invalid, bob@example.invalid."
            " It has high importance."
            " It is tagged Invoices, Red."
        )
