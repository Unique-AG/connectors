"""`EndEmploymentInput`: both parties and an end date."""

from datetime import date

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.org_people_writes import EndEmploymentInput

_ADAPTER: TypeAdapter[EndEmploymentInput] = TypeAdapter(EndEmploymentInput)


def test_accepts_trusted_ids() -> None:
    parsed = _ADAPTER.validate_python(
        {
            "party_id": "p1",
            "organization_id": "o1",
            "end_date": "2026-01-15",
        }
    )

    assert parsed.party_id == "p1"
    assert parsed.organization_id == "o1"
    assert parsed.end_date == date(2026, 1, 15)


def test_rejects_two_person_selectors() -> None:
    with pytest.raises(ValidationError, match="Exactly one of party_id or search"):
        _ADAPTER.validate_python(
            {
                "party_id": "p1",
                "search": "Jane",
                "organization_id": "o1",
                "end_date": "2026-01-15",
            }
        )


def test_rejects_two_organization_selectors() -> None:
    with pytest.raises(ValidationError, match="organization_id or organization_search"):
        _ADAPTER.validate_python(
            {
                "party_id": "p1",
                "organization_id": "o1",
                "organization_search": "Acme",
                "end_date": "2026-01-15",
            }
        )
