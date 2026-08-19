from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TypedDict

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.data_hygiene.api_responses import (
    EntityRelationshipAttributes,
    RelationshipTypeAttributes,
)

__all__ = [
    "DepartedEmploymentDto",
    "DepartureSignal",
    "EmploymentEdgeDto",
    "EmploymentRecordDto",
    "EmploymentRulesDto",
    "EmploymentStatus",
    "EntityRelationshipsDto",
    "TypeVocabularyDto",
]


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
class DepartedEmploymentDto:
    """A hard signal that the person is no longer employed at an organization.

    The organization is always identified: a relationship whose organization side carries no
    `resourceId` is skipped rather than reported, because a departure nobody can attribute to a
    company is not a usable answer — see `employment._employer_side`.
    """

    signal: DepartureSignal
    organization_id: str
    organization_type: str
    end_date: date | None = None
    relationship_type_id: str | None = None
    relationship_type_name: str | None = None


@dataclass(frozen=True)
class TypeVocabularyDto:
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
class EmploymentEdgeDto:
    """One person→org relationship, normalised out of the raw Backstop payload.

    `status` comes from `classify_employment` (`CURRENT` / `FORMER`; `IRRELEVANT` edges never
    reach this shape at all). `effective_date` is whichever date on the relationship is
    comparable across edges — a `None` here means the edge has no usable date and must sort
    last rather than being mistaken for the oldest or newest edge. `departure` is set only when
    status is `FORMER`.
    """

    person_id: str
    person_type: str
    organization_id: str
    organization_type: str
    relationship_type_id: str | None
    relationship_type_name: str | None
    status: EmploymentStatus
    effective_date: date | None
    departure: DepartedEmploymentDto | None


@dataclass(frozen=True)
class EmploymentRecordDto:
    """The resolved answer for one person/organization pair, after edges are reduced to one.

    Always carries both sides of the pair. `status` is only `CURRENT` or `FORMER` — unknown
    pairs are absent from the index entirely rather than stored as `IRRELEVANT`. `departure` is
    set only when status is `FORMER`.
    """

    person_id: str
    person_type: str
    organization_id: str
    organization_type: str
    status: EmploymentStatus
    relationship_type_id: str | None
    relationship_type_name: str | None
    effective_date: date | None
    departure: DepartedEmploymentDto | None


@dataclass(frozen=True)
class EmploymentRulesDto:
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

    employment: TypeVocabularyDto
    former: TypeVocabularyDto


class EntityRelationshipsDto(TypedDict):
    relationships: list[BackstopApiResource[EntityRelationshipAttributes]]
    relationship_types: list[BackstopApiResource[RelationshipTypeAttributes]]
