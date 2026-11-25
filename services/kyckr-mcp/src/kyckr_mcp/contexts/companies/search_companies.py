from pydantic import Field

from kyckr_mcp.contexts.replies import KyckrModel
from kyckr_mcp.contexts.replies import Reply
from kyckr_mcp.upstream import GET_COMPANIES
from kyckr_mcp.upstream import GetCompaniesQuery
from kyckr_mcp.upstream import GetCompaniesRequest
from kyckr_mcp.upstream import Upstream


async def search_companies(
    *,
    upstream: Upstream,
    name: str | None,
    company_number: str | None,
    iso_code: str | None,
) -> CompanySearchReply:
    if not name and not company_number:
        raise MissingSearchTermError("Provide either `name` or `company_number`.")
    query = GetCompaniesQuery(name=name, company_number=company_number, iso_code=iso_code)
    response = await upstream.call(GET_COMPANIES, GetCompaniesRequest(query=query))
    return CompanySearchReply.model_validate(response)


class MissingSearchTermError(ValueError):
    """A company search needs a name or a registration number."""


class CompanySearchResult(KyckrModel):
    """A company the search found."""

    id: str | None = Field(None, description="The Kyckr id, passed as `kyckr_id` to other tools.")
    company_name: str | None = Field(None, description="The name at the registry.")
    english_name: str | None = Field(
        None, description="The English name, which some jurisdictions add."
    )
    company_number: str | None = Field(None, description="The registration number.")
    address: str | None = Field(None, description="The registered address.")
    status: str | None = Field(
        None, description="The status at the registry, such as whether the company is active."
    )
    type: str | None = Field(None, description="The company type, such as `LTD`.")
    start_date: str | None = Field(None, description="When the company started.")
    is_previous_name: bool | None = Field(
        None, description="Whether the name matched is one the company no longer uses."
    )


class CompanySearchReply(Reply):
    """The companies a search found."""

    data: list[CompanySearchResult] | None = Field(None, description="The companies found.")
