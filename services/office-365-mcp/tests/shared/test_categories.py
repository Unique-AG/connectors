import json

import pytest
from pydantic import TypeAdapter, ValidationError

from office_365_mcp.shared.categories import (
    LIST_CATEGORIES_GUARD,
    CategoryName,
    merged_categories,
    named_in_both,
)


class TestTheCategoryMerge:
    def test_a_new_name_comes_after_the_names_the_item_has(self) -> None:
        assert merged_categories(["Budget"], add=["Blue category"], remove=[]) == [
            "Budget",
            "Blue category",
        ]

    def test_a_name_the_item_has_in_another_case_keeps_its_own_spelling(self) -> None:
        assert merged_categories(["Budget"], add=["BUDGET"], remove=[]) == ["Budget"]

    def test_a_removed_name_goes_whatever_its_case(self) -> None:
        assert merged_categories(["Budget", "Blue category"], add=[], remove=["BLUE CATEGORY"]) == [
            "Budget"
        ]

    def test_a_name_added_twice_is_added_once(self) -> None:
        assert merged_categories([], add=["Budget", "budget"], remove=[]) == ["Budget"]

    def test_removing_every_name_leaves_an_empty_list(self) -> None:
        assert merged_categories(["Budget"], add=[], remove=["Budget"]) == []

    def test_the_current_list_is_left_as_it_was(self) -> None:
        current = ["Budget"]

        _ = merged_categories(current, add=["Blue category"], remove=["Budget"])

        assert current == ["Budget"]


class TestTheNameInBothLists:
    def test_lists_with_no_name_in_common_give_none(self) -> None:
        assert named_in_both(["Budget"], ["Blue category"]) is None

    @pytest.mark.parametrize(
        ("add", "remove"),
        [([], []), (["Budget"], []), ([], ["Budget"])],
        ids=["both-empty", "nothing-removed", "nothing-added"],
    )
    def test_an_empty_list_gives_none(self, add: list[str], remove: list[str]) -> None:
        assert named_in_both(add, remove) is None

    def test_a_name_that_differs_only_in_case_comes_back_as_the_add_list_spells_it(self) -> None:
        assert named_in_both(["Budget"], ["BUDGET"]) == "Budget"

    def test_the_first_match_in_the_add_list_wins(self) -> None:
        assert named_in_both(["Red", "Blue", "Green"], ["green", "BLUE"]) == "Blue"


class TestTheCategoryName:
    def test_a_list_of_names_is_accepted(self) -> None:
        assert TypeAdapter(list[CategoryName]).validate_python(["Red"]) == ["Red"]

    def test_a_name_with_spaces_around_a_visible_character_is_kept_as_given(self) -> None:
        assert TypeAdapter(list[CategoryName]).validate_python([" Red "]) == [" Red "]

    @pytest.mark.parametrize(
        "name",
        ["", "  ", "\t"],
        ids=["empty", "spaces", "tab"],
    )
    def test_a_name_with_no_visible_character_is_refused(self, name: str) -> None:
        with pytest.raises(ValidationError):
            _ = TypeAdapter(list[CategoryName]).validate_python([name])

    def test_the_schema_inlines_a_minimum_length_of_one_and_a_visible_character(self) -> None:
        schema = TypeAdapter(list[CategoryName]).json_schema()

        assert schema["items"]["minLength"] == 1
        assert schema["items"]["pattern"] == "\\S"
        assert "$ref" not in json.dumps(schema)


class TestTheListerGuard:
    def test_the_sentence_promises_the_lister_only_where_the_deployment_has_it(self) -> None:
        assert LIST_CATEGORIES_GUARD == (
            "If this deployment exposes outlook_list_categories, that tool lists only the "
            "category names of the signed-in user's own mailbox."
        )
