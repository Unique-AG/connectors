from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool

from kyckr_mcp import contexts
from kyckr_mcp.mcp.dependencies import get_upstream
from kyckr_mcp.mcp.hints import FREE_READ
from kyckr_mcp.mcp.hints import tool_options
from kyckr_mcp.mcp.inputs.company import CompanyNumber
from kyckr_mcp.mcp.inputs.company import IsoCode
from kyckr_mcp.mcp.inputs.company import Name
from kyckr_mcp.mcp.responses.failures import answers_failures
from kyckr_mcp.upstream import Upstream


@tool(
    **tool_options(
        "Search Companies",
        FREE_READ,
        icon="building",
        system_prompt=(
            "Always the first step when the user names a company. Use the result's `id` as the "
            "`kyckr_id` for any downstream tool. For status decisions, confirm with a "
            "jurisdiction-specific re-search (`iso_code` set) before treating a global-search hit "
            "as current - global search runs over Kyckr's stored snapshot."
        ),
    )
)
@answers_failures
async def search_companies(
    name: Name = None,
    company_number: CompanyNumber = None,
    iso_code: IsoCode = None,
    *,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.CompanySearchReply:
    """Search the Kyckr company registry by name or registration number. Either `name` or
    `company_number` must be provided. Pass `iso_code` (ISO 3166 alpha-2, e.g. 'GB', 'AU') to
    search a specific jurisdiction directly. Without `iso_code`, Kyckr performs a global search
    over stored data; once you locate the right jurisdiction, repeat the search with that
    `iso_code` to confirm the entity is currently active. The returned `id` is the Kyckr id
    required by every other tool, passed as `kyckr_id`, and is the starting point for
    `list_company_documents`. Free to call.
    """
    try:
        return await contexts.search_companies(
            upstream=upstream, name=name, company_number=company_number, iso_code=iso_code
        )
    except contexts.MissingSearchTermError as error:
        raise ToolError(str(error)) from error
