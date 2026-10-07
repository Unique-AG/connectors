from backstop_mcp.features.custom_fields import (
    CustomFieldMatch,
    CustomFieldValueAttributes,
    display_text,
    normalize_matches,
    satisfies_every,
    stored_custom_field_values,
)


def _value(
    definition_id: str | None, value: object, name: str = "Field"
) -> CustomFieldValueAttributes:
    return CustomFieldValueAttributes.model_validate(
        {"definitionId": definition_id, "name": name, "value": value}
    )


class TestDisplayText:
    def test_scalars_become_text(self) -> None:
        assert display_text("  Tier 1 ") == "Tier 1"
        assert display_text(True) == "true"
        assert display_text(False) == "false"
        assert display_text(0.3) == "0.3"

    def test_a_multi_select_is_joined_and_blanks_are_dropped(self) -> None:
        assert display_text(["EMEA", " ", None, "APAC"]) == "EMEA; APAC"

    def test_unset_values_have_no_text(self) -> None:
        for unset in (None, "", "   ", [], [None, ""], {"nested": 1}):
            assert display_text(unset) is None


class TestStoredCustomFieldValues:
    def test_publishes_every_set_value_in_wire_order(self) -> None:
        published = stored_custom_field_values(
            [
                _value("2", ["a", "b"], "Tags"),
                _value("1", "Tier 1", "Relationship"),
                _value("3", None, "Unset"),
                _value(None, "orphan", "No id"),
            ]
        )

        assert [(item.definition_id, item.name, item.value) for item in published] == [
            ("2", "Tags", "a; b"),
            ("1", "Relationship", "Tier 1"),
        ]


class TestSatisfiesEvery:
    def test_no_predicates_match_everything(self) -> None:
        assert satisfies_every([], []) is True

    def test_compares_whole_values_case_insensitively(self) -> None:
        values = [_value("10", "Alpha")]

        assert satisfies_every(values, [CustomFieldMatch("10", ("alpha",))]) is True
        assert satisfies_every(values, [CustomFieldMatch("10", ("Alph",))]) is False

    def test_a_list_value_matches_on_any_element(self) -> None:
        values = [_value("12", ["EMEA", "US"])]

        assert satisfies_every(values, [CustomFieldMatch("12", ("us",))]) is True

    def test_predicates_and_together_and_values_or(self) -> None:
        values = [_value("1", "Tier 1"), _value("2", "Stage B")]

        assert satisfies_every(
            values,
            [
                CustomFieldMatch("1", ("tier 1",)),
                CustomFieldMatch("2", ("Stage A", "Stage B")),
            ],
        )
        assert not satisfies_every(
            values,
            [CustomFieldMatch("1", ("tier 1",)), CustomFieldMatch("3", ("x",))],
        )

    def test_a_missing_value_never_matches(self) -> None:
        assert satisfies_every([_value("1", None)], [CustomFieldMatch("1", ("",))]) is False


class TestNormalizeMatches:
    def test_strips_and_drops_empty_predicates(self) -> None:
        assert normalize_matches(
            [
                CustomFieldMatch(" 10 ", (" yes ", " ")),
                CustomFieldMatch("", ("x",)),
                CustomFieldMatch("11", (" ",)),
            ]
        ) == (CustomFieldMatch("10", ("yes",)),)
