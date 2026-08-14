"""Custom-field tool entity types and re-exports of the party-search vocabulary."""

from enum import StrEnum
from typing import Final

from backstop_mcp.features.entity_types import KNOWN_ENTITY_TYPES, EntityType, normalize_entity_type


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

_BEAN_TO_CUSTOM_FIELD_ENTITY_TYPE: Final[dict[str, CustomFieldEntityType]] = {
    bean: entity_type for entity_type, bean in CUSTOM_FIELD_BEANS.items()
}


def custom_field_entity_type_from_bean(bean: str) -> CustomFieldEntityType | None:
    """Map a Backstop Bean `entityType` to a tool name, or None if unknown."""
    return _BEAN_TO_CUSTOM_FIELD_ENTITY_TYPE.get(bean)


__all__ = [
    "CUSTOM_FIELD_BEANS",
    "CustomFieldEntityType",
    "EntityType",
    "KNOWN_ENTITY_TYPES",
    "custom_field_entity_type_from_bean",
    "normalize_entity_type",
]
