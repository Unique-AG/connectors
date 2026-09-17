"""Find the current person↔organization employment row."""

from urllib.parse import quote

from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient, Included
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    EntityRelationshipAttributes,
    EntityRelationshipRef,
    RelationshipTypeAttributes,
)

_Relationship = BackstopApiResource[EntityRelationshipAttributes]
_TypeResource = BackstopApiResource[RelationshipTypeAttributes]


async def open_employment_id(
    *,
    client: BackstopClient,
    employment_index_factory: EmploymentIndexFactory,
    person_id: str,
    person_search_type: str,
    organization_id: str,
) -> str:
    """Return the one current employment id linking this person to this organization."""
    page = await client.paginate(
        f"/{person_search_type}/{quote(person_id, safe='')}/entityRelationships",
        schema=_Relationship,
        params={"include": EntityRelationshipRef.TYPE.value},
        max_records=None,
        page_size=100,
    )
    types = Included(page.included).by_type(
        EntityRelationshipRef.TYPES_RESOURCE.value, schema=_TypeResource
    )
    open_ids = [
        resource.id
        for resource in page.items
        if _is_open_employment(
            resource,
            organization_id=organization_id,
            relationship_types=types,
            employment_index_factory=employment_index_factory,
        )
    ]
    if not open_ids:
        raise ToolError(
            "No current employment relationship links person "
            + f"{person_id} to organization {organization_id}."
        )
    if len(open_ids) > 1:
        raise ToolError(
            "Multiple current employment relationships link person "
            + f"{person_id} to organization {organization_id}: "
            + ", ".join(open_ids)
            + ". Say which one to end or update."
        )
    return open_ids[0]


def _is_open_employment(
    resource: _Relationship,
    *,
    organization_id: str,
    relationship_types: list[_TypeResource],
    employment_index_factory: EmploymentIndexFactory,
) -> bool:
    destination = resource.attributes.destination_entity
    if destination is None or destination.resource_id != organization_id:
        return False
    index = employment_index_factory.index(
        relationships=[resource],
        relationship_types=relationship_types,
    )
    return any(link.status == "current" for link in index.links())
