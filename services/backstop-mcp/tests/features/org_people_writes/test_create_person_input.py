"""`CreatePersonInput`: required last name and gender, local maxLength."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.org_people_writes import CreatePersonInput

_ADAPTER: TypeAdapter[CreatePersonInput] = TypeAdapter(CreatePersonInput)


def test_accepts_the_minimal_create() -> None:
    parsed = _ADAPTER.validate_python({"last_name": "Smith", "gender": "Female"})

    assert parsed.last_name == "Smith"
    assert parsed.gender == "Female"
    assert parsed.category_ids == ()


def test_over_length_job_title_is_rejected_by_the_input_model() -> None:
    with pytest.raises(ValidationError, match="140"):
        _ADAPTER.validate_python({"last_name": "Smith", "gender": "Female", "job_title": "x" * 141})


def test_missing_last_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match="last_name"):
        _ADAPTER.validate_python({"gender": "Female"})


def test_missing_gender_is_rejected() -> None:
    with pytest.raises(ValidationError, match="gender"):
        _ADAPTER.validate_python({"last_name": "Smith"})
