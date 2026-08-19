"""Employment detection from side-loaded `entityRelationships`.

The scan and the type classification it rests on, pure and fully parameterised. Tools do not call
any of it directly — they go through `service.EmploymentIndexFactory`, which owns the employment
vocabulary. List/org-contact tools should use that verdict to exclude departed people
from "who do we contact at X" answers unless the user asked for historical contacts; a by-id
person fetch returns the person with employment links rather than hiding the record.
"""

from collections.abc import Sequence
from datetime import date
from typing import ClassVar, TypeGuard

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
from backstop_mcp.features.data_hygiene.internal_dto import (
    DepartedEmploymentDto,
    DepartureSignal,
    EmploymentEdgeDto,
    EmploymentRecordDto,
    EmploymentRulesDto,
    EmploymentStatus,
)
from backstop_mcp.features.data_hygiene.responses import EmploymentLinkResponse
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


class EmploymentIndex:
    """One winner per `(person_id, organization_id)` pair, folded out of `_employment_edges`.

    A tenant's `entityRelationships` can carry several records for the same pair — a live `is
    employee of` alongside an ended `is a former employee of`, or successive relationships across
    a re-hire — and the caller needs one verdict, not a list to re-resolve on every read. The fold
    happens once, in `__init__`; every query method after that is a plain dict lookup.

    Winner per pair: the edge with the greatest `effective_date`. A tie breaks toward **departed**
    — a same-day former record is the more recent human action, and under-reporting a departure is
    the costlier error for a "who do we contact" answer. An edge with no usable date at all still
    counts, but sorts behind every dated edge for its pair, so it only wins when it is the sole
    edge for that pair.
    """

    def __init__(self, edges: Sequence[EmploymentEdgeDto]) -> None:
        winners: dict[tuple[str, str], EmploymentEdgeDto] = {}
        for edge in edges:
            key = (edge.person_id, edge.organization_id)
            current = winners.get(key)
            if current is None or _outranks(edge, current):
                winners[key] = edge
        self._records: dict[tuple[str, str], EmploymentRecordDto] = {
            key: _to_record(edge) for key, edge in winners.items()
        }

    def get(self, *, person_id: str, organization_id: str) -> EmploymentRecordDto | None:
        """The winning record for this pair, or `None` when the index has no employment evidence."""
        return self._records.get((person_id, organization_id))

    def status(self, *, person_id: str, organization_id: str) -> EmploymentStatus | None:
        """The winning edge's status, or `None` — "no employment evidence" — for an unknown pair.

        Never a false `CURRENT`: a pair this index has never seen is not a live employee.
        """
        record = self.get(person_id=person_id, organization_id=organization_id)
        return None if record is None else record.status

    def departure(self, *, person_id: str, organization_id: str) -> DepartedEmploymentDto | None:
        """The winning edge's departure evidence, when the pair's resolved status is `FORMER`."""
        record = self.get(person_id=person_id, organization_id=organization_id)
        if record is None or record.status is not EmploymentStatus.FORMER:
            return None
        return record.departure

    def current(self) -> tuple[EmploymentRecordDto, ...]:
        """Every resolved pair whose winning status is `CURRENT`."""
        return self.pairs(status=EmploymentStatus.CURRENT)

    def former(self) -> tuple[EmploymentRecordDto, ...]:
        """Every resolved pair whose winning status is `FORMER`."""
        return self.pairs(status=EmploymentStatus.FORMER)

    def pairs(self, *, status: EmploymentStatus) -> tuple[EmploymentRecordDto, ...]:
        """Every resolved pair whose winning status matches `status`, for list annotation."""
        return tuple(record for record in self._records.values() if record.status is status)

    def links(self) -> list[EmploymentLinkResponse]:
        """Current then former employment links — the shape tools should relay."""
        return [_to_link(record) for record in (*self.current(), *self.former())]


def _to_link(record: EmploymentRecordDto) -> EmploymentLinkResponse:
    if record.status is EmploymentStatus.CURRENT:
        status = "current"
    elif record.status is EmploymentStatus.FORMER:
        status = "former"
    else:
        raise AssertionError(
            f"EmploymentIndex only stores CURRENT/FORMER winners, got {record.status!r}"
        )
    departure = record.departure
    return EmploymentLinkResponse(
        status=status,
        person_id=record.person_id,
        person_type=record.person_type,
        organization_id=record.organization_id,
        organization_type=record.organization_type,
        signal=None if departure is None else departure.signal,
        end_date=None if departure is None else departure.end_date,
        relationship_type_id=record.relationship_type_id,
        relationship_type_name=record.relationship_type_name,
    )


def _outranks(edge: EmploymentEdgeDto, current: EmploymentEdgeDto) -> bool:
    """Whether `edge` beats `current` as the winner for their shared pair.

    Compared as `(has a date, date, is departed)` tuples so a dated edge always beats an undated
    one, the later date wins between two dated edges, and a same-day tie breaks toward `FORMER`.
    """
    return _rank(edge) > _rank(current)


def _rank(edge: EmploymentEdgeDto) -> tuple[bool, date, bool]:
    return (
        edge.effective_date is not None,
        edge.effective_date if edge.effective_date is not None else date.min,
        edge.status is EmploymentStatus.FORMER,
    )


def _to_record(edge: EmploymentEdgeDto) -> EmploymentRecordDto:
    return EmploymentRecordDto(
        person_id=edge.person_id,
        person_type=edge.person_type,
        organization_id=edge.organization_id,
        organization_type=edge.organization_type,
        status=edge.status,
        relationship_type_id=edge.relationship_type_id,
        relationship_type_name=edge.relationship_type_name,
        effective_date=edge.effective_date,
        departure=edge.departure,
    )


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


def _relationship_type_names(*, resources: Sequence[RelationshipTypeResource]) -> dict[str, str]:
    """`id → name` for the side-loaded relationship types. Unnamed ones are dropped."""
    names: dict[str, str] = {}
    for resource in resources:
        if resource.attributes.name is not None:
            names[resource.id] = resource.attributes.name
    return names


def _side_type(*, side: EntityRefAttributes) -> str | None:
    if side.resource_type is None:
        return None
    return normalize_entity_type(side.resource_type)


def _sides(
    *, attrs: EntityRelationshipAttributes
) -> tuple[tuple[EntityRefAttributes, str | None], tuple[EntityRefAttributes, str | None]] | None:
    sides = [
        (side, _side_type(side=side))
        for side in (attrs.source_entity, attrs.destination_entity)
        if side is not None
    ]
    if len(sides) != 2:
        return None
    return (sides[0], sides[1])


def _employer_side(*, attrs: EntityRelationshipAttributes) -> _Employer | None:
    """The organization a relationship could attribute employment to, when there is one.

    Needs a person on one side and an organization on the other, in either direction, and needs
    that organization to be identifiable. An organization side with no `resourceId` is skipped
    rather than keyed on a placeholder: every such side would share one bucket, so a live
    relationship to one unnamed company would clear a departure from a different one.
    """
    sides = _sides(attrs=attrs)
    if sides is None:
        return None
    (first, first_type), (second, second_type) = sides
    if _is_person(first_type) and _is_organization(second_type):
        organization, organization_type = second, second_type
    elif _is_person(second_type) and _is_organization(first_type):
        organization, organization_type = first, first_type
    else:
        return None

    if organization.resource_id is None:
        return None
    return _Employer(organization_id=organization.resource_id, organization_type=organization_type)


def _person_side(*, attrs: EntityRelationshipAttributes) -> _Person | None:
    """The person side's id and type, whichever literal JSON key it landed on.

    Mirrors `_employer_side`'s type-based matching. A person side with no `resourceId` is skipped
    for the same reason an unidentified organization is: an id-less side would collide every such
    relationship into one bucket.
    """
    sides = _sides(attrs=attrs)
    if sides is None:
        return None
    (first, first_type), (second, second_type) = sides
    if _is_person(first_type) and _is_organization(second_type):
        person, person_type = first, first_type
    elif _is_person(second_type) and _is_organization(first_type):
        person, person_type = second, second_type
    else:
        return None
    if person.resource_id is None:
        return None
    return _Person(person_id=person.resource_id, person_type=person_type)


def _is_person(side_type: str | None) -> TypeGuard[str]:
    return side_type in PERSON_SIDE_TYPES


def _is_organization(side_type: str | None) -> TypeGuard[str]:
    """`TypeGuard` rather than a bare `in`, so the matched side's type reads as the `str` it is."""
    return side_type in ORG_SIDE_TYPES


def _employment_edges(
    *,
    relationships: Sequence[RelationshipResource],
    relationship_types: Sequence[RelationshipTypeResource],
    rules: EmploymentRulesDto,
    today: date,
) -> list[EmploymentEdgeDto]:
    """Every person↔organization relationship, normalised into one `EmploymentEdge` each.

    Structural matching is direction-agnostic: `_employer_side`'s type-based check already tells
    the organization side from the person side regardless of which literal key each landed on.

    `IRRELEVANT` edges are dropped — they neither vouch for the person nor speak against them, so
    they carry no employment signal for `EmploymentIndex` to fold. An edge with no usable date at
    all (`effective_date=None`) is kept: it sorts last downstream rather than being dropped
    outright, so it still wins when it is the only edge for its pair.
    """
    type_names = _relationship_type_names(resources=relationship_types)
    edges: list[EmploymentEdgeDto] = []

    for resource in relationships:
        attrs = resource.attributes
        type_ids = resource.related_ids(EntityRelationshipRef.TYPE)
        type_id = type_ids[0] if type_ids else None
        employer = _employer_side(attrs=attrs)
        if employer is None:
            continue
        person = _person_side(attrs=attrs)
        if person is None:
            continue

        type_name = type_names.get(type_id) if type_id is not None else None
        status = classify_employment(type_id=type_id, type_name=type_name, rules=rules)
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
            # A `CURRENT`-type relationship whose own end date has already passed: rewritten to a
            # departure dated at that `endDate`.
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


def build_employment_index(
    *,
    relationships: Sequence[RelationshipResource],
    relationship_types: Sequence[RelationshipTypeResource],
    rules: EmploymentRulesDto,
    today: date,
) -> EmploymentIndex:
    """The `EmploymentIndex` for `entityRelationships` side-loaded off a person or organization."""
    return EmploymentIndex(
        _employment_edges(
            relationships=relationships,
            relationship_types=relationship_types,
            rules=rules,
            today=today,
        )
    )
