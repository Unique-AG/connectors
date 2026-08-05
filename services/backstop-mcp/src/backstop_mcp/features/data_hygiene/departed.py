"""Departed-contact detection from side-loaded `entityRelationships`.

The scan and the type classification it rests on, pure and fully parameterised. Tools do not call
any of it directly — they go through `service.DepartedContactDetector.verify`, which owns the
employment vocabulary. List/org-contact tools should use that verdict to exclude departed people
from "who do we contact at X" answers unless the user asked for historical contacts; a by-id
person fetch returns the person with the flag set rather than hiding the record.
"""

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
    DepartureRules,
    DepartureSignal,
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


def detect_departed_employment(
    *,
    relationships: list[dict[str, object]],
    relationship_types: list[dict[str, object]],
    rules: DepartureRules,
    today: date,
) -> DepartedEmployment | None:
    """The person's departed employment, or None while employment at that organization is current.

    Decided per organization rather than per relationship. A tenant keeps `is employee of` and
    `is a former employee of` as separate records against the *same* organization, and the order
    of `included` is arbitrary, so a first-match scan would answer by array position: one live
    relationship to an organization outranks any number of ended ones, whichever came back first.

    Departed when the relationship's type says past employment, or when its `endDate` has passed.

    One departure is reported even when the person has left several organizations, chosen by
    `_strongest_departure` so the answer never depends on the order of `included`.

    Keyword-only throughout: `relationships` and `relationship_types` are both
    `list[dict[str, object]]` and would transpose without a type error, and a swap fails
    silently — nothing parses, so every person reads as current.
    """
    type_names = _relationship_type_names(resources=relationship_types)
    departures: dict[str, DepartedEmployment] = {}
    current: set[str] = set()

    for raw in relationships:
        parsed = _parse_relationship(raw=raw)
        if parsed is None:
            continue
        attrs, type_id = parsed
        employer = _employer_side(attrs=attrs)
        if employer is None:
            continue

        type_name = type_names.get(type_id) if type_id is not None else None
        status = classify_employment(type_id=type_id, type_name=type_name, rules=rules)
        if status is EmploymentStatus.IRRELEVANT:
            # Neither vouches for the person nor speaks against them.
            continue

        # Parsed whichever way the type classified, so a former-employment record that also
        # carries a date still reports it rather than dropping it.
        ended = _parse_date(raw=attrs.end_date)
        if status is EmploymentStatus.FORMER or (ended is not None and ended < today):
            signal = (
                DepartureSignal.FORMER_TYPE
                if status is EmploymentStatus.FORMER
                else DepartureSignal.END_DATE
            )
            departures.setdefault(
                employer.organization_id,
                DepartedEmployment(
                    signal=signal,
                    organization_id=employer.organization_id,
                    organization_type=employer.organization_type,
                    end_date=ended.isoformat() if ended is not None else None,
                    relationship_type_id=type_id,
                    relationship_type_name=type_name,
                ),
            )
            continue

        current.add(employer.organization_id)

    return _strongest_departure(departures=departures, current=current)


def classify_employment(
    *,
    type_id: str | None,
    type_name: str | None,
    rules: DepartureRules,
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
        # `DepartureRules` for what that costs.
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


def _strongest_departure(
    *, departures: dict[str, DepartedEmployment], current: set[str]
) -> DepartedEmployment | None:
    """The one departure to report, out of every organization the person has left.

    The response carries a single signal, so a person with two ended employments needs a rule
    that does not read off array position. Stronger evidence first — the CRM naming someone a past
    employee outranks an end date that merely elapsed — then the lowest organization id, which is
    arbitrary but fixed for a given record.
    """
    unresolved = [departure for key, departure in departures.items() if key not in current]
    if not unresolved:
        return None
    return min(
        unresolved,
        key=lambda departure: (
            departure.signal is not DepartureSignal.FORMER_TYPE,
            departure.organization_id,
        ),
    )


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


def _parse_relationship(
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


def _parse_date(*, raw: str | None) -> date | None:
    """The calendar day an `endDate` names, however the instance spelled it.

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
