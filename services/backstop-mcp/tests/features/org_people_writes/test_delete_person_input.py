"""`DeletePersonInput`: a trusted person id."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.org_people_writes import DeletePersonInput

_ADAPTER: TypeAdapter[DeletePersonInput] = TypeAdapter(DeletePersonInput)


def test_accepts_party_id_with_search_type() -> None:
    parsed = _ADAPTER.validate_python({"search_type": "people", "party_id": "27871657"})

    assert parsed.party_id == "27871657"
    assert parsed.search_type == "people"


def test_defaults_search_type_to_people() -> None:
    parsed = _ADAPTER.validate_python({"party_id": "27871657"})

    assert parsed.search_type == "people"


def test_rejects_missing_party_id() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"search_type": "people"})
