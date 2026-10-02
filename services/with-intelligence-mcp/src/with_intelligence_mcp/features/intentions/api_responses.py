"""With Intelligence's intention shapes, from the v3 schemas.

An intention is forward-looking allocation intent. The whole resource is a subscription add-on:
a refusal means the account is not licensed for it. `status.id` is not modelled — on funds the
same field arrives as a string, and a number here would reject the whole record.
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict

from with_intelligence_mcp.features.investors import ClassificationAttributes
from with_intelligence_mcp.with_intelligence_client import SEQUENCE, SINGLE


class IntentionAmountAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    value_lower_usd: float | None = None
    value_upper_usd: float | None = None


class IntentionStatusLabelAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str | None = None


class IntentionStatusAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str | None = None
    sub_status: Annotated[IntentionStatusLabelAttributes | None, SINGLE] = None


class IntentionStrategyAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    primary_strategy: Annotated[ClassificationAttributes | None, SINGLE] = None
    secondary_strategies: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None


class IntentionSegmentsAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    strategies: Annotated[IntentionStrategyAttributes | None, SINGLE] = None


class IntentionPreferenceAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    name: str | None = None
    sentiment: str | None = None
    type: str | None = None


class IntentionListItemAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    updated_at: str | None = None
    date: str | None = None


class IntentionExtendedAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    updated_at: str | None = None
    date: str | None = None
    note: str | None = None
    preference_only: bool | None = None
    search_consultant: bool | None = None
    allocation_amount: Annotated[IntentionAmountAttributes | None, SINGLE] = None
    ticket_size: Annotated[IntentionAmountAttributes | None, SINGLE] = None
    asset_class: Annotated[ClassificationAttributes | None, SINGLE] = None
    status: Annotated[IntentionStatusAttributes | None, SINGLE] = None
    structures: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    themes: Annotated[list[ClassificationAttributes] | None, SEQUENCE] = None
    preferences: Annotated[list[IntentionPreferenceAttributes] | None, SEQUENCE] = None
    classification_segments: Annotated[IntentionSegmentsAttributes | None, SINGLE] = None
