"""Side-loaded `entityRelationships` fixtures, shared by the feature tests and `get_person`'s.

The type ids and names are the ones a real instance uses: `is employee of` and `is a former
employee of` against the same organization, plus `has portal access to` as a person→org link that
is not employment at all.
"""

EMPLOYEE_TYPE = "456439"
FORMER_TYPE = "459795"
PORTAL_TYPE = "633147"

TYPE_NAMES = {
    EMPLOYEE_TYPE: "is employee of",
    FORMER_TYPE: "is a former employee of",
    PORTAL_TYPE: "has portal access to",
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
    source_type: str | None = "people",
    source_id: str | None = "p1",
    dest_type: str | None = "organizations",
    dest_id: str | None = "o1",
    type_id: str | None = EMPLOYEE_TYPE,
) -> dict[str, object]:
    """One `entityRelationships` resource linking a person side to an org side.

    A `None` id or type leaves that key off the side entirely, which is how Backstop returns a
    side it did not resolve.
    """
    attributes: dict[str, object] = {
        "sourceEntity": _side(resource_id=source_id, resource_type=source_type),
        "destinationEntity": _side(resource_id=dest_id, resource_type=dest_type),
    }
    if end_date is not None:
        attributes["endDate"] = end_date
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
