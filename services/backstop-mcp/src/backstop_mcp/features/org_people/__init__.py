"""People linked to an organization, with employment status from `EmploymentIndex`.

Also fetches a person or organization record by id.

`numberOfEmployees` on the organization record is not a roster. Current staff come from one
paginated walk of `GET /organizations/{id}/employees` with
`include=entityRelationships,entityRelationships.entityRelationshipType` and a sparse
`fields[employees]` fieldset for the contact card. Status is the same `EmploymentIndex`
`get_person` uses, built from those side-loads. `/employees` is current staff only, so the
organization's `entityRelationships` are always walked as well — former people live there,
and `former_omitted` needs that walk. `include_former` only controls whether they are
returned.
"""

from backstop_mcp.features.org_people.fetch_organization import fetch_organization
from backstop_mcp.features.org_people.fetch_people_for_organization import (
    MAX_ORG_PEOPLE,
    fetch_people_for_organization,
)
from backstop_mcp.features.org_people.fetch_person import fetch_person
from backstop_mcp.features.org_people.internal_dto import (
    OrgPeopleListingDto,
    PersonAtOrganizationDto,
)
from backstop_mcp.features.org_people.responses import (
    OrganizationRecordResponse,
    OrgPeopleResolvedResponse,
    PersonAtOrganizationResponse,
    PersonRecordResponse,
)

__all__ = [
    "MAX_ORG_PEOPLE",
    "OrganizationRecordResponse",
    "OrgPeopleListingDto",
    "OrgPeopleResolvedResponse",
    "PersonAtOrganizationDto",
    "PersonAtOrganizationResponse",
    "PersonRecordResponse",
    "fetch_organization",
    "fetch_people_for_organization",
    "fetch_person",
]
