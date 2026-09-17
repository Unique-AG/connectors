"""`DeletePersonInput`: same identity as `update_person`."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.org_people_writes import DeletePersonInput

_ADAPTER: TypeAdapter[DeletePersonInput] = TypeAdapter(DeletePersonInput)


def test_accepts_party_id_with_search_type() -> None:
    parsed = _ADAPTER.validate_python({"search_type": "people", "party_id": "27871657"})

    assert parsed.party_id == "27871657"
    assert parsed.search_type == "people"
    assert parsed.search is None


def test_defaults_search_type_to_people() -> None:
    parsed = _ADAPTER.validate_python({"party_id": "27871657"})

    assert parsed.search_type == "people"


def test_rejects_both_selectors() -> None:
    with pytest.raises(ValidationError, match="Exactly one"):
        _ADAPTER.validate_python({"party_id": "27871657", "search": "Jane Doe"})


def test_rejects_neither_selector() -> None:
    with pytest.raises(ValidationError, match="Exactly one"):
        _ADAPTER.validate_python({"search_type": "people"})
