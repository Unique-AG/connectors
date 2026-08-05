"""Internal types for read-response provenance and departed-contact detection."""

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

# Which resource types can hold an employment relationship, as the canonical plurals that
# `entity_types.normalize_entity_type` maps to — `departed.py` compares through it. Backstop
# emits the API path segment (`people`, `organizations`) and an admin cannot rename those, so
# this is product schema rather than tenant vocabulary and has no business being configurable:
# a deployment cannot know the strings, and a typo would silently disable detection.
PERSON_SIDE_TYPES: frozenset[str] = frozenset({"people", "contacts", "employees"})
ORG_SIDE_TYPES: frozenset[str] = frozenset({"organizations"})

# Including `entityRelationships` alone leaves each relationship's own `entityRelationshipType`
# linkage empty, and the type id lives nowhere else on the record. The nested hop fills both in
# on one GET, which is what lets the detector classify without a second request.
ENTITY_RELATIONSHIPS_INCLUDE = "entityRelationships,entityRelationships.entityRelationshipType"
ENTITY_RELATIONSHIPS_RELATIONSHIP = "entityRelationships"
ENTITY_RELATIONSHIP_TYPE_RELATIONSHIP = "entityRelationshipType"
ENTITY_RELATIONSHIP_TYPES_RESOURCE = "entity-relationship-types"


class EntityRefAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    resource_id: str | None = Field(default=None, alias="resourceId")
    resource_type: str | None = Field(default=None, alias="resourceType")


class EntityRelationshipAttributes(BaseModel):
    """Sparse attributes used to decide whether a person→org employment has ended."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    end_date: str | None = Field(default=None, alias="endDate")
    source_entity: EntityRefAttributes | None = Field(default=None, alias="sourceEntity")
    destination_entity: EntityRefAttributes | None = Field(default=None, alias="destinationEntity")


class RelationshipTypeAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str | None = None


@dataclass(frozen=True)
class AsOf:
    """Plain provenance from a Backstop record. No staleness verdict attached."""

    modified_timestamp: str | None = None
    modified_by: str | None = None


class EmploymentStatus(StrEnum):
    """What a relationship's type says about employment at the organization it links to.

    Three outcomes, and `IRRELEVANT` is not a soft `FORMER`. A type that links a person to an
    organization for some reason other than employment (`has portal access to`) must neither
    raise a departure nor clear one — counting it as employment would let portal access vouch
    for someone who has left. `CURRENT` and `FORMER` are both positive findings.

    `StrEnum` so a member renders as a readable word in a log line or an assertion diff rather
    than as an opaque ordinal.
    """

    CURRENT = "current"
    FORMER = "former"
    IRRELEVANT = "irrelevant"


class DepartureSignal(StrEnum):
    """Which evidence a departure rests on, so the answer can say why rather than just that."""

    FORMER_TYPE = "former_relationship_type"
    END_DATE = "end_date_passed"


@dataclass(frozen=True)
class DepartedEmployment:
    """A hard signal that the person is no longer employed at an organization."""

    signal: DepartureSignal
    organization_id: str | None = None
    organization_type: str | None = None
    end_date: str | None = None
    relationship_type_id: str | None = None
    relationship_type_name: str | None = None


@dataclass(frozen=True)
class TypeVocabulary:
    """Which entity-relationship types a deployment puts in one bucket.

    Two ways in, because a tenant can supply either. `type_ids` are exact but per-instance — an
    admin's numeric ids mean nothing on another deployment. `name_markers` are substrings of the
    type's own name and survive a re-install, at the cost of matching anything that contains
    them. Both fields are required: a match must be a function of what was injected, never of
    which default a call site happened to leave out.
    """

    type_ids: frozenset[str]
    name_markers: frozenset[str]

    @property
    def is_empty(self) -> bool:
        """Whether this bucket can match anything at all."""
        return not self.type_ids and not self.name_markers

    def matches(self, *, type_id: str | None, type_name: str | None) -> bool:
        if type_id is not None and type_id in self.type_ids:
            return True
        if type_name is None:
            return False
        lowered = type_name.casefold()
        return any(marker.casefold() in lowered for marker in self.name_markers)


@dataclass(frozen=True)
class DepartureRules:
    """Everything about reading a tenant's `entityRelationships` that a deployment can set.

    Both halves are tenant vocabulary rather than anything Backstop guarantees. `employment`
    decides which person→org types concern employment at all; `former` decides which of those
    describe employment that has ended.

    `former` is the half that does the work. A tenant models a departure as a *different
    relationship type*, not as an end date — the instance this was built against carries
    `is employee of` and `is a former employee of` side by side against the same organization
    and fills in `endDate` on well under one percent of records. An empty `former` therefore
    leaves `endDate` as the only signal and detects almost nothing.

    An empty `employment` admits every person→org type, which over-reports in the one direction
    that matters: `has portal access to` would count as employment and could clear a departure
    that `is a former employee of` had correctly raised.
    """

    employment: TypeVocabulary
    former: TypeVocabulary
