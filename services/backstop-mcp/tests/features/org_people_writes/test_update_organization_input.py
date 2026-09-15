"""`UpdateOrganizationInput`: required name, local maxLength, exclusive category fields."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.org_people_writes import UpdateOrganizationInput

_ADAPTER: TypeAdapter[UpdateOrganizationInput] = TypeAdapter(UpdateOrganizationInput)


def test_accepts_a_website_patch() -> None:
    parsed = _ADAPTER.validate_python({"party_id": "1001", "website": "https://example.com"})

    assert parsed.party_id == "1001"
    assert parsed.website == "https://example.com"


def test_rejects_an_update_with_no_change_fields() -> None:
    with pytest.raises(ValidationError, match="Pass at least one field to change"):
        _ADAPTER.validate_python({"party_id": "1001"})


def test_over_length_name_is_rejected_by_the_input_model() -> None:
    with pytest.raises(ValidationError, match="50"):
        _ADAPTER.validate_python({"party_id": "1001", "name": "x" * 51})


def test_clearing_a_required_attribute_is_rejected_by_the_input_model() -> None:
    with pytest.raises(ValidationError, match="name cannot be cleared"):
        _ADAPTER.validate_python({"party_id": "1001", "name": "   "})


def test_an_explicit_null_name_is_rejected_rather_than_ignored() -> None:
    with pytest.raises(ValidationError, match="name cannot be cleared"):
        _ADAPTER.validate_python({"party_id": "1001", "name": None})


def test_add_and_replace_category_ids_together_are_rejected() -> None:
    with pytest.raises(ValidationError, match="not both"):
        _ADAPTER.validate_python(
            {
                "party_id": "1001",
                "add_category_ids": ["c1"],
                "replace_category_ids": ["c2"],
            }
        )
