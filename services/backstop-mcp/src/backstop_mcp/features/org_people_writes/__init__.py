"""Write-back for people and organizations: PATCH the party and edit its locations."""

from backstop_mcp.features.org_people_writes.commands import (
    ModifyContactLocationCommand,
    UpdateOrganizationCommand,
    UpdatePersonCommand,
)
from backstop_mcp.features.org_people_writes.contact_location_input import ContactLocationInput
from backstop_mcp.features.org_people_writes.dependencies import (
    get_modify_contact_location_command_factory,
    get_update_organization_command_factory,
    get_update_person_command_factory,
)
from backstop_mcp.features.org_people_writes.responses import (
    UpdateOrganizationResponse,
    UpdatePersonResponse,
    UpdatedOrganizationResponse,
    UpdatedPersonResponse,
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
    "UPDATE_ORGANIZATION_INPUT_DESCRIPTION",
    "UPDATE_PERSON_INPUT_DESCRIPTION",
    "ContactLocationInput",
    "ModifyContactLocationCommand",
    "UpdateOrganizationCommand",
    "UpdateOrganizationInput",
    "UpdateOrganizationResponse",
    "UpdatePersonCommand",
    "UpdatePersonInput",
    "UpdatePersonResponse",
    "UpdatedOrganizationResponse",
    "UpdatedPersonResponse",
    "get_modify_contact_location_command_factory",
    "get_update_organization_command_factory",
    "get_update_person_command_factory",
]
