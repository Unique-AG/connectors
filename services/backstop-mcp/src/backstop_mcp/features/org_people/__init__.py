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

from backstop_mcp.features.org_people.api_responses import (
    EmployeeAttributes,
    OrganizationAttributes,
    PersonAttributes,
)
from backstop_mcp.features.org_people.dependencies import (
    get_organization_query_factory,
    get_people_for_organization_query_factory,
    get_person_query_factory,
)
from backstop_mcp.features.org_people.queries import (
    MAX_ORG_PEOPLE,
    GetOrganizationQuery,
    GetPeopleForOrganizationQuery,
    GetPersonQuery,
)
from backstop_mcp.features.org_people.responses import (
    OrganizationRecordResponse,
    OrganizationResolvedResponse,
    OrgPeopleResolvedResponse,
    PartyOrganizationResponse,
    PartyOrgPeopleResponse,
    PartyPersonResponse,
    PersonAtOrganizationResponse,
    PersonRecordResponse,
    PersonResolvedResponse,
)

__all__ = [
    "MAX_ORG_PEOPLE",
    "EmployeeAttributes",
    "GetOrganizationQuery",
    "GetPeopleForOrganizationQuery",
    "GetPersonQuery",
    "OrgPeopleResolvedResponse",
    "OrganizationAttributes",
    "OrganizationRecordResponse",
    "OrganizationResolvedResponse",
    "PartyOrgPeopleResponse",
    "PartyOrganizationResponse",
    "PartyPersonResponse",
    "PersonAtOrganizationResponse",
    "PersonAttributes",
    "PersonRecordResponse",
    "PersonResolvedResponse",
    "get_organization_query_factory",
    "get_people_for_organization_query_factory",
    "get_person_query_factory",
]
