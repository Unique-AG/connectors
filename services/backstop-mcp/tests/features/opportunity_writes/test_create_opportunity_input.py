"""`CreateOpportunityInput`: required name, currency, ERISA, and investor selector."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.opportunity_writes import CreateOpportunityInput

_ADAPTER: TypeAdapter[CreateOpportunityInput] = TypeAdapter(CreateOpportunityInput)

_MINIMAL = {
    "name": "Koch - CATS Select",
    "currency_code": "USD",
    "is_erisa": False,
    "party_id": "c1",
}


def test_accepts_the_minimal_create() -> None:
    parsed = _ADAPTER.validate_python(_MINIMAL)

    assert parsed.name == "Koch - CATS Select"
    assert parsed.currency_code == "USD"
    assert parsed.is_erisa is False
    assert parsed.party_id == "c1"
    assert parsed.search_type == "contacts"
    assert parsed.stage is None


def test_missing_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match="name"):
        _ADAPTER.validate_python({"currency_code": "USD", "is_erisa": False, "party_id": "c1"})


def test_missing_currency_code_is_rejected() -> None:
    with pytest.raises(ValidationError, match="currency_code"):
        _ADAPTER.validate_python(
            {"name": "Koch - CATS Select", "is_erisa": False, "party_id": "c1"}
        )


def test_missing_is_erisa_is_rejected() -> None:
    with pytest.raises(ValidationError, match="is_erisa"):
        _ADAPTER.validate_python(
            {"name": "Koch - CATS Select", "currency_code": "USD", "party_id": "c1"}
        )


def test_missing_investor_selector_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Exactly one of party_id or search"):
        _ADAPTER.validate_python(
            {"name": "Koch - CATS Select", "currency_code": "USD", "is_erisa": False}
        )


def test_two_investor_selectors_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Exactly one of party_id or search"):
        _ADAPTER.validate_python({**_MINIMAL, "search": "Koch"})


def test_identity_and_required_fields_lead_the_schema() -> None:
    assert list(CreateOpportunityInput.model_fields)[:6] == [
        "search_type",
        "party_id",
        "search",
        "name",
        "currency_code",
        "is_erisa",
    ]


def test_stage_description_does_not_say_replacement_or_only_way_to_move() -> None:
    description = CreateOpportunityInput.model_fields["stage"].description or ""

    assert "Replacement" not in description
    assert "only way to move" not in description
