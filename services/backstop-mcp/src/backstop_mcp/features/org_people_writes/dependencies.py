from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller, get_backstop_config
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    get_employment_index_factory,
    get_employment_rules,
)
from backstop_mcp.features.org_people_writes.commands import (
    CreateEmploymentCommand,
    CreateOrganizationCommand,
    CreatePersonCommand,
    EndEmploymentCommand,
    ModifyContactLocationCommand,
    UpdateOrganizationCommand,
    UpdatePersonCommand,
)
from backstop_mcp.features.org_people_writes.entity_relationship_types_service import (
    EntityRelationshipTypesService,
)
from backstop_mcp.features.system_users import SystemUsersService, get_system_users_service


@lru_cache(maxsize=1)
def get_modify_contact_location_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> ModifyContactLocationCommand:
    return ModifyContactLocationCommand(client=client)


@lru_cache(maxsize=1)
def get_create_person_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    system_users_service: SystemUsersService = Depends(get_system_users_service),
) -> CreatePersonCommand:
    return CreatePersonCommand(client=client, system_users_service=system_users_service)


@lru_cache(maxsize=1)
def get_create_organization_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    system_users_service: SystemUsersService = Depends(get_system_users_service),
) -> CreateOrganizationCommand:
    return CreateOrganizationCommand(client=client, system_users_service=system_users_service)


@lru_cache(maxsize=1)
def get_update_person_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    system_users_service: SystemUsersService = Depends(get_system_users_service),
    modify_contact_location_command: ModifyContactLocationCommand = Depends(
        get_modify_contact_location_command_factory
    ),
) -> UpdatePersonCommand:
    return UpdatePersonCommand(
        client=client,
        system_users_service=system_users_service,
        modify_contact_location_command=modify_contact_location_command,
    )


@lru_cache(maxsize=1)
def get_update_organization_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    system_users_service: SystemUsersService = Depends(get_system_users_service),
    modify_contact_location_command: ModifyContactLocationCommand = Depends(
        get_modify_contact_location_command_factory
    ),
) -> UpdateOrganizationCommand:
    return UpdateOrganizationCommand(
        client=client,
        system_users_service=system_users_service,
        modify_contact_location_command=modify_contact_location_command,
    )


@lru_cache(maxsize=1)
def get_entity_relationship_types_service_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> EntityRelationshipTypesService:
    # Config / employment vocabulary are read here, not injected: `@lru_cache` cannot hash them.
    config = get_backstop_config()
    return EntityRelationshipTypesService.with_ttl_minutes(
        client=client,
        ttl_minutes=config.entity_relationship_type_ttl_minutes,
        rules=get_employment_rules(),
    )


@lru_cache(maxsize=1)
def get_create_employment_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    entity_relationship_types_service: EntityRelationshipTypesService = Depends(
        get_entity_relationship_types_service_factory
    ),
) -> CreateEmploymentCommand:
    return CreateEmploymentCommand(
        client=client,
        entity_relationship_types_service=entity_relationship_types_service,
    )


@lru_cache(maxsize=1)
def get_end_employment_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    employment_index_factory: EmploymentIndexFactory = Depends(get_employment_index_factory),
) -> EndEmploymentCommand:
    return EndEmploymentCommand(
        client=client,
        employment_index_factory=employment_index_factory,
    )
