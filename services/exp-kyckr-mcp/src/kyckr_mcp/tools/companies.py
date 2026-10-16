from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_openapi.upstream import OperationClient

from kyckr_mcp.deps import get_api, get_settings
from kyckr_mcp.failures import answers_failures
from kyckr_mcp.hints import FREE_READ, PAID_READ, tool_options
from kyckr_mcp.models import operations
from kyckr_mcp.models.replies import (
    CompanyDocumentsReply,
    EnhancedProfileReply,
    LiteProfileReply,
    SearchCompaniesReply,
    answer,
)
from kyckr_mcp.params import CompanyNumber, ContinuationKey, IsoCode, KyckrId, Name
from kyckr_mcp.settings import Settings


@tool(
    **tool_options(
        "Search Companies",
        FREE_READ,
        "building",
        "Always the first step when the user names a company. Use the result's `id` as the "
        "`kyckr_id` for any downstream tool. For status decisions, confirm with a "
        "jurisdiction-specific re-search (`iso_code` set) before treating a global-search hit as "
        "current - global search runs over Kyckr's stored snapshot.",
    )
)
@answers_failures
async def search_companies(
    name: Name = None,
    company_number: CompanyNumber = None,
    iso_code: IsoCode = None,
    api: OperationClient = Depends(get_api),
) -> SearchCompaniesReply:
    """Search the Kyckr company registry by name or registration number. Either `name` or
    `company_number` must be provided. Pass `iso_code` (ISO 3166 alpha-2, e.g. 'GB', 'AU') to
    search a specific jurisdiction directly. Without `iso_code`, Kyckr performs a global search
    over stored data; once you locate the right jurisdiction, repeat the search with that
    `iso_code` to confirm the entity is currently active. The returned `id` is the Kyckr id
    required by every other tool, passed as `kyckr_id`, and is the starting point for
    `list_company_documents`. Free to call.
    """
    if not name and not company_number:
        raise ToolError("Provide either `name` or `company_number`.")
    response = await api.call(
        operations.GET_COMPANIES, name=name, companyNumber=company_number, isoCode=iso_code
    )
    return answer(SearchCompaniesReply, response)


@tool(
    **tool_options(
        "Get Lite Company Profile",
        PAID_READ,
        "building",
        "Use after `search_companies` when the user needs verified company identification (name, "
        "number, address, dates, legal form, status). Spends credits - confirm intent if there's "
        "any ambiguity, and prefer caching the result over re-fetching. If the user asks about "
        "directors / shareholders / UBOs, use `get_enhanced_profile` instead.",
    )
)
@answers_failures
async def get_lite_profile(
    kyckr_id: KyckrId,
    api: OperationClient = Depends(get_api),
    settings: Settings = Depends(get_settings),
) -> LiteProfileReply:
    """Fetch a paid Lite company profile using a confirmed `kyckr_id`. Returns basic verified
    registry details: company name, registration number, registered address, registration and
    foundation dates, legal form, legal status, activities, and registration authority.
    Consumes credits. Does not return directors, shareholders, or beneficial owners; use
    `get_enhanced_profile` for those. For orderable filings, see `list_company_documents`.
    """
    response = await api.call(
        operations.GET_COMPANIES_KYCKR_ID,
        kyckrId=kyckr_id,
        customerReference=settings.kyckr_default_customer_reference,
    )
    return answer(LiteProfileReply, response)


@tool(
    **tool_options(
        "Get Enhanced Company Profile",
        PAID_READ,
        "building",
        "Use when the user needs ownership data: directors / representatives, ultimate "
        "beneficial owners, share capital, contact details, or the registry activity "
        "declaration. Otherwise `get_lite_profile` covers identification at a lower credit "
        "cost. Spends credits - confirm the user wants this depth before calling. A "
        "`statusCode: 405` means the enhanced profile is not available synchronously for that "
        "jurisdiction; surface that limitation to the user rather than substituting another "
        "tool.",
    )
)
@answers_failures
async def get_enhanced_profile(
    kyckr_id: KyckrId,
    api: OperationClient = Depends(get_api),
    settings: Settings = Depends(get_settings),
) -> EnhancedProfileReply:
    """Fetch a paid Enhanced company profile using a confirmed `kyckr_id`. Returns everything in
    `get_lite_profile` plus representatives, ultimate beneficial owners, share capital, contact
    details, and activity declarations. Use only when ownership or representative data is
    needed; `get_lite_profile` is cheaper for basic identification. A `statusCode: 405`
    response means the enhanced profile is not available for that jurisdiction; tell the user
    and do not substitute `create_document_order`, which orders registry filings, not profile
    data. When `data.status` is `Pending` the profile is not ready yet: poll `get_order` with
    `data.orderId` until it resolves.
    """
    response = await api.call(
        operations.GET_COMPANIES_KYCKR_ID_ENHANCED,
        kyckrId=kyckr_id,
        customerReference=settings.kyckr_default_customer_reference,
    )
    return answer(EnhancedProfileReply, response)


@tool(
    **tool_options(
        "List Company Documents",
        FREE_READ,
        "file-text",
        "Use to find filings the user can pay to retrieve as official artifacts (annual "
        "accounts, articles, mortgages, etc.). Free to call; always run this before "
        "`create_document_order` so you can show the user the document `name` and `cost.value` "
        "and obtain explicit confirmation.",
    )
)
@answers_failures
async def list_company_documents(
    kyckr_id: KyckrId,
    continuation_key: ContinuationKey = None,
    api: OperationClient = Depends(get_api),
    settings: Settings = Depends(get_settings),
) -> CompanyDocumentsReply:
    """List official registry documents available to order for a company. The listing is free;
    only `create_document_order` consumes credits. Each entry includes a product `id` (use as
    `product_id` when ordering), `name`, `category`, `documentDate`, expected
    `deliveryTimeMinutes`, and the credit `cost` of ordering. Paginate with `continuation_key`
    when the response includes one.
    """
    response = await api.call(
        operations.GET_COMPANIES_KYCKR_ID_DOCUMENTS,
        kyckrId=kyckr_id,
        continuationKey=continuation_key,
        customerReference=settings.kyckr_default_customer_reference,
    )
    return answer(CompanyDocumentsReply, response)
