"""`UpdatePersonInput`: required last name, local maxLength, exclusive category fields."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.org_people_writes import UpdatePersonInput

_ADAPTER: TypeAdapter[UpdatePersonInput] = TypeAdapter(UpdatePersonInput)


def test_accepts_a_job_title_patch() -> None:
    parsed = _ADAPTER.validate_python({"party_id": "27871657", "job_title": "Managing Director"})

    assert parsed.party_id == "27871657"
    assert parsed.job_title == "Managing Director"


def test_rejects_an_update_with_no_change_fields() -> None:
    with pytest.raises(ValidationError, match="Pass at least one field to change"):
        _ADAPTER.validate_python({"party_id": "27871657"})


def test_over_length_job_title_is_rejected_by_the_input_model() -> None:
    with pytest.raises(ValidationError, match="140"):
        _ADAPTER.validate_python({"party_id": "27871657", "job_title": "x" * 141})


def test_clearing_a_required_attribute_is_rejected_by_the_input_model() -> None:
    with pytest.raises(ValidationError, match="last_name cannot be cleared"):
        _ADAPTER.validate_python({"party_id": "27871657", "last_name": "   "})


def test_empty_replace_category_ids_counts_as_a_change() -> None:
    parsed = _ADAPTER.validate_python({"party_id": "27871657", "replace_category_ids": []})

    assert parsed.replace_category_ids == ()


def test_add_and_replace_category_ids_together_are_rejected() -> None:
    with pytest.raises(ValidationError, match="not both"):
        _ADAPTER.validate_python(
            {
                "party_id": "27871657",
                "add_category_ids": ["c1"],
                "replace_category_ids": ["c2"],
            }
        )


def test_create_location_requires_title() -> None:
    with pytest.raises(ValidationError, match="location_title is required"):
        _ADAPTER.validate_python({"party_id": "27871657", "location": {"city": "Chicago"}})
