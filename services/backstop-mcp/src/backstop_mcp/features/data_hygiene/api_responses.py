from enum import StrEnum
from typing import Annotated, ClassVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from backstop_mcp.dates import LenientDate

__all__ = [
    "CleanStr",
    "EntityRefAttributes",
    "EntityRelationshipAttributes",
    "EntityRelationshipInclude",
    "EntityRelationshipRef",
    "ORG_SIDE_TYPES",
    "PERSON_SIDE_TYPES",
    "ProvenanceAttributes",
    "RelationshipTypeAttributes",
]


def _clean_or_none(value: object) -> object:
    """Backstop sends `""` and `"  "` where it means "unset"; both are absence, not a value."""
    return (value.strip() or None) if isinstance(value, str) else value


# The one place the "stripped, non-empty, else absent" rule is written for this feature. Fields
# carry it so readers get a value that is already clean, instead of every call site re-checking.
#
# Annotated on the *union*, not on the `str` arm: a `BeforeValidator` inside
# `Annotated[str, ...] | None` still has its result checked against `str`, so returning None for
# a blank fails validation rather than selecting the None arm.
CleanStr = Annotated[str | None, BeforeValidator(_clean_or_none)]

# Which resource types can hold an employment relationship, as the canonical plurals that
# `entity_types.normalize_entity_type` maps to — `employment.py` compares through it. Backstop
# emits the API path segment (`people`, `organizations`) and an admin cannot rename those, so
# this is product schema rather than tenant vocabulary and has no business being configurable:
# a deployment cannot know the strings, and a typo would silently disable detection.
PERSON_SIDE_TYPES: frozenset[str] = frozenset({"people", "contacts", "employees"})
ORG_SIDE_TYPES: frozenset[str] = frozenset({"organizations"})


class EntityRelationshipInclude(StrEnum):
    """Backstop `?include=` values for side-loading employment relationships.

    Nested hop is required: including `entityRelationships` alone leaves each
    relationship's `entityRelationshipType` linkage empty.
    """

    ENTITY_RELATIONSHIPS = "entityRelationships"
    ENTITY_RELATIONSHIP_TYPE = "entityRelationships.entityRelationshipType"

    @classmethod
    def for_employment(cls) -> str:
        return f"{cls.ENTITY_RELATIONSHIPS},{cls.ENTITY_RELATIONSHIP_TYPE}"


class EntityRelationshipRef(StrEnum):
    """JSON:API names used when reading entity-relationship side-loads."""

    RELATIONSHIPS = "entityRelationships"
    TYPE = "entityRelationshipType"
    RELATIONSHIPS_RESOURCE = "entity-relationships"
    TYPES_RESOURCE = "entity-relationship-types"


class EntityRefAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    resource_id: CleanStr = Field(default=None, alias="resourceId")
    resource_type: str | None = Field(default=None, alias="resourceType")


class EntityRelationshipAttributes(BaseModel):
    """Sparse attributes used to decide whether a person→org employment has ended."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    end_date: LenientDate = Field(default=None, alias="endDate")
    start_date: LenientDate = Field(default=None, alias="startDate")
    created_timestamp: LenientDate = Field(default=None, alias="createdTimestamp")
    source_entity: EntityRefAttributes | None = Field(default=None, alias="sourceEntity")
    destination_entity: EntityRefAttributes | None = Field(default=None, alias="destinationEntity")


class RelationshipTypeAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: CleanStr = None


class ProvenanceAttributes(BaseModel):
    """Shared `modifiedTimestamp` / `modifiedBy` attributes for as-of provenance."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    modified_timestamp: CleanStr = Field(
        default=None,
        alias="modifiedTimestamp",
        description="When this record was last saved in Backstop.",
    )
    modified_by: object | None = Field(
        default=None,
        alias="modifiedBy",
        description="Who last saved this record. Shape varies by instance.",
    )
