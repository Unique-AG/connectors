import unique_sdk
from unique_sdk.api_resources._llm_models import LLMModels
from unique_sdk.api_resources._mcp import McpServersResponse

from space_config_mcp.upstream import Upstream


async def list_language_models(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
) -> LLMModels.LLMModelsResponse:
    """Return all language model IDs available to the company."""
    return await upstream.list_language_models(user_id, company_id)


async def list_spaces(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    name: str | None = None,
    skip: int = 0,
    take: int = 20,
) -> unique_sdk.Space.Spaces:
    return await upstream.get_spaces(user_id, company_id, name=name, skip=skip, take=take)


async def get_space(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    space_id: str,
) -> unique_sdk.Space:
    return await upstream.get_space(user_id, company_id, space_id)


async def list_mcp_servers(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
) -> McpServersResponse:
    """List all MCP servers available to the company with their tools and metadata."""
    return await upstream.list_mcp_servers(user_id, company_id)


async def get_mcp_server_status(
    *,
    upstream: Upstream,
    user_id: str,
    company_id: str,
    space_id: str,
) -> unique_sdk.Space.McpServerStatusResponse:
    return await upstream.get_mcp_server_status(user_id, company_id, space_id)
