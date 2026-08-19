import pytest

from backstop_mcp.features.data_hygiene import AsOfResponse, ProvenanceFields, extract_as_of


def _attrs(payload: dict[str, object]) -> ProvenanceFields:
    return ProvenanceFields.model_validate(payload)


class TestExtractAsOf:
    def test_returns_none_when_both_missing(self) -> None:
        assert extract_as_of(_attrs({})) is None
        assert extract_as_of(None) is None
        assert extract_as_of(_attrs({"name": "Acme"})) is None

    def test_extracts_timestamp_and_by(self) -> None:
        assert extract_as_of(
            _attrs({"modifiedTimestamp": "2024-01-01T00:00:00Z", "modifiedBy": "alice"})
        ) == AsOfResponse(modified_timestamp="2024-01-01T00:00:00Z", modified_by="alice")

    def test_timestamp_alone_is_enough(self) -> None:
        assert extract_as_of(_attrs({"modifiedTimestamp": "2024-01-01"})) == AsOfResponse(
            modified_timestamp="2024-01-01", modified_by=None
        )

    def test_actor_alone_is_enough(self) -> None:
        assert extract_as_of(_attrs({"modifiedBy": "alice"})) == AsOfResponse(
            modified_timestamp=None, modified_by="alice"
        )

    def test_blank_values_count_as_missing(self) -> None:
        assert extract_as_of(_attrs({"modifiedTimestamp": "  ", "modifiedBy": ""})) is None

    def test_values_are_stripped(self) -> None:
        assert extract_as_of(_attrs({"modifiedTimestamp": " 2024-01-01 "})) == AsOfResponse(
            modified_timestamp="2024-01-01", modified_by=None
        )


class TestNestedModifiedBy:
    """Some instances nest the actor as an object rather than a bare string."""

    @pytest.mark.parametrize(
        ("actor", "expected"),
        [
            ({"name": "bob"}, "bob"),
            ({"displayName": "Bob Smith"}, "Bob Smith"),
            ({"display_name": "Bob Smith"}, "Bob Smith"),
            ({"id": "u-7"}, "u-7"),
            # A name beats the id it sits next to.
            ({"id": "u-7", "name": "bob"}, "bob"),
        ],
    )
    def test_the_first_readable_label_wins(self, actor: dict[str, str], expected: str) -> None:
        assert extract_as_of(_attrs({"modifiedBy": actor})) == AsOfResponse(
            modified_timestamp=None, modified_by=expected
        )

    def test_an_object_with_no_readable_label_is_dropped(self) -> None:
        assert extract_as_of(_attrs({"modifiedBy": {"href": "/users/7"}})) is None

    def test_a_non_string_non_object_actor_is_dropped(self) -> None:
        assert extract_as_of(_attrs({"modifiedBy": 7})) is None
