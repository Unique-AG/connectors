from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.org_people_writes.commands import (
    ModifyContactLocationCommand,
    UpdateOrganizationCommand,
    UpdatePersonCommand,
)
from backstop_mcp.features.system_users import SystemUsersService, get_system_users_service


@lru_cache(maxsize=1)
def get_modify_contact_location_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> ModifyContactLocationCommand:
    return ModifyContactLocationCommand(client=client)


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
