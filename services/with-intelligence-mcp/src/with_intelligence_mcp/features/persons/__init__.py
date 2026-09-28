"""People at an investor: the roster, and the role each holds there."""

from with_intelligence_mcp.features.persons.api_responses import (
    PersonExtendedAttributes,
    PersonListItemAttributes,
    PersonRoleAttributes,
    RoleOrganisationAttributes,
)
from with_intelligence_mcp.features.persons.dependencies import (
    get_people_for_investor_query_factory,
)
from with_intelligence_mcp.features.persons.fetch_people_for_organisation import (
    PERSONS_PATH,
    fetch_people_for_organisation,
)
from with_intelligence_mcp.features.persons.fetch_person import fetch_person
from with_intelligence_mcp.features.persons.queries import GetPeopleForInvestorQuery
from with_intelligence_mcp.features.persons.responses import (
    PeopleForInvestorResponse,
    PersonResponse,
)

__all__ = [
    "PERSONS_PATH",
    "GetPeopleForInvestorQuery",
    "PeopleForInvestorResponse",
    "PersonExtendedAttributes",
    "PersonListItemAttributes",
    "PersonResponse",
    "PersonRoleAttributes",
    "RoleOrganisationAttributes",
    "fetch_people_for_organisation",
    "fetch_person",
    "get_people_for_investor_query_factory",
]
