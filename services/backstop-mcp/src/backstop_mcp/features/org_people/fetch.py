"""Walk an organization's `/employees` with employment includes, annotated via `EmploymentIndex`."""

import logging
from urllib.parse import quote

from pydantic import ValidationError

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopClient,
    included_by_type,
)
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    EntityRelationshipAttributes,
    EntityRelationshipInclude,
    EntityRelationshipRef,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.includes import ContactCardResponse
from backstop_mcp.features.org_people.internal_dto import (
    OrgPeopleListingDto,
    PersonAtOrganizationDto,
)

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
MAX_ORG_PEOPLE = 500
_EMPLOYEE_FIELDS = "name,jobTitle,email,phone,companyName"

RelationshipResource = BackstopApiResource[EntityRelationshipAttributes]
RelationshipTypeResource = BackstopApiResource[RelationshipTypeAttributes]
EmployeeCardResource = BackstopApiResource[ContactCardResponse]


async def fetch_people_for_organization(
    client: BackstopClient,
    factory: EmploymentIndexFactory,
    *,
    organization_id: str,
    include_former: bool,
) -> OrgPeopleListingDto:
    """People the employment index ties to `organization_id`.

    Current staff are one paginated walk of `/organizations/{id}/employees` with
    `include=entityRelationships,entityRelationships.entityRelationshipType` and a sparse
    employee fieldset for the contact card. Status comes from `EmploymentIndex` — not from
    `numberOfEmployees`. `/employees` is current staff only, so the organization's
    `entityRelationships` are always walked as well: former people live there, and without
    that walk `former_omitted` cannot tell an empty roster from a former-only one.
    `include_former` only controls whether those former people are returned.
    """
    org = quote(organization_id, safe="")
    page = await client.paginate(
        f"/organizations/{org}/employees",
        schema=EmployeeCardResource,
        params={
            "include": EntityRelationshipInclude.for_employment(),
            "fields[employees]": _EMPLOYEE_FIELDS,
        },
        max_records=None,
        page_size=_PAGE_SIZE,
    )
    org_page = await client.paginate(
        f"/organizations/{org}/entityRelationships",
        schema=RelationshipResource,
        params={"include": EntityRelationshipRef.TYPE.value},
        max_records=None,
        page_size=_PAGE_SIZE,
    )
    relationships = [
        *_resources(
            page.included,
            resource_type=EntityRelationshipRef.RELATIONSHIPS_RESOURCE,
            schema=EntityRelationshipAttributes,
            kind="entity-relationships",
        ),
        *org_page.items,
    ]
    relationship_types = [
        *_resources(
            page.included,
            resource_type=EntityRelationshipRef.TYPES_RESOURCE,
            schema=RelationshipTypeAttributes,
            kind="entity-relationship-types",
        ),
        *_resources(
            org_page.included,
            resource_type=EntityRelationshipRef.TYPES_RESOURCE,
            schema=RelationshipTypeAttributes,
            kind="entity-relationship-types",
        ),
    ]
    index = factory.index(
        relationships=relationships,
        relationship_types=relationship_types,
    )
    current = index.current()
    former = index.former()
    if not include_former:
        records = current
        former_omitted = sum(1 for record in former if record.organization_id == organization_id)
    else:
        records = (*current, *former)
        former_omitted = 0
    at_org = tuple(record for record in records if record.organization_id == organization_id)
    fanned = at_org[:MAX_ORG_PEOPLE]
    people_omitted = len(at_org) - len(fanned)
    fanned_keys = {(record.person_id, record.organization_id) for record in fanned}
    links = tuple(
        link for link in index.links() if (link.person_id, link.organization_id) in fanned_keys
    )
    cards = {resource.id: resource.attributes for resource in page.items}
    people = tuple(
        PersonAtOrganizationDto(employment=link, card=cards.get(link.person_id)) for link in links
    )
    return OrgPeopleListingDto(
        people=people,
        former_omitted=former_omitted,
        people_omitted=people_omitted,
    )


def _resources[AttrT](
    included: list[dict[str, object]],
    *,
    resource_type: str,
    schema: type[AttrT],
    kind: str,
) -> list[BackstopApiResource[AttrT]]:
    parsed: list[BackstopApiResource[AttrT]] = []
    for raw in included_by_type(included, resource_type):
        try:
            parsed.append(BackstopApiResource[schema].model_validate(raw))
        except ValidationError as exc:
            logger.warning(
                "org_people.side_load.unreadable", extra={"kind": kind, "error": str(exc)}
            )
    return parsed
