"""People linked to an organization, with employment status from `EmploymentIndex`.

`numberOfEmployees` on the organization record is not a roster. Current staff come from one
paginated walk of `GET /organizations/{id}/employees` with
`include=entityRelationships,entityRelationships.entityRelationshipType` and a sparse
`fields[employees]` fieldset for the contact card. Status is the same `EmploymentIndex`
`get_person` uses, built from those side-loads. `/employees` is current staff only, so the
organization's `entityRelationships` are always walked as well — former people live there,
and `former_omitted` needs that walk. `include_former` only controls whether they are
returned.
"""

from backstop_mcp.features.org_people.fetch_people_for_organization import (
    MAX_ORG_PEOPLE,
    fetch_people_for_organization,
)
from backstop_mcp.features.org_people.internal_dto import (
    OrgPeopleListingDto,
    PersonAtOrganizationDto,
)
from backstop_mcp.features.org_people.responses import (
    OrgPeopleResolvedResponse,
    PersonAtOrganizationResponse,
)

__all__ = [
    "MAX_ORG_PEOPLE",
    "OrgPeopleListingDto",
    "OrgPeopleResolvedResponse",
    "PersonAtOrganizationDto",
    "PersonAtOrganizationResponse",
    "fetch_people_for_organization",
]
