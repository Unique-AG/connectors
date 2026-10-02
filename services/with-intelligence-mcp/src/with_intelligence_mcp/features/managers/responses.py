from typing import Literal, Self

from pydantic import Field

from with_intelligence_mcp.features.managers.api_responses import (
    ManagerAumAttributes,
    ManagerContactAttributes,
    ManagerExtendedAttributes,
)
from with_intelligence_mcp.models import OmitNoneModel
from with_intelligence_mcp.utils import html_to_markdown, names, when_either, when_present


class ManagerAumResponse(OmitNoneModel):
    value_millions: float | None = Field(
        default=None,
        description=(
            "Assets under management, in MILLIONS. 85000 means 85 billion. Do not report "
            "the raw number as a plain figure."
        ),
    )
    as_of: str | None = Field(default=None, description="Date this figure was reported.")
    type_name: str | None = Field(
        default=None,
        description="Which AUM figure this is, such as GROUP, REGULATORY, or HEDGEMAP.",
        examples=["GROUP"],
    )
    is_estimate: bool | None = Field(
        default=None,
        description="True when With Intelligence did not take this figure from a filing.",
    )


class ManagerProfileResponse(OmitNoneModel):
    """One management company.

    AUM figures are in MILLIONS. Service-provider lists are who administers, audits, and
    primes the firm — a name there is current, not historical.
    """

    id: int = Field(description="With Intelligence manager identifier.", examples=[2145860302])
    name: str | None = Field(default=None, description="Management company name.")
    updated_at: str | None = Field(
        default=None, description="When With Intelligence last changed this manager record."
    )
    summary: str | None = Field(default=None, description="Firm summary, as prose.")
    website: str | None = Field(default=None, description="Firm website.")
    email: str | None = Field(default=None, description="Firm email.")
    phone: str | None = Field(default=None, description="Firm phone.")
    location: str | None = Field(
        default=None,
        description="City and country, as one line.",
        examples=["Westport, United States"],
    )
    sec_number: str | None = Field(default=None, description="SEC registration number, when held.")
    sec_registered_firm: bool | None = Field(
        default=None, description="Whether With Intelligence records the firm as SEC-registered."
    )
    types: list[str] | None = Field(default=None, description="Manager types.")
    aums: list[ManagerAumResponse] | None = Field(
        default=None, description="AUM figures With Intelligence holds. Each value is in millions."
    )
    asset_classes: list[str] | None = Field(
        default=None, description="Asset classes across the firm's funds."
    )
    strategies: list[str] | None = Field(
        default=None, description="Primary and secondary strategies across the firm's funds."
    )
    investment_regions: list[str] | None = Field(
        default=None, description="Regions the firm's funds invest in."
    )
    administrators: list[str] | None = Field(
        default=None, description="Current administrators.", examples=[["State Street"]]
    )
    auditors: list[str] | None = Field(default=None, description="Current auditors.")
    custodians: list[str] | None = Field(default=None, description="Current custodians.")
    legal_advisors: list[str] | None = Field(default=None, description="Current legal advisors.")
    prime_brokers: list[str] | None = Field(
        default=None, description="Current prime brokers.", examples=[["JP Morgan"]]
    )
    contacts: list[str] | None = Field(
        default=None, description="Contact names With Intelligence holds for this manager."
    )

    @classmethod
    def from_attributes(cls, attributes: ManagerExtendedAttributes) -> Self:
        return cls(
            id=attributes.id,
            name=attributes.name,
            updated_at=attributes.updated_at,
            summary=html_to_markdown(attributes.summary),
            website=attributes.website,
            email=attributes.email,
            phone=attributes.phone,
            location=_location(attributes),
            sec_number=attributes.sec_number,
            sec_registered_firm=attributes.sec_registered_firm,
            types=when_present(attributes, "types", names(attributes.types)),
            aums=when_present(attributes, "aums", [_aum(entry) for entry in attributes.aums or []]),
            asset_classes=when_present(
                attributes, "fund_asset_classes", names(attributes.fund_asset_classes)
            ),
            strategies=when_either(
                attributes,
                "funds_primary_strategies",
                "funds_secondary_strategies",
                names(attributes.funds_primary_strategies)
                + names(attributes.funds_secondary_strategies),
            ),
            investment_regions=when_present(
                attributes, "funds_investment_regions", names(attributes.funds_investment_regions)
            ),
            administrators=when_present(
                attributes, "administrator", names(attributes.administrator)
            ),
            auditors=when_present(attributes, "auditor", names(attributes.auditor)),
            custodians=when_present(attributes, "custodian", names(attributes.custodian)),
            legal_advisors=when_present(
                attributes, "legal_advisor", names(attributes.legal_advisor)
            ),
            prime_brokers=when_present(attributes, "prime_broker", names(attributes.prime_broker)),
            contacts=when_present(attributes, "contacts", _contact_names(attributes.contacts)),
        )


class ManagerCandidateResponse(OmitNoneModel):
    id: int
    name: str | None = None
    updated_at: str | None = None


class ManagerAmbiguousResponse(OmitNoneModel):
    """Several managers matched the name. Ask which one, then call again with `manager_id`."""

    status: Literal["ambiguous"] = "ambiguous"
    searched_for: str
    candidates: list[ManagerCandidateResponse] = Field(default_factory=list)
    total_matches: int = 0


class ManagerNotFoundResponse(OmitNoneModel):
    status: Literal["not_found"] = "not_found"
    searched_for: str
    hint: str | None = None


class ManagerNotEntitledResponse(OmitNoneModel):
    status: Literal["not_entitled"] = "not_entitled"
    searched_for: str
    hint: str | None = None


def _contact_names(values: list[ManagerContactAttributes] | None) -> list[str]:
    if values is None:
        return []
    return [value.contact_name for value in values if value.contact_name]


def _aum(attributes: ManagerAumAttributes) -> ManagerAumResponse:
    return ManagerAumResponse(
        value_millions=attributes.aum,
        as_of=attributes.as_of,
        type_name=attributes.type_name,
        is_estimate=attributes.is_estimate,
    )


def _location(attributes: ManagerExtendedAttributes) -> str | None:
    parts = [
        attributes.city,
        attributes.country.name if attributes.country else None,
    ]
    return ", ".join(part for part in parts if part) or None
