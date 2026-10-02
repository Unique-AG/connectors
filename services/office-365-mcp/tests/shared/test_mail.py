import pytest
from msgraph.generated.models.followup_flag import FollowupFlag
from msgraph.generated.models.followup_flag_status import FollowupFlagStatus
from msgraph.generated.models.message import Message

from office_365_mcp.shared.mail import (
    AddressFault,
    carries_category,
    copied_and_marked,
    has_flag_state,
    one_address_each,
    repeated_address,
)

_ADA = "ada@example.invalid"
_ALEX = "alex@example.invalid"


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


class TestOnePersonInvitedOnce:
    def test_the_repeat_is_the_entry_that_names_an_address_already_named(self) -> None:
        assert repeated_address([_ADA, _ALEX, _ADA]) == _ADA

    def test_case_is_not_a_second_person(self) -> None:
        assert repeated_address([_ADA, _ADA.upper()]) == _ADA.upper()

    @pytest.mark.parametrize(
        "addresses",
        [[], [_ADA], [_ADA, _ALEX]],
        ids=["nobody", "one-person", "two-people"],
    )
    def test_a_list_that_names_everybody_once_has_no_repeat(self, addresses: list[str]) -> None:
        assert repeated_address(addresses) is None


class TestOneAddressEach:
    def test_plain_addresses_come_back_trimmed_and_in_order(self) -> None:
        assert one_address_each([f"  {_ALEX} ", _ADA]) == (_ALEX, _ADA)

    def test_no_entry_is_no_fault(self) -> None:
        assert one_address_each([]) == ()

    @pytest.mark.parametrize(
        ("entry", "named"),
        [
            ("", ""),
            ("   ", ""),
            ("Ada Lovelace", "Ada Lovelace"),
            (f" Ada Lovelace <{_ADA}> ", f"Ada Lovelace <{_ADA}>"),
            (f"{_ADA}, {_ALEX}", f"{_ADA}, {_ALEX}"),
            (f"{_ADA}; {_ALEX}", f"{_ADA}; {_ALEX}"),
            (f"{_ADA} {_ALEX}", f"{_ADA} {_ALEX}"),
        ],
        ids=[
            "empty",
            "blank",
            "display-name-alone",
            "name-and-angle-brackets",
            "two-with-a-comma",
            "two-with-a-semicolon",
            "two-with-a-space",
        ],
    )
    def test_an_entry_that_is_not_one_address_is_named_as_trimmed(
        self, entry: str, named: str
    ) -> None:
        assert one_address_each([_ALEX, entry]) == AddressFault(entry=named, repeated=False)

    def test_a_repeat_that_differs_only_in_case_is_named_as_written(self) -> None:
        assert one_address_each([_ADA, _ALEX, _ADA.upper()]) == AddressFault(
            entry=_ADA.upper(), repeated=True
        )

    def test_a_repeat_that_differs_only_in_spaces_is_still_a_repeat(self) -> None:
        assert one_address_each([_ADA, f"  {_ADA}"]) == AddressFault(entry=_ADA, repeated=True)

    def test_an_entry_that_is_not_one_address_is_named_before_a_repeat(self) -> None:
        assert one_address_each([_ADA, _ADA, "Ada Lovelace"]) == AddressFault(
            entry="Ada Lovelace", repeated=False
        )
