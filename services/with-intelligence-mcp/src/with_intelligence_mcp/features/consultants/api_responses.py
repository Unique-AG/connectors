"""With Intelligence's consultant shapes, from the v3 schemas.

A consultant is the firm advising an allocator. The address carries the contact details; the
`funds_*` lists are the strategies and asset classes that firm covers, not funds it manages.
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict

from with_intelligence_mcp.features.investors import ClassificationAttributes
from with_intelligence_mcp.with_intelligence_client import SEQUENCE, SINGLE


class ConsultantStateAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None
    abbreviation: str | None = None


class ConsultantAddressAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    address1: str | None = None
    city: str | None = None
    postcode: str | None = None
    email: str | None = None
    phone: str | None = None
    state: Annotated[ConsultantStateAttributes | None, SINGLE] = None
    country: Annotated[ClassificationAttributes | None, SINGLE] = None
    continent: Annotated[ClassificationAttributes | None, SINGLE] = None


class ConsultantListItemAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    updated_at: str | None = None


class ConsultantExtendedAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    updated_at: str | None = None
    website: str | None = None
    address: Annotated[ConsultantAddressAttributes | None, SINGLE] = None
    services: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    funds_asset_classes: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    funds_primary_strategies: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    funds_secondary_strategies: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    funds_investment_regions: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
