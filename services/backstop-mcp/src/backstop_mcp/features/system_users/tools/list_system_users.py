from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.includes import InternalOwnerResponse
from backstop_mcp.features.system_users import (
    ListSystemUsersResponse,
    SystemUserDto,
    SystemUsersService,
    get_system_users_service,
)
from backstop_mcp.models import published_output_schema


def _to_owner(user: SystemUserDto) -> InternalOwnerResponse:
    return InternalOwnerResponse.model_validate(
        {
            "id": user.id,
            "name": user.name,
            "userName": user.user_name,
            "email": user.email,
            "phoneNumber": user.phone,
            "disabled": user.disabled,
        }
    )


def _user_matches(user: SystemUserDto, search: str) -> bool:
    search = search.casefold().strip()
    values_to_check = (user.name, user.user_name, user.email)
    return any(
        value is not None and search in value.casefold().strip() for value in values_to_check
    )


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(ListSystemUsersResponse),
)
async def list_system_users(
    search: Annotated[
        str | None,
        Field(
            description=(
                "Optional case-insensitive substring of the display name, login, or email."
            ),
        ),
    ] = None,
    refresh: Annotated[
        bool,
        Field(
            description=(
                "Refetch the catalog. Does nothing unless the catalog cache is enabled; "
                "it is off by default. Pass true only when the user reports a missing colleague "
                "and the cache is on."
            )
        ),
    ] = False,
    system_users: SystemUsersService = Depends(get_system_users_service),
) -> ListSystemUsersResponse:
    """List our colleagues' Backstop logins.

    Use when you need the `user_name` login that search_opportunities filters on, or to see
    whether a colleague is `disabled`, or the login for an opportunity `owner_login` or a
    task assignee. These are our staff, not investors. Pass `search` to keep colleagues
    whose name, login, or email contains that substring. `refresh` does nothing unless the
    catalog cache is enabled (off by default).

    Call like: {"search": "doe"}
    """
    catalog, cache = await system_users.get(refresh=refresh)
    selected = tuple(catalog.values())
    if search is not None:
        needle = search.casefold()
        selected = tuple(user for user in selected if _user_matches(user, needle))
    return ListSystemUsersResponse(
        cache=cache,
        users=[_to_owner(user) for user in selected],
    )
