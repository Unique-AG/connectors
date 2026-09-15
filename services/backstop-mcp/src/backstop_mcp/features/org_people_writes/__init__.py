"""Write-back for people and organizations: create/PATCH the party, locations, and employment."""

from backstop_mcp.features.org_people_writes.commands import (
    CreateEmploymentCommand,
    CreateOrganizationCommand,
    CreatePersonCommand,
    EndEmploymentCommand,
    ModifyContactLocationCommand,
    UpdateOrganizationCommand,
    UpdatePersonCommand,
)
from backstop_mcp.features.org_people_writes.contact_location_input import ContactLocationInput
from backstop_mcp.features.org_people_writes.create_employment_input import (
    CREATE_EMPLOYMENT_INPUT_DESCRIPTION,
    CreateEmploymentInput,
)
from backstop_mcp.features.org_people_writes.create_organization_input import (
    CREATE_ORGANIZATION_INPUT_DESCRIPTION,
    CreateOrganizationInput,
)
from backstop_mcp.features.org_people_writes.create_person_input import (
    CREATE_PERSON_INPUT_DESCRIPTION,
    CreatePersonInput,
)
from backstop_mcp.features.org_people_writes.dependencies import (
    get_create_employment_command_factory,
    get_create_organization_command_factory,
    get_create_person_command_factory,
    get_end_employment_command_factory,
    get_entity_relationship_types_service_factory,
    get_modify_contact_location_command_factory,
    get_update_organization_command_factory,
    get_update_person_command_factory,
)
from backstop_mcp.features.org_people_writes.end_employment_input import (
    END_EMPLOYMENT_INPUT_DESCRIPTION,
    EndEmploymentInput,
)
from backstop_mcp.features.org_people_writes.entity_relationship_types_service import (
    EntityRelationshipTypesService,
)
from backstop_mcp.features.org_people_writes.responses import (
    CreatedEmploymentResponse,
    CreatedOrganizationResponse,
    CreatedPersonResponse,
    CreateEmploymentResponse,
    EndedEmploymentResponse,
    EndEmploymentResponse,
    EntityRelationshipTypeResponse,
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
    "CREATE_EMPLOYMENT_INPUT_DESCRIPTION",
    "CREATE_ORGANIZATION_INPUT_DESCRIPTION",
    "CREATE_PERSON_INPUT_DESCRIPTION",
    "END_EMPLOYMENT_INPUT_DESCRIPTION",
    "UPDATE_ORGANIZATION_INPUT_DESCRIPTION",
    "UPDATE_PERSON_INPUT_DESCRIPTION",
    "ContactLocationInput",
    "CreateEmploymentCommand",
    "CreateEmploymentInput",
    "CreateEmploymentResponse",
    "CreateOrganizationCommand",
    "CreateOrganizationInput",
    "CreatePersonCommand",
    "CreatePersonInput",
    "CreatedEmploymentResponse",
    "CreatedOrganizationResponse",
    "CreatedPersonResponse",
    "EndEmploymentCommand",
    "EndEmploymentInput",
    "EndEmploymentResponse",
    "EndedEmploymentResponse",
    "EntityRelationshipTypeResponse",
    "EntityRelationshipTypesService",
    "ModifyContactLocationCommand",
    "UpdateOrganizationCommand",
    "UpdateOrganizationInput",
    "UpdateOrganizationResponse",
    "UpdatePersonCommand",
    "UpdatePersonInput",
    "UpdatePersonResponse",
    "UpdatedOrganizationResponse",
    "UpdatedPersonResponse",
    "get_create_employment_command_factory",
    "get_create_organization_command_factory",
    "get_create_person_command_factory",
    "get_end_employment_command_factory",
    "get_entity_relationship_types_service_factory",
    "get_modify_contact_location_command_factory",
    "get_update_organization_command_factory",
    "get_update_person_command_factory",
]
