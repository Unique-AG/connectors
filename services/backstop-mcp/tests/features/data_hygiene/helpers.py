"""Side-loaded `entityRelationships` fixtures, shared by the feature tests and `get_person`'s.

The type ids and names are the ones a real instance uses: `is employee of` and `is a former
employee of` against the same organization, plus `has portal access to` as a person→org link that
is not employment at all.

The mirror types (`is employee of (mirror)` / `is a former employee of (mirror)`) are what an
organization's own GET side-loads instead — same meaning, different ids and names, and pointing
the other direction. `owns account` / `management company of` are org-side types the design doc
cites as `IRRELEVANT`: person↔organization is not the shape at all (an org owning an account or
managing another org), so they must drop out rather than count as employment either way.
"""

EMPLOYEE_TYPE = "456439"
FORMER_TYPE = "459795"
PORTAL_TYPE = "633147"
EMPLOYEE_MIRROR_TYPE = "456441"
FORMER_MIRROR_TYPE = "459797"
OWNS_ACCOUNT_TYPE = "700001"
MANAGEMENT_COMPANY_TYPE = "700002"

TYPE_NAMES = {
    EMPLOYEE_TYPE: "is employee of",
    FORMER_TYPE: "is a former employee of",
    PORTAL_TYPE: "has portal access to",
    EMPLOYEE_MIRROR_TYPE: "is employee of (mirror)",
    FORMER_MIRROR_TYPE: "is a former employee of (mirror)",
    OWNS_ACCOUNT_TYPE: "owns account",
    MANAGEMENT_COMPANY_TYPE: "management company of",
}


def relationship_types(*type_ids: str) -> list[dict[str, object]]:
    """Side-loaded `entity-relationship-types` resources (id → name)."""
    return [
        {
            "type": "entity-relationship-types",
            "id": type_id,
            "attributes": {"name": TYPE_NAMES[type_id]},
        }
        for type_id in type_ids
    ]


def person_org(
    er_id: str,
    *,
    end_date: str | None = None,
    start_date: str | None = None,
    created_timestamp: str | None = None,
    source_type: str | None = "people",
    source_id: str | None = "p1",
    dest_type: str | None = "organizations",
    dest_id: str | None = "o1",
    type_id: str | None = EMPLOYEE_TYPE,
) -> dict[str, object]:
    """One `entityRelationships` resource linking a person side to an org side.

    A `None` id or type leaves that key off the side entirely, which is how Backstop returns a
    side it did not resolve. `source_type`/`dest_type`/`source_id`/`dest_id` already suffice to
    simulate an organization's own GET: pass the organization as `source_*` and the person as
    `dest_*` (or vice versa) — `_employer_side`/`_person_id` match structurally by resource type,
    not by literal JSON key, so no separate builder is needed for that payload shape.
    """
    attributes: dict[str, object] = {
        "sourceEntity": _side(resource_id=source_id, resource_type=source_type),
        "destinationEntity": _side(resource_id=dest_id, resource_type=dest_type),
    }
    if end_date is not None:
        attributes["endDate"] = end_date
    if start_date is not None:
        attributes["startDate"] = start_date
    if created_timestamp is not None:
        attributes["createdTimestamp"] = created_timestamp
    relationships: dict[str, object] = {}
    if type_id is not None:
        relationships["entityRelationshipType"] = {
            "data": {"type": "entity-relationship-types", "id": type_id}
        }
    return {
        "type": "entity-relationships",
        "id": er_id,
        "attributes": attributes,
        "relationships": relationships,
    }


def _side(*, resource_id: str | None, resource_type: str | None) -> dict[str, object]:
    side: dict[str, object] = {}
    if resource_id is not None:
        side["resourceId"] = resource_id
    if resource_type is not None:
        side["resourceType"] = resource_type
    return side
