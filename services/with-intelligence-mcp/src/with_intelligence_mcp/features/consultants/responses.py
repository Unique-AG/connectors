from typing import Literal, Self

from pydantic import Field

from with_intelligence_mcp.features.consultants.api_responses import ConsultantExtendedAttributes
from with_intelligence_mcp.features.investors import ClassificationAttributes
from with_intelligence_mcp.models import OmitNoneModel


class ConsultantProfileResponse(OmitNoneModel):
    """One consulting firm: where it is, how to reach it, and what it advises on."""

    id: int = Field(description="With Intelligence consultant identifier.")
    name: str | None = Field(default=None, description="Consulting firm name.")
    updated_at: str | None = Field(
        default=None, description="When With Intelligence last changed this consultant record."
    )
    website: str | None = Field(default=None, description="Firm website.")
    email: str | None = Field(default=None, description="Email from the firm's address record.")
    phone: str | None = Field(default=None, description="Phone from the firm's address record.")
    location: str | None = Field(
        default=None,
        description="City, state, and country, as one line.",
        examples=["Boston, MA, United States"],
    )
    services: list[str] | None = Field(
        default=None, description="Services this firm provides, such as investment consultant."
    )
    asset_classes: list[str] | None = Field(
        default=None, description="Asset classes this firm advises on."
    )
    strategies: list[str] | None = Field(
        default=None, description="Strategies this firm advises on."
    )
    investment_regions: list[str] | None = Field(
        default=None, description="Regions this firm advises on."
    )

    @classmethod
    def from_attributes(cls, attributes: ConsultantExtendedAttributes) -> Self:
        address = attributes.address
        return cls(
            id=attributes.id,
            name=attributes.name,
            updated_at=attributes.updated_at,
            website=attributes.website,
            email=address.email if address else None,
            phone=address.phone if address else None,
            location=_location(attributes),
            services=_when_present(attributes, "services", _names(attributes.services)),
            asset_classes=_when_present(
                attributes, "funds_asset_classes", _names(attributes.funds_asset_classes)
            ),
            strategies=_when_either(
                attributes,
                "funds_primary_strategies",
                "funds_secondary_strategies",
                _names(attributes.funds_primary_strategies)
                + _names(attributes.funds_secondary_strategies),
            ),
            investment_regions=_when_present(
                attributes,
                "funds_investment_regions",
                _names(attributes.funds_investment_regions),
            ),
        )


class ConsultantCandidateResponse(OmitNoneModel):
    id: int
    name: str | None = None
    updated_at: str | None = None


class ConsultantAmbiguousResponse(OmitNoneModel):
    """Several consultants matched the name. Ask which one, then call again with `consultant_id`."""

    status: Literal["ambiguous"] = "ambiguous"
    searched_for: str
    candidates: list[ConsultantCandidateResponse] = Field(default_factory=list)
    total_matches: int = 0


class ConsultantNotFoundResponse(OmitNoneModel):
    status: Literal["not_found"] = "not_found"
    searched_for: str
    hint: str | None = None


class ConsultantNotEntitledResponse(OmitNoneModel):
    status: Literal["not_entitled"] = "not_entitled"
    searched_for: str
    hint: str | None = None


def _names(values: list[ClassificationAttributes] | None) -> list[str]:
    if values is None:
        return []
    return [value.name for value in values if value.name]


def _location(attributes: ConsultantExtendedAttributes) -> str | None:
    address = attributes.address
    if address is None:
        return None
    parts = [
        address.city,
        address.state.abbreviation if address.state and address.state.abbreviation else None,
        address.country.name if address.country else None,
    ]
    joined = ", ".join(part for part in parts if part)
    return joined or None


def _when_present[T](attributes: ConsultantExtendedAttributes, field: str, value: T) -> T | None:
    return value if field in attributes.model_fields_set else None


def _when_either[T](
    attributes: ConsultantExtendedAttributes, first: str, second: str, value: T
) -> T | None:
    if first in attributes.model_fields_set or second in attributes.model_fields_set:
        return value
    return None
