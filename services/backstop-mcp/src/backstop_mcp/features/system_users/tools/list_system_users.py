from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.includes import InternalOwnerResponse
from backstop_mcp.features.system_users import (
    SystemUserDto,
    SystemUsersService,
    get_system_users_service,
)
from backstop_mcp.models import published_output_schema


class ListSystemUsersResponse(BaseModel):
    """Colleagues from the Backstop system-user catalog."""

    status: Literal["ok"] = Field(default="ok", description="Always 'ok'.")
    cache: Literal["ok", "stale"] = Field(
        description=(
            "'ok' when the catalog was fetched this call or is still fresh; 'stale' when a "
            "previous catalog is served because refresh failed."
        )
    )
    users: list[InternalOwnerResponse] = Field(
        description=(
            "Our colleagues, in catalog order. Echo `user_name` into search_opportunities "
            "`representative` — that filter takes a login, not a display name. `disabled` is "
            "true for a departed colleague; do not treat their empty pipeline as 'no coverage'."
        )
    )


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


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(ListSystemUsersResponse),
)
async def list_system_users(
    refresh: Annotated[
        bool,
        Field(description="Do not pass true unless the user reports a missing colleague."),
    ] = False,
    client: BackstopClient = Depends(get_backstop_client),
    system_users: SystemUsersService = Depends(get_system_users_service),
) -> ListSystemUsersResponse:
    """List our colleagues' Backstop logins.

    Use when you need the `user_name` login that search_opportunities filters on, or to see
    whether a colleague is `disabled`. These are our staff, not investors. Pass refresh=true
    only when the user reports a missing colleague.
    """
    catalog, cache = await system_users.get(client, refresh=refresh)
    return ListSystemUsersResponse(
        cache=cache,
        users=[_to_owner(user) for user in catalog.values()],
    )
