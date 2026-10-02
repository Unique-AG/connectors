from office_365_mcp.shared.categories import LIST_CATEGORIES_GUARD, merged_categories


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


class TestTheListerGuard:
    def test_the_sentence_promises_the_lister_only_where_the_deployment_has_it(self) -> None:
        assert LIST_CATEGORIES_GUARD == (
            "If this deployment exposes outlook_list_categories, that tool lists the category "
            "names of the mailbox."
        )
