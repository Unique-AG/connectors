"""Custom-field tool entity types and Bean lookup."""

from enum import StrEnum
from typing import Final


class CustomFieldEntityType(StrEnum):
    """Closed set of custom-field tool names; not the party-search `EntityType`."""

    ORGANIZATIONS = "organizations"
    PEOPLE = "people"
    ACCOUNTS = "accounts"
    OPPORTUNITIES = "opportunities"
    PRODUCTS = "products"
    PARTY = "party"


CUSTOM_FIELD_BEANS: Final[dict[CustomFieldEntityType, str]] = {
    CustomFieldEntityType.ORGANIZATIONS: "OrganizationBean",
    CustomFieldEntityType.PEOPLE: "PersonBean",
    CustomFieldEntityType.ACCOUNTS: "AccountBean",
    CustomFieldEntityType.OPPORTUNITIES: "OpportunityBean",
    CustomFieldEntityType.PRODUCTS: "ProductBean",
    CustomFieldEntityType.PARTY: "PartyBean",
}

_TOOL_NAME_TO_ENTITY_TYPE: Final[dict[str, CustomFieldEntityType]] = {
    member.value.casefold(): member for member in CustomFieldEntityType
}

_BEAN_TO_CUSTOM_FIELD_ENTITY_TYPE: Final[dict[str, CustomFieldEntityType]] = {
    bean.casefold(): entity_type for entity_type, bean in CUSTOM_FIELD_BEANS.items()
}


def custom_field_entity_type_from_bean(bean: str) -> CustomFieldEntityType | None:
    """Map a Backstop Bean `entityType` to a tool name, or None if unknown."""
    return _BEAN_TO_CUSTOM_FIELD_ENTITY_TYPE.get(bean.casefold())


def custom_field_entity_type(value: str) -> CustomFieldEntityType | None:
    """Map a tool name or Bean to a custom-field entity type, or None if unknown."""
    folded = value.casefold()
    return _TOOL_NAME_TO_ENTITY_TYPE.get(folded) or _BEAN_TO_CUSTOM_FIELD_ENTITY_TYPE.get(folded)


__all__ = [
    "CUSTOM_FIELD_BEANS",
    "CustomFieldEntityType",
    "custom_field_entity_type",
    "custom_field_entity_type_from_bean",
]
