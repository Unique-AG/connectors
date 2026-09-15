"""`CreateEmploymentInput`: both parties and a start date."""

from datetime import date

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.org_people_writes import CreateEmploymentInput

_ADAPTER: TypeAdapter[CreateEmploymentInput] = TypeAdapter(CreateEmploymentInput)


def test_accepts_trusted_ids() -> None:
    parsed = _ADAPTER.validate_python(
        {
            "party_id": "p1",
            "organization_id": "o1",
            "start_date": "2026-01-15",
        }
    )

    assert parsed.party_id == "p1"
    assert parsed.organization_id == "o1"
    assert parsed.start_date == date(2026, 1, 15)


def test_rejects_two_person_selectors() -> None:
    with pytest.raises(ValidationError, match="Exactly one of party_id or search"):
        _ADAPTER.validate_python(
            {
                "party_id": "p1",
                "search": "Jane",
                "organization_id": "o1",
                "start_date": "2026-01-15",
            }
        )


def test_rejects_neither_person_selector() -> None:
    with pytest.raises(ValidationError, match="Exactly one of party_id or search"):
        _ADAPTER.validate_python(
            {
                "organization_id": "o1",
                "start_date": "2026-01-15",
            }
        )


def test_rejects_two_organization_selectors() -> None:
    with pytest.raises(ValidationError, match="organization_id or organization_search"):
        _ADAPTER.validate_python(
            {
                "party_id": "p1",
                "organization_id": "o1",
                "organization_search": "Acme",
                "start_date": "2026-01-15",
            }
        )


def test_rejects_neither_organization_selector() -> None:
    with pytest.raises(ValidationError, match="organization_id or organization_search"):
        _ADAPTER.validate_python(
            {
                "party_id": "p1",
                "start_date": "2026-01-15",
            }
        )


def test_rejects_missing_start_date() -> None:
    with pytest.raises(ValidationError, match="start_date"):
        _ADAPTER.validate_python({"party_id": "p1", "organization_id": "o1"})
