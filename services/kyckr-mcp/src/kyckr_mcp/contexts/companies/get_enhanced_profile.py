from pydantic import Field

from kyckr_mcp.contexts.companies.models import Activity
from kyckr_mcp.contexts.companies.models import Address
from kyckr_mcp.contexts.companies.models import Normalized
from kyckr_mcp.contexts.replies import Cost
from kyckr_mcp.contexts.replies import KyckrModel
from kyckr_mcp.contexts.replies import Reply
from kyckr_mcp.upstream import GET_COMPANIES_KYCKR_ID_ENHANCED
from kyckr_mcp.upstream import GetCompaniesKyckrIdEnhancedPath
from kyckr_mcp.upstream import GetCompaniesKyckrIdEnhancedQuery
from kyckr_mcp.upstream import GetCompaniesKyckrIdEnhancedRequest
from kyckr_mcp.upstream import Upstream


async def get_enhanced_profile(
    *, upstream: Upstream, kyckr_id: str, customer_reference: str | None
) -> EnhancedProfileReply:
    request = GetCompaniesKyckrIdEnhancedRequest(
        path=GetCompaniesKyckrIdEnhancedPath(kyckr_id=kyckr_id),
        query=GetCompaniesKyckrIdEnhancedQuery(
            customer_reference=customer_reference, show_directorships=None
        ),
    )
    response = await upstream.call(GET_COMPANIES_KYCKR_ID_ENHANCED, request)
    return EnhancedProfileReply.model_validate(response)


class Party(KyckrModel):
    """A person or a corporation. Each field is there only when the registry has it."""

    type: str | None = Field(None, description="The kind of party, as Kyckr names it.")
    name: str | None = Field(None, description="The full name.")
    role: Normalized | None = Field(None, description="A representative's role.")
    is_active: bool | None = Field(None, description="Whether a representative is in post.")
    nature_of_control: list[str] | None = Field(
        None, description="How a beneficial owner controls the company."
    )
    start_date: Normalized | None = Field(None, description="When the role or control started.")
    end_date: Normalized | None = Field(None, description="When the role or control ended.")
    birthdate: Normalized | None = Field(None, description="A person's date of birth.")
    nationality: str | None = Field(None, description="A person's nationality.")
    registration_number: str | None = Field(
        None, description="A corporation's registration number at its home registry."
    )
    address: Address | None = Field(None, description="The party's address.")
    registered_address: Address | None = Field(
        None, description="A corporation's registered address, which some registries give instead."
    )


class Parties(KyckrModel):
    """People and corporations in one role."""

    individuals: list[Party] | None = Field(None, description="The people.")
    corporations: list[Party] | None = Field(None, description="The corporations.")


class Shareholding(KyckrModel):
    """A holding of one share class."""

    percentage: str | None = Field(
        None, description="The share of the class held. Absent when Kyckr gives a range."
    )
    percentage_range: str | None = Field(None, description="The share held as a range, `0-100%`.")
    count: float | None = Field(None, description="The number of shares held.")
    total_nominal_value: float | None = Field(
        None, description="The nominal value of the shares held."
    )
    shareholders: Parties | None = Field(
        None, description="Who holds it. Several hold it jointly, in a split nobody stated."
    )


class Capital(KyckrModel):
    """A share class."""

    class_description: str | None = Field(None, description="What the class is.")
    currency: str | None = Field(None, description="The currency of its values.")
    quantity: float | None = Field(None, description="The number of shares in the class.")
    unit_nominal_value: float | None = Field(None, description="The nominal value of one share.")
    total_nominal_value: float | None = Field(
        None, description="The nominal value of every share in the class."
    )
    shareholdings: list[Shareholding] | None = Field(None, description="Who holds the class.")


class TotalCapital(KyckrModel):
    """The share capital as the registry reports it: authorized, issued or nominal."""

    total_value: float | None = Field(None, description="The amount of share capital.")
    quantity: float | None = Field(None, description="The number of shares across all classes.")
    currency: str | None = Field(None, description="The currency of `totalValue`.")


class ContactDetails(KyckrModel):
    """How to reach the company."""

    email: str | None = Field(None, description="The email address.")
    tel_number: str | None = Field(None, description="The phone number.")
    fax: str | None = Field(None, description="The fax number.")
    website: str | None = Field(None, description="The website.")


class ActivityDeclaration(KyckrModel):
    """The company's business purpose in the registry's words."""

    declaration: str | None = Field(None, description="The text of the declaration.")
    language: str | None = Field(None, description="The language of the text, such as `fr`.")


class Identifiers(KyckrModel):
    """The company's registration numbers."""

    primary_registration_number: str | None = Field(None, description="The registration number.")


class EnhancedProfile(KyckrModel):
    """A company's registry details with its owners, representatives and capital."""

    company_name: str | None = Field(None, description="The name at the registry.")
    english_name: str | None = Field(None, description="The English name, if there is one.")
    identifiers: Identifiers | None = Field(None, description="Its registration numbers.")
    registration_authority: str | None = Field(
        None, description="The registry the company is registered at."
    )
    addresses: list[Address] | None = Field(None, description="Its addresses.")
    registration_date: Normalized | None = Field(None, description="When it was registered.")
    foundation_date: Normalized | None = Field(None, description="When it was founded.")
    legal_form: Normalized | None = Field(None, description="Its legal form.")
    status: Normalized | None = Field(
        None, description="Its legal status, such as whether it is active."
    )
    activities: list[Activity] | None = Field(None, description="Its industry classifications.")
    activity_declarations: list[ActivityDeclaration] | None = Field(
        None, description="Its business purpose as the registry states it."
    )
    total_capital: TotalCapital | None = Field(None, description="Its share capital.")
    capital: list[Capital] | None = Field(None, description="Its share classes and holders.")
    representatives: Parties | None = Field(None, description="Its directors and officers.")
    ultimate_beneficial_owners: Parties | None = Field(
        None, description="Its ultimate beneficial owners, from the registers that record them."
    )
    contact_details: ContactDetails | None = Field(None, description="How to reach it.")


class PendingProfile(KyckrModel):
    """A profile Kyckr is still fetching from the registry."""

    status: str = Field(description="`Pending` until the profile is ready.")
    order_id: str | int = Field(description="The order to poll with `get_order`.")
    cost: Cost | None = Field(None, description="What the order costs.")


class EnhancedProfileReply(Reply):
    """An Enhanced company profile, or the order that fetches it."""

    data: EnhancedProfile | PendingProfile | None = Field(
        None, description="The profile, or the order to poll while it is pending."
    )
