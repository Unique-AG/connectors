"""Employment-index assembly: vocabulary, classification, and edge parsing.

The scan and the type classification it rests on, fully parameterised. Tools do not call any of
it directly — they go through `EmploymentIndexFactory`, which owns the employment vocabulary.
List/org-contact tools should use that verdict to exclude departed people from "who do we contact
at X" answers unless the user asked for historical contacts; a by-id person fetch returns the
person with employment links rather than hiding the record.
"""

from collections.abc import Callable, Sequence
from datetime import date
from typing import ClassVar, Self, TypeGuard

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.data_hygiene.api_responses import (
    ORG_SIDE_TYPES,
    PERSON_SIDE_TYPES,
    EntityRefAttributes,
    EntityRelationshipAttributes,
    EntityRelationshipRef,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.data_hygiene.employment_index import EmploymentIndex
from backstop_mcp.features.data_hygiene.internal_dto import (
    DepartedEmploymentDto,
    DepartureSignal,
    EmploymentEdgeDto,
    EmploymentRulesDto,
    EmploymentStatus,
    TypeVocabularyDto,
)
from backstop_mcp.features.entity_types import normalize_entity_type

type RelationshipResource = BackstopApiResource[EntityRelationshipAttributes]
type RelationshipTypeResource = BackstopApiResource[RelationshipTypeAttributes]


class _Employer(BaseModel):
    """The organization side of one person→org relationship, once it is known to have both."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    organization_id: str
    organization_type: str


class _Person(BaseModel):
    """The person side of one person→org relationship, once it is known to have both."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    person_id: str
    person_type: str


class EmploymentIndexFactory:
    """Owns the employment vocabulary and the clock; builds an `EmploymentIndex` per document.

    The employment vocabulary is a constructor dependency and the relationship-type names arrive
    side-loaded on the caller's own GET, so building an index needs no client, no cache and no
    lock: it is synchronous, and every caller gets the same index for the same record.

    Built via `from_vocabulary` in `create_app()` and reached via
    `runtime.get_employment_index_factory()`.
    """

    def __init__(
        self,
        *,
        rules: EmploymentRulesDto,
        clock: Callable[[], date] = date.today,
    ) -> None:
        self._rules: EmploymentRulesDto = rules
        self._clock: Callable[[], date] = clock

    @classmethod
    def from_vocabulary(
        cls,
        *,
        employment_type_ids: Sequence[str],
        employment_type_markers: Sequence[str],
        former_type_ids: Sequence[str],
        former_type_markers: Sequence[str],
    ) -> Self:
        """Build the factory from configured values, translating them into the feature's own
        type."""
        return cls(
            rules=EmploymentRulesDto(
                employment=TypeVocabularyDto(
                    type_ids=frozenset(employment_type_ids),
                    name_markers=frozenset(employment_type_markers),
                ),
                former=TypeVocabularyDto(
                    type_ids=frozenset(former_type_ids),
                    name_markers=frozenset(former_type_markers),
                ),
            ),
        )

    @property
    def rules(self) -> EmploymentRulesDto:
        """The vocabulary this factory was built with. Read-only; set once at composition."""
        return self._rules

    def index(
        self,
        *,
        relationships: list[RelationshipResource],
        relationship_types: list[RelationshipTypeResource],
    ) -> EmploymentIndex:
        """Build an `EmploymentIndex` from `entityRelationships` side-loaded off a person or
        organization GET.

        Both arguments come from that GET's includes — no second fetch of the subject and no
        per-relationship fetch of its type. Keyword-only because the two lists share a resource
        shape and transposing them would silently misclassify every relationship.
        """
        return EmploymentIndex(
            self._employment_edges(
                relationships=relationships,
                relationship_types=relationship_types,
                rules=self._rules,
                today=self._clock(),
            )
        )

    def _employment_edges(
        self,
        *,
        relationships: Sequence[RelationshipResource],
        relationship_types: Sequence[RelationshipTypeResource],
        rules: EmploymentRulesDto,
        today: date,
    ) -> list[EmploymentEdgeDto]:
        """Every person↔organization relationship, normalised into one `EmploymentEdge` each.

        Structural matching is direction-agnostic: `_employer_side`'s type-based check already
        tells the organization side from the person side regardless of which literal key each
        landed on.

        `IRRELEVANT` edges are dropped — they neither vouch for the person nor speak against them,
        so they carry no employment signal for `EmploymentIndex` to fold. An edge with no usable
        date at all (`effective_date=None`) is kept: it sorts last downstream rather than being
        dropped outright, so it still wins when it is the only edge for its pair.
        """
        type_names = self._relationship_type_names(resources=relationship_types)
        edges: list[EmploymentEdgeDto] = []

        for resource in relationships:
            attrs = resource.attributes
            type_ids = resource.related_ids(EntityRelationshipRef.TYPE)
            type_id = type_ids[0] if type_ids else None
            employer = self._employer_side(attrs=attrs)
            if employer is None:
                continue
            person = self._person_side(attrs=attrs)
            if person is None:
                continue

            type_name = type_names.get(type_id) if type_id is not None else None
            status = self.classify_employment(type_id=type_id, type_name=type_name, rules=rules)
            if status is EmploymentStatus.IRRELEVANT:
                continue

            created = attrs.created_timestamp
            started = attrs.start_date
            ended = attrs.end_date

            departure: DepartedEmploymentDto | None = None
            if status is EmploymentStatus.FORMER:
                effective_date = ended if ended is not None else created
                departure = DepartedEmploymentDto(
                    signal=DepartureSignal.FORMER_TYPE,
                    organization_id=employer.organization_id,
                    organization_type=employer.organization_type,
                    end_date=ended,
                    relationship_type_id=type_id,
                    relationship_type_name=type_name,
                )
            elif ended is not None and ended < today:
                # A `CURRENT`-type relationship whose own end date has already passed: rewritten to
                # a departure dated at that `endDate`.
                status = EmploymentStatus.FORMER
                effective_date = ended
                departure = DepartedEmploymentDto(
                    signal=DepartureSignal.END_DATE,
                    organization_id=employer.organization_id,
                    organization_type=employer.organization_type,
                    end_date=ended,
                    relationship_type_id=type_id,
                    relationship_type_name=type_name,
                )
            else:
                effective_date = started if started is not None else created

            edges.append(
                EmploymentEdgeDto(
                    person_id=person.person_id,
                    person_type=person.person_type,
                    organization_id=employer.organization_id,
                    organization_type=employer.organization_type,
                    relationship_type_id=type_id,
                    relationship_type_name=type_name,
                    status=status,
                    effective_date=effective_date,
                    departure=departure,
                )
            )

        return edges

    @staticmethod
    def classify_employment(
        *,
        type_id: str | None,
        type_name: str | None,
        rules: EmploymentRulesDto,
    ) -> EmploymentStatus:
        """What one relationship's type says about employment at the organization.

        * `FORMER` — the type is one the deployment calls past employment. Tested *first*, because a
          tenant's past-employment name tends to contain its current-employment name (`is a former
          employee of` contains `employee`); an employment-first test would call it `CURRENT` and
          report someone who has left as a live contact.
        * `IRRELEVANT` — employment vocabulary is configured, the type has a name to judge, and it
          matches nothing — or the type id is present but its name did not side-load, so we cannot
          treat it as employment evidence (a portal-style edge must not clear a real departure).
        * `CURRENT` — otherwise (including truly untyped relationships, so `endDate` still applies).
        """
        if rules.former.matches(type_id=type_id, type_name=type_name):
            return EmploymentStatus.FORMER
        if rules.employment.is_empty:
            # No employment vocabulary configured, so every person→org type is admitted. See
            # `EmploymentRules` for what that costs.
            return EmploymentStatus.CURRENT
        if rules.employment.matches(type_id=type_id, type_name=type_name):
            return EmploymentStatus.CURRENT
        if type_name is None and type_id is None:
            # Truly untyped: leave the person→org gate as the only evidence and read it as current
            # so `endDate` stays in play.
            return EmploymentStatus.CURRENT
        return EmploymentStatus.IRRELEVANT

    @staticmethod
    def _relationship_type_names(
        *, resources: Sequence[RelationshipTypeResource]
    ) -> dict[str, str]:
        """`id → name` for the side-loaded relationship types. Unnamed ones are dropped."""
        names: dict[str, str] = {}
        for resource in resources:
            if resource.attributes.name is not None:
                names[resource.id] = resource.attributes.name
        return names

    @staticmethod
    def _side_type(*, side: EntityRefAttributes) -> str | None:
        if side.resource_type is None:
            return None
        return normalize_entity_type(side.resource_type)

    def _sides(
        self, *, attrs: EntityRelationshipAttributes
    ) -> (
        tuple[tuple[EntityRefAttributes, str | None], tuple[EntityRefAttributes, str | None]] | None
    ):
        sides = [
            (side, self._side_type(side=side))
            for side in (attrs.source_entity, attrs.destination_entity)
            if side is not None
        ]
        if len(sides) != 2:
            return None
        return (sides[0], sides[1])

    def _employer_side(self, *, attrs: EntityRelationshipAttributes) -> _Employer | None:
        """The organization a relationship could attribute employment to, when there is one.

        Needs a person on one side and an organization on the other, in either direction, and needs
        that organization to be identifiable. An organization side with no `resourceId` is skipped
        rather than keyed on a placeholder: every such side would share one bucket, so a live
        relationship to one unnamed company would clear a departure from a different one.
        """
        sides = self._sides(attrs=attrs)
        if sides is None:
            return None
        (first, first_type), (second, second_type) = sides
        if self._is_person(first_type) and self._is_organization(second_type):
            organization, organization_type = second, second_type
        elif self._is_person(second_type) and self._is_organization(first_type):
            organization, organization_type = first, first_type
        else:
            return None

        if organization.resource_id is None:
            return None
        return _Employer(
            organization_id=organization.resource_id, organization_type=organization_type
        )

    def _person_side(self, *, attrs: EntityRelationshipAttributes) -> _Person | None:
        """The person side's id and type, whichever literal JSON key it landed on.

        Mirrors `_employer_side`'s type-based matching. A person side with no `resourceId` is
        skipped for the same reason an unidentified organization is: an id-less side would collide
        every such relationship into one bucket.
        """
        sides = self._sides(attrs=attrs)
        if sides is None:
            return None
        (first, first_type), (second, second_type) = sides
        if self._is_person(first_type) and self._is_organization(second_type):
            person, person_type = first, first_type
        elif self._is_person(second_type) and self._is_organization(first_type):
            person, person_type = second, second_type
        else:
            return None
        if person.resource_id is None:
            return None
        return _Person(person_id=person.resource_id, person_type=person_type)

    @staticmethod
    def _is_person(side_type: str | None) -> TypeGuard[str]:
        return side_type in PERSON_SIDE_TYPES

    @staticmethod
    def _is_organization(side_type: str | None) -> TypeGuard[str]:
        """`TypeGuard` rather than a bare `in`, so the matched side's type reads as the `str` it
        is."""
        return side_type in ORG_SIDE_TYPES
