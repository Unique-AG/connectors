"""People at an investor: the roster, and the role each holds there."""

from with_intelligence_mcp.features.persons.api_responses import (
    PersonExtendedAttributes,
    PersonListItemAttributes,
    PersonRoleAttributes,
    RoleOrganisationAttributes,
)
from with_intelligence_mcp.features.persons.fetch_people_for_organisation import (
    PERSONS_PATH,
    fetch_people_for_organisation,
)
from with_intelligence_mcp.features.persons.fetch_person import fetch_person
from with_intelligence_mcp.features.persons.project_person import project_person
from with_intelligence_mcp.features.persons.responses import (
    PeopleForInvestorResponse,
    PersonResponse,
)

__all__ = [
    "PERSONS_PATH",
    "PeopleForInvestorResponse",
    "PersonExtendedAttributes",
    "PersonListItemAttributes",
    "PersonResponse",
    "PersonRoleAttributes",
    "RoleOrganisationAttributes",
    "fetch_people_for_organisation",
    "fetch_person",
    "project_person",
]
