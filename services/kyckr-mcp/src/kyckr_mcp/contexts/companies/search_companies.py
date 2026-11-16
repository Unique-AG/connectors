from kyckr_mcp.upstream import GET_COMPANIES
from kyckr_mcp.upstream import GetCompaniesQuery
from kyckr_mcp.upstream import GetCompaniesRequest
from kyckr_mcp.upstream import GetCompaniesResponse
from kyckr_mcp.upstream import Upstream


async def search_companies(
    *,
    upstream: Upstream,
    name: str | None,
    company_number: str | None,
    iso_code: str | None,
) -> GetCompaniesResponse:
    if not name and not company_number:
        raise MissingSearchTermError("Provide either `name` or `company_number`.")
    query = GetCompaniesQuery(name=name, company_number=company_number, iso_code=iso_code)
    return await upstream.call(GET_COMPANIES, GetCompaniesRequest(query=query))


class MissingSearchTermError(ValueError):
    """A company search needs a name or a registration number."""
