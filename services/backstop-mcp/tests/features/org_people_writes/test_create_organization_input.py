"""`CreateOrganizationInput`: required name, local maxLength."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.org_people_writes import CreateOrganizationInput

_ADAPTER: TypeAdapter[CreateOrganizationInput] = TypeAdapter(CreateOrganizationInput)


def test_accepts_the_minimal_create() -> None:
    parsed = _ADAPTER.validate_python({"name": "Acme"})

    assert parsed.name == "Acme"
    assert parsed.category_ids == ()


def test_over_length_name_is_rejected_by_the_input_model() -> None:
    with pytest.raises(ValidationError, match="50"):
        _ADAPTER.validate_python({"name": "x" * 51})


def test_missing_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match="name"):
        _ADAPTER.validate_python({})
