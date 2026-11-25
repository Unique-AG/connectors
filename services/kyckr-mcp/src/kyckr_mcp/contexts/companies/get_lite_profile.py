from pydantic import Field

from kyckr_mcp.contexts.companies.models import Activity
from kyckr_mcp.contexts.companies.models import Address
from kyckr_mcp.contexts.companies.models import Normalized
from kyckr_mcp.contexts.replies import KyckrModel
from kyckr_mcp.contexts.replies import Reply
from kyckr_mcp.upstream import GET_COMPANIES_KYCKR_ID
from kyckr_mcp.upstream import GetCompaniesKyckrIdPath
from kyckr_mcp.upstream import GetCompaniesKyckrIdQuery
from kyckr_mcp.upstream import GetCompaniesKyckrIdRequest
from kyckr_mcp.upstream import Upstream


async def get_lite_profile(
    *, upstream: Upstream, kyckr_id: str, customer_reference: str | None
) -> LiteProfileReply:
    request = GetCompaniesKyckrIdRequest(
        path=GetCompaniesKyckrIdPath(kyckr_id=kyckr_id),
        query=GetCompaniesKyckrIdQuery(customer_reference=customer_reference),
    )
    return LiteProfileReply.model_validate(await upstream.call(GET_COMPANIES_KYCKR_ID, request))


class LiteProfile(KyckrModel):
    """A company's verified registry details."""

    company_name: str | None = Field(None, description="The name at the registry.")
    english_name: str | None = Field(None, description="The English name, if there is one.")
    company_number: str | None = Field(None, description="The registration number.")
    registration_authority: str | None = Field(
        None, description="The registry the company is registered at."
    )
    address: Address | None = Field(None, description="The registered address.")
    registration_date: Normalized | None = Field(None, description="When it was registered.")
    foundation_date: Normalized | None = Field(None, description="When it was founded.")
    legal_form: Normalized | None = Field(None, description="Its legal form.")
    legal_status: Normalized | None = Field(
        None, description="Its legal status, such as whether it is active."
    )
    activity: list[Activity] | None = Field(None, description="Its industry classifications.")


class LiteProfileReply(Reply):
    """A Lite company profile."""

    data: LiteProfile | None = Field(None, description="The profile.")
