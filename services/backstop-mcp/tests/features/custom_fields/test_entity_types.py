import pytest

from backstop_mcp.features.custom_fields.entity_types import (
    CUSTOM_FIELD_BEANS,
    CustomFieldEntityType,
    custom_field_entity_type_from_bean,
)
from backstop_mcp.features.entity_types import EntityType


class TestCustomFieldEntityType:
    def test_enum_has_exactly_the_six_tool_names(self) -> None:
        assert [member.value for member in CustomFieldEntityType] == [
            "organizations",
            "people",
            "accounts",
            "opportunities",
            "products",
            "party",
        ]

    def test_each_tool_name_maps_to_its_bean(self) -> None:
        assert CUSTOM_FIELD_BEANS == {
            CustomFieldEntityType.ORGANIZATIONS: "OrganizationBean",
            CustomFieldEntityType.PEOPLE: "PersonBean",
            CustomFieldEntityType.ACCOUNTS: "AccountBean",
            CustomFieldEntityType.OPPORTUNITIES: "OpportunityBean",
            CustomFieldEntityType.PRODUCTS: "ProductBean",
            CustomFieldEntityType.PARTY: "PartyBean",
        }

    def test_reverse_lookup_returns_enum_for_known_beans(self) -> None:
        assert (
            custom_field_entity_type_from_bean("OrganizationBean")
            is CustomFieldEntityType.ORGANIZATIONS
        )
        assert custom_field_entity_type_from_bean("PersonBean") is CustomFieldEntityType.PEOPLE
        assert custom_field_entity_type_from_bean("AccountBean") is CustomFieldEntityType.ACCOUNTS
        assert (
            custom_field_entity_type_from_bean("OpportunityBean")
            is CustomFieldEntityType.OPPORTUNITIES
        )
        assert custom_field_entity_type_from_bean("ProductBean") is CustomFieldEntityType.PRODUCTS
        assert custom_field_entity_type_from_bean("PartyBean") is CustomFieldEntityType.PARTY

    def test_reverse_lookup_returns_none_for_unknown_beans(self) -> None:
        assert custom_field_entity_type_from_bean("ContactBean") is None
        assert custom_field_entity_type_from_bean("EmployeeBean") is None
        assert custom_field_entity_type_from_bean("UnknownBean") is None
        assert custom_field_entity_type_from_bean("organizationbean") is None

    def test_contacts_and_employees_are_not_members(self) -> None:
        with pytest.raises(ValueError):
            CustomFieldEntityType("contacts")
        with pytest.raises(ValueError):
            CustomFieldEntityType("employees")

    def test_party_search_entity_type_keeps_contacts_and_employees(self) -> None:
        assert EntityType.CONTACTS == "contacts"
        assert EntityType.EMPLOYEES == "employees"
        values = {member.value for member in EntityType}
        assert "products" not in values
        assert "party" not in values
