"""People linked to an organization, with employment status from `EmploymentIndex`.

`numberOfEmployees` on the organization record is not a roster. Current staff come from one
paginated walk of `GET /organizations/{id}/employees` with
`include=entityRelationships,entityRelationships.entityRelationshipType` and a sparse
`fields[employees]` fieldset for the contact card. Status is the same `EmploymentIndex`
`get_person` uses, built from those side-loads. `/employees` is current staff only — pass
`include_former` to also walk the organization's `entityRelationships` for former people.
"""

from backstop_mcp.features.org_people.fetch import fetch_people_for_organization
from backstop_mcp.features.org_people.responses import (
    OrgPeopleResolvedResponse,
    PersonAtOrganizationResponse,
    org_people_response,
)
from backstop_mcp.features.org_people.types import OrgPeopleListing, PersonAtOrganization

__all__ = [
    "OrgPeopleListing",
    "OrgPeopleResolvedResponse",
    "PersonAtOrganization",
    "PersonAtOrganizationResponse",
    "fetch_people_for_organization",
    "org_people_response",
]
