"""`DeleteOrganizationInput`: same identity as `update_organization`."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.org_people_writes import DeleteOrganizationInput

_ADAPTER: TypeAdapter[DeleteOrganizationInput] = TypeAdapter(DeleteOrganizationInput)


def test_accepts_party_id_with_search_type() -> None:
    parsed = _ADAPTER.validate_python({"search_type": "organizations", "party_id": "org-1"})

    assert parsed.party_id == "org-1"
    assert parsed.search_type == "organizations"
    assert parsed.search is None


def test_defaults_search_type_to_organizations() -> None:
    parsed = _ADAPTER.validate_python({"party_id": "org-1"})

    assert parsed.search_type == "organizations"


def test_rejects_both_selectors() -> None:
    with pytest.raises(ValidationError, match="Exactly one"):
        _ADAPTER.validate_python({"party_id": "org-1", "search": "Acme"})
