from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp.exceptions import ToolError
import unique_sdk

from space_config_mcp.upstream.settings import UpstreamSettings


class UpstreamError(ToolError):
    """The upstream failed. It reaches the MCP client."""


class Upstream:
    """Thin async wrapper around unique_sdk Space and Module API resources."""

    def __init__(self, settings: UpstreamSettings) -> None:
        self._service_user_id: str | None = settings.service_user_id
        self._service_company_id: str | None = settings.service_company_id

    async def get_spaces(
        self,
        user_id: str,
        company_id: str,
        *,
        name: str | None = None,
        skip: int = 0,
        take: int = 20,
    ) -> unique_sdk.Space.Spaces:
        params: unique_sdk.Space.GetSpacesParams = {"skip": skip, "take": take}
        if name is not None:
            params["name"] = name
        return await unique_sdk.Space.get_spaces_async(user_id, company_id, **params)

    async def get_space(
        self,
        user_id: str,
        company_id: str,
        space_id: str,
    ) -> unique_sdk.Space:
        return await unique_sdk.Space.get_space_async(user_id, company_id, space_id)

    async def update_space(
        self,
        user_id: str,
        company_id: str,
        space_id: str,
        *,
        patch: unique_sdk.Space.UpdateParams,
    ) -> unique_sdk.Space:
        return await unique_sdk.Space.update_space_async(user_id, company_id, space_id, **patch)

    async def get_space_access(
        self,
        user_id: str,
        company_id: str,
        space_id: str,
    ) -> unique_sdk.Space.SpaceAccessResponse:
        return await unique_sdk.Space.get_space_access_async(user_id, company_id, space_id)

    async def add_space_access(
        self,
        user_id: str,
        company_id: str,
        space_id: str,
        *,
        access: list[unique_sdk.Space.AccessEntry],
    ) -> unique_sdk.Space.SpaceAccessResponse:
        return await unique_sdk.Space.add_space_access_async(
            user_id, company_id, space_id, access=access
        )

    async def delete_space_access(
        self,
        user_id: str,
        company_id: str,
        space_id: str,
        *,
        access_ids: list[str],
    ) -> unique_sdk.Space.DeleteSpaceAccessResponse:
        return await unique_sdk.Space.delete_space_access_async(
            user_id, company_id, space_id, accessIds=access_ids
        )

    async def list_modules(
        self,
        user_id: str,
        company_id: str,
        space_id: str,
    ) -> list[unique_sdk.Module]:
        return await unique_sdk.Module.list_async(
            user_id=user_id, company_id=company_id, assistantId=space_id
        )

    async def get_module(
        self,
        user_id: str,
        company_id: str,
        module_id: str,
    ) -> unique_sdk.Module:
        return await unique_sdk.Module.retrieve_async(
            user_id=user_id, company_id=company_id, id=module_id
        )

    async def modify_module(
        self,
        user_id: str,
        company_id: str,
        module_id: str,
        *,
        configuration: dict[str, object],
    ) -> unique_sdk.Module:
        return await unique_sdk.Module.modify_async(
            user_id=user_id,
            company_id=company_id,
            id=module_id,
            configuration=configuration,
        )


@asynccontextmanager
async def open_upstream(
    settings: UpstreamSettings,
) -> AsyncGenerator[Upstream]:
    unique_sdk.api_key = settings.unique_api_key.get_secret_value()
    unique_sdk.app_id = settings.unique_app_id
    unique_sdk.api_base = settings.unique_api_base
    yield Upstream(settings)
