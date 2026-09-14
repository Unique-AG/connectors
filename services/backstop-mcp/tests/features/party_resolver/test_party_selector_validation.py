"""Shared party-selector validators used by resolve, activity writes, and activity history."""

import pytest

from backstop_mcp.features.party_resolver import (
    blank_to_none,
    require_exactly_one_party_selector,
    require_path_segment,
)


def test_blank_to_none_coerces_whitespace_and_empty() -> None:
    assert blank_to_none("") is None
    assert blank_to_none("   ") is None
    assert blank_to_none("o1") == "o1"
    assert blank_to_none(None) is None


def test_require_exactly_one_party_selector_accepts_either_side() -> None:
    require_exactly_one_party_selector(party_id="o1", search=None)
    require_exactly_one_party_selector(party_id=None, search="Northwind")


@pytest.mark.parametrize(
    ("party_id", "search"),
    [(None, None), ("o1", "Northwind")],
)
def test_require_exactly_one_party_selector_rejects_both_or_neither(
    party_id: str | None, search: str | None
) -> None:
    with pytest.raises(ValueError, match="Exactly one of party_id or search"):
        require_exactly_one_party_selector(party_id=party_id, search=search)


def test_require_exactly_one_party_selector_rejects_a_slash_in_party_id() -> None:
    with pytest.raises(ValueError, match="must not contain '/'"):
        require_exactly_one_party_selector(party_id="../admin", search=None)


def test_require_path_segment_uses_the_field_name() -> None:
    require_path_segment("o1", field_name="entity_id")
    with pytest.raises(ValueError, match="entity_id '../admin' must not contain '/'"):
        require_path_segment("../admin", field_name="entity_id")
