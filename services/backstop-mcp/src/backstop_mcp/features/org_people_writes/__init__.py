"""Write-back for people and organizations: create/PATCH the party, locations, and employment."""

from backstop_mcp.features.org_people_writes.commands import (
    CreateOrganizationCommand,
    CreatePersonCommand,
    EndEmploymentCommand,
    ModifyContactLocationCommand,
    UpdateOrganizationCommand,
    UpdatePersonCommand,
)
from backstop_mcp.features.org_people_writes.contact_location_input import ContactLocationInput
from backstop_mcp.features.org_people_writes.create_organization_input import (
    CREATE_ORGANIZATION_INPUT_DESCRIPTION,
    CreateOrganizationInput,
)
from backstop_mcp.features.org_people_writes.create_person_input import (
    CREATE_PERSON_INPUT_DESCRIPTION,
    CreatePersonInput,
)
from backstop_mcp.features.org_people_writes.dependencies import (
    get_create_organization_command_factory,
    get_create_person_command_factory,
    get_end_employment_command_factory,
    get_modify_contact_location_command_factory,
    get_update_organization_command_factory,
    get_update_person_command_factory,
)
from backstop_mcp.features.org_people_writes.end_employment_input import (
    END_EMPLOYMENT_INPUT_DESCRIPTION,
    EndEmploymentInput,
)
from backstop_mcp.features.org_people_writes.responses import (
    CreatedOrganizationResponse,
    CreatedPersonResponse,
    EndedEmploymentResponse,
    EndEmploymentResponse,
    UpdatedOrganizationResponse,
    UpdatedPersonResponse,
    UpdateOrganizationResponse,
    UpdatePersonResponse,
)
from backstop_mcp.features.org_people_writes.update_organization_input import (
    UPDATE_ORGANIZATION_INPUT_DESCRIPTION,
    UpdateOrganizationInput,
)
from backstop_mcp.features.org_people_writes.update_person_input import (
    UPDATE_PERSON_INPUT_DESCRIPTION,
    UpdatePersonInput,
)

__all__ = [
    "CREATE_ORGANIZATION_INPUT_DESCRIPTION",
    "CREATE_PERSON_INPUT_DESCRIPTION",
    "END_EMPLOYMENT_INPUT_DESCRIPTION",
    "UPDATE_ORGANIZATION_INPUT_DESCRIPTION",
    "UPDATE_PERSON_INPUT_DESCRIPTION",
    "ContactLocationInput",
    "CreateOrganizationCommand",
    "CreateOrganizationInput",
    "CreatePersonCommand",
    "CreatePersonInput",
    "CreatedOrganizationResponse",
    "CreatedPersonResponse",
    "EndEmploymentCommand",
    "EndEmploymentInput",
    "EndEmploymentResponse",
    "EndedEmploymentResponse",
    "ModifyContactLocationCommand",
    "UpdateOrganizationCommand",
    "UpdateOrganizationInput",
    "UpdateOrganizationResponse",
    "UpdatePersonCommand",
    "UpdatePersonInput",
    "UpdatePersonResponse",
    "UpdatedOrganizationResponse",
    "UpdatedPersonResponse",
    "get_create_organization_command_factory",
    "get_create_person_command_factory",
    "get_end_employment_command_factory",
    "get_modify_contact_location_command_factory",
    "get_update_organization_command_factory",
    "get_update_person_command_factory",
]
