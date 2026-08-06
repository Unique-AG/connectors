"""Employment detection from side-loaded `entityRelationships`.

The scan and the type classification it rests on, pure and fully parameterised. Tools do not call
any of it directly — they go through `service.EmploymentIndexFactory`, which owns the employment
vocabulary. List/org-contact tools should use that verdict to exclude departed people
from "who do we contact at X" answers unless the user asked for historical contacts; a by-id
person fetch returns the person with the flag set rather than hiding the record.

`_employment_edges` is the shared building block for reading employment off *either* side of a
relationship — a person's own GET or an organization's own GET — with `person_side` as the only
difference between the two directions. It is one step below `EmploymentIndex` (a later addition):
it normalises the raw payload into edges, but does not yet reduce several edges for the same pair
down to one winner.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import TypeGuard

from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.coerce import as_clean_str
from backstop_mcp.features.data_hygiene.types import (
    ENTITY_RELATIONSHIP_TYPE_RELATIONSHIP,
    ORG_SIDE_TYPES,
    PERSON_SIDE_TYPES,
    DepartedEmployment,
    DepartureSignal,
    EmploymentEdge,
    EmploymentRecord,
    EmploymentRules,
    EmploymentStatus,
    EntityRefAttributes,
    EntityRelationshipAttributes,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.entity_types import normalize_entity_type


@dataclass(frozen=True)
class _Employer:
    """The organization side of one person→org relationship, once it is known to have both."""

    organization_id: str
    organization_type: str


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

    def __init__(self, edges: Sequence[EmploymentEdge]) -> None:
        winners: dict[tuple[str, str], EmploymentEdge] = {}
        for edge in edges:
            key = (edge.person_id, edge.organization_id)
            current = winners.get(key)
            if current is None or _outranks(edge, current):
                winners[key] = edge
        self._records: dict[tuple[str, str], EmploymentRecord] = {
            key: _to_record(edge) for key, edge in winners.items()
        }

    def status(self, *, person_id: str, organization_id: str) -> EmploymentStatus:
        """The winning edge's status, or `IRRELEVANT` — "no employment evidence" — for an unknown
        pair. Never a false `CURRENT`: a pair this index has never seen is not a live employee.
        """
        record = self._records.get((person_id, organization_id))
        if record is None:
            return EmploymentStatus.IRRELEVANT
        return record.status

    def departure(self, *, person_id: str, organization_id: str) -> DepartedEmployment | None:
        """The winning edge's departure evidence, when the pair's resolved status is `FORMER`."""
        record = self._records.get((person_id, organization_id))
        if record is None or record.status is not EmploymentStatus.FORMER:
            return None
        return record.departure

    def pairs(self, *, status: EmploymentStatus) -> tuple[EmploymentRecord, ...]:
        """Every resolved pair whose winning status matches `status`, for list annotation."""
        return tuple(record for record in self._records.values() if record.status is status)


def _outranks(edge: EmploymentEdge, current: EmploymentEdge) -> bool:
    """Whether `edge` beats `current` as the winner for their shared pair.

    Compared as `(has a date, date, is departed)` tuples so a dated edge always beats an undated
    one, the later date wins between two dated edges, and a same-day tie breaks toward `FORMER`.
    """
    return _rank(edge) > _rank(current)


def _rank(edge: EmploymentEdge) -> tuple[bool, date, bool]:
    return (
        edge.effective_date is not None,
        edge.effective_date if edge.effective_date is not None else date.min,
        edge.status is EmploymentStatus.FORMER,
    )


def _to_record(edge: EmploymentEdge) -> EmploymentRecord:
    departure = edge.evidence if edge.status is EmploymentStatus.FORMER else None
    return EmploymentRecord(status=edge.status, departure=departure)


def classify_employment(
    *,
    type_id: str | None,
    type_name: str | None,
    rules: EmploymentRules,
) -> EmploymentStatus:
    """What one relationship's type says about employment at the organization.

    * `FORMER` — the type is one the deployment calls past employment. Tested *first*, because a
      tenant's past-employment name tends to contain its current-employment name (`is a former
      employee of` contains `employee`); an employment-first test would call it `CURRENT` and
      report someone who has left as a live contact.
    * `IRRELEVANT` — employment vocabulary is configured, the type has a name to judge, and it
      matches nothing.
    * `CURRENT` — otherwise.
    """
    if rules.former.matches(type_id=type_id, type_name=type_name):
        return EmploymentStatus.FORMER
    if rules.employment.is_empty:
        # No employment vocabulary configured, so every person→org type is admitted. See
        # `EmploymentRules` for what that costs.
        return EmploymentStatus.CURRENT
    if rules.employment.matches(type_id=type_id, type_name=type_name):
        return EmploymentStatus.CURRENT
    if type_name is None:
        # Nothing to judge: either the record carries no type, or its type resource did not
        # side-load. Both leave the person→org gate below as the only evidence, so read it as
        # current — that keeps `endDate` in play and never invents a departure out of a record we
        # could not classify.
        return EmploymentStatus.CURRENT
    return EmploymentStatus.IRRELEVANT


def _relationship_type_names(*, resources: list[dict[str, object]]) -> dict[str, str]:
    """`id → name` for the side-loaded relationship types. Unnamed and malformed ones are dropped.

    A type we cannot read leaves its relationships with no name to match, which
    `classify_employment` treats as no type signal — never as a positive finding.
    """
    names: dict[str, str] = {}
    for raw in resources:
        try:
            resource = BackstopApiResource[RelationshipTypeAttributes].model_validate(raw)
        except ValidationError:
            continue
        name = as_clean_str(resource.attributes.name)
        if name is not None:
            names[resource.id] = name
    return names


def _safe_parse_relationship(
    *, raw: dict[str, object]
) -> tuple[EntityRelationshipAttributes, str | None] | None:
    try:
        resource = BackstopApiResource[EntityRelationshipAttributes].model_validate(raw)
    except ValidationError:
        return None
    type_ids = resource.related_ids(ENTITY_RELATIONSHIP_TYPE_RELATIONSHIP)
    return resource.attributes, type_ids[0] if type_ids else None


def _side_type(*, side: EntityRefAttributes) -> str | None:
    if side.resource_type is None:
        return None
    return normalize_entity_type(side.resource_type)


def _employer_side(*, attrs: EntityRelationshipAttributes) -> _Employer | None:
    """The organization a relationship could attribute employment to, when there is one.

    Needs a person on one side and an organization on the other, in either direction, and needs
    that organization to be identifiable. An organization side with no `resourceId` is skipped
    rather than keyed on a placeholder: every such side would share one bucket, so a live
    relationship to one unnamed company would clear a departure from a different one.
    """
    sides = [
        (side, _side_type(side=side))
        for side in (attrs.source_entity, attrs.destination_entity)
        if side is not None
    ]
    if len(sides) != 2:
        return None
    (first, first_type), (second, second_type) = sides
    if first_type in PERSON_SIDE_TYPES and _is_organization(second_type):
        organization, organization_type = second, second_type
    elif second_type in PERSON_SIDE_TYPES and _is_organization(first_type):
        organization, organization_type = first, first_type
    else:
        return None

    organization_id = as_clean_str(organization.resource_id)
    if organization_id is None:
        return None
    return _Employer(organization_id=organization_id, organization_type=organization_type)


def _is_organization(side_type: str | None) -> TypeGuard[str]:
    """`TypeGuard` rather than a bare `in`, so the matched side's type reads as the `str` it is."""
    return side_type in ORG_SIDE_TYPES


def _safe_parse_date(*, raw: str | None) -> date | None:
    """The calendar day an `endDate` (or `startDate` / `createdTimestamp`) names, however the
    instance spelled it.

    The leading ten characters cover both a plain `YYYY-MM-DD` and the full timestamp Backstop
    actually writes into this date field; the second attempt is for compact ISO forms
    (`20221231T101530`), whose date part is not ten characters long.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _employment_edges(
    *,
    relationships: list[dict[str, object]],
    relationship_types: list[dict[str, object]],
    rules: EmploymentRules,
    today: date,
    person_side: bool,
) -> list[EmploymentEdge]:
    """Every person↔organization relationship, normalised into one `EmploymentEdge` each.

    `person_side` names which literal JSON side is "self" when the payload came from the
    person's own GET (`sourceEntity`) versus the organization's own GET (`destinationEntity`).
    Structural matching itself stays direction-agnostic: `_employer_side`'s type-based check
    already tells the organization side from the person side regardless of which literal key
    each landed on, so both `person_id` and `organization_id` are pulled from whichever side
    matched — `person_side` only needs to be threaded through for callers building an index (a
    later addition) that must record which id belongs to which entity type.

    `IRRELEVANT` edges are dropped — they neither vouch for the person nor speak against them, so
    they carry no employment signal for `EmploymentIndex` to fold. An edge with no usable date at
    all (`effective_date=None`) is kept: it sorts last downstream rather than being dropped
    outright, so it still wins when it is the only edge for its pair.
    """
    type_names = _relationship_type_names(resources=relationship_types)
    edges: list[EmploymentEdge] = []

    for raw in relationships:
        parsed = _safe_parse_relationship(raw=raw)
        if parsed is None:
            continue
        attrs, type_id = parsed
        employer = _employer_side(attrs=attrs)
        if employer is None:
            continue
        person_id = _person_id(attrs=attrs)
        if person_id is None:
            continue

        type_name = type_names.get(type_id) if type_id is not None else None
        status = classify_employment(type_id=type_id, type_name=type_name, rules=rules)
        if status is EmploymentStatus.IRRELEVANT:
            continue

        created = _safe_parse_date(raw=attrs.created_timestamp)
        started = _safe_parse_date(raw=attrs.start_date)
        ended = _safe_parse_date(raw=attrs.end_date)

        if status is EmploymentStatus.FORMER:
            effective_date = ended if ended is not None else created
            evidence = DepartedEmployment(
                signal=DepartureSignal.FORMER_TYPE,
                organization_id=employer.organization_id,
                organization_type=employer.organization_type,
                end_date=ended.isoformat() if ended is not None else None,
                relationship_type_id=type_id,
                relationship_type_name=type_name,
            )
        elif ended is not None and ended < today:
            # A `CURRENT`-type relationship whose own end date has already passed: rewritten to a
            # departure dated at that `endDate`.
            status = EmploymentStatus.FORMER
            effective_date = ended
            evidence = DepartedEmployment(
                signal=DepartureSignal.END_DATE,
                organization_id=employer.organization_id,
                organization_type=employer.organization_type,
                end_date=ended.isoformat(),
                relationship_type_id=type_id,
                relationship_type_name=type_name,
            )
        else:
            effective_date = started if started is not None else created
            # `evidence` is only ever read by the resolver (a later addition) for a `FORMER`
            # edge; a plain `CURRENT` edge has no departure to describe, so `signal`/`end_date`
            # here are a placeholder to satisfy the required field, not a claim about anything.
            evidence = DepartedEmployment(
                signal=DepartureSignal.END_DATE,
                organization_id=employer.organization_id,
                organization_type=employer.organization_type,
                end_date=None,
                relationship_type_id=type_id,
                relationship_type_name=type_name,
            )

        edges.append(
            EmploymentEdge(
                person_id=person_id,
                organization_id=employer.organization_id,
                organization_type=employer.organization_type,
                status=status,
                effective_date=effective_date,
                evidence=evidence,
            )
        )

    return edges


def _person_id(*, attrs: EntityRelationshipAttributes) -> str | None:
    """The person side's id, whichever literal JSON key (`sourceEntity`/`destinationEntity`) it
    landed on.

    Mirrors `_employer_side`'s type-based matching rather than trusting a `person_side` flag for
    structural matching, so the two functions never disagree about which side is which. A person
    side with no `resourceId` is skipped for the same reason an unidentified organization is: an
    id-less side would collide every such relationship into one bucket.
    """
    sides = [
        (side, _side_type(side=side))
        for side in (attrs.source_entity, attrs.destination_entity)
        if side is not None
    ]
    if len(sides) != 2:
        return None
    (first, first_type), (second, second_type) = sides
    if first_type in PERSON_SIDE_TYPES and _is_organization(second_type):
        person = first
    elif second_type in PERSON_SIDE_TYPES and _is_organization(first_type):
        person = second
    else:
        return None
    return as_clean_str(person.resource_id)


def build_person_employment_index(
    *,
    relationships: list[dict[str, object]],
    relationship_types: list[dict[str, object]],
    rules: EmploymentRules,
    today: date,
) -> EmploymentIndex:
    """The `EmploymentIndex` for `entityRelationships` side-loaded off a person's own GET.

    A person's own GET puts the person at `sourceEntity`, so `person_side=True`. The rest is
    exactly `build_organization_employment_index`'s work: `person_side` carries no behavior yet
    (see `_employment_edges`), so the only real difference between the two builders is which
    literal value they pass.
    """
    edges = _employment_edges(
        relationships=relationships,
        relationship_types=relationship_types,
        rules=rules,
        today=today,
        person_side=True,
    )
    return EmploymentIndex(edges)


def build_organization_employment_index(
    *,
    relationships: list[dict[str, object]],
    relationship_types: list[dict[str, object]],
    rules: EmploymentRules,
    today: date,
) -> EmploymentIndex:
    """The `EmploymentIndex` for `entityRelationships` side-loaded off an organization's own GET.

    An organization's own GET puts the person at `destinationEntity`, so `person_side=False` —
    the mirror image of `build_person_employment_index`.
    """
    edges = _employment_edges(
        relationships=relationships,
        relationship_types=relationship_types,
        rules=rules,
        today=today,
        person_side=False,
    )
    return EmploymentIndex(edges)
