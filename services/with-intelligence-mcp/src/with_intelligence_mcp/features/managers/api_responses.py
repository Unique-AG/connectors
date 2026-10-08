"""With Intelligence's manager shapes, from the v3 schemas.

Service providers (`administrator`, `auditor`, `custodian`, `legal_advisor`, `prime_broker`) are
declared as one classification and delivered as a list. AUM figures are in millions.
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from with_intelligence_mcp.features.investors import ClassificationAttributes
from with_intelligence_mcp.with_intelligence_client import SEQUENCE, SINGLE


class ManagerAumAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    as_of: str | None = None
    aum: float | None = None
    aum_type: int | None = None
    is_estimate: bool | None = None
    type_name: str | None = None


class ManagerContactAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    contact_name: str | None = None


class ManagerListItemAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    updated_at: str | None = None


class ManagerExtendedAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    updated_at: str | None = None
    summary: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    sec_number: str | None = None
    sec_registered_firm: bool | None = None
    address1: str | None = None
    city: str | None = None
    postcode: str | None = None
    country: Annotated[ClassificationAttributes | None, SINGLE] = None
    continent: Annotated[ClassificationAttributes | None, SINGLE] = None
    aums: Annotated[list[ManagerAumAttributes] | None, SEQUENCE] = None
    types: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    fund_asset_classes: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    funds_primary_strategies: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    funds_secondary_strategies: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    funds_investment_regions: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    contacts: Annotated[list[ManagerContactAttributes] | None, SEQUENCE] = None
    administrator: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = Field(default=None)
    auditor: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = Field(default=None)
    custodian: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = Field(default=None)
    legal_advisor: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = Field(default=None)
    prime_broker: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = Field(default=None)
