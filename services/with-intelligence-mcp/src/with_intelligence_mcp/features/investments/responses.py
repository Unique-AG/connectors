from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class OmitNoneModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")


class PositionAmountResponse(OmitNoneModel):
    value_millions: float | None = Field(
        default=None, description="Committed or held amount, in MILLIONS of `currency`."
    )
    as_of: str | None = None
    currency: str | None = None


class PositionResponse(OmitNoneModel):
    """One position: a fund this investor holds, or held."""

    id: int
    fund: str | None = None
    fund_id: int | None = None
    manager: str | None = None
    manager_id: int | None = Field(
        default=None, description="Use with manager_id filters to find their other investors."
    )
    amount: PositionAmountResponse | None = None
    asset_classes: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    structures: list[str] = Field(default_factory=list)
    as_of: str | None = Field(default=None, description="When the vendor last confirmed it.")
    is_current: bool = Field(
        default=True, description="False once the position carries an exit date."
    )
    exited_on: str | None = None
    fund_unidentified: bool | None = Field(
        default=None,
        description="The vendor records the position but could not identify which fund it is in.",
    )


class InvestorPositionsResponse(OmitNoneModel):
    """An investor's fund roster — who they allocate to, and at what size."""

    investor_id: int
    investor_name: str | None = None
    positions: list[PositionResponse] = Field(default_factory=list)
    total: int = Field(default=0, description="How many positions the vendor holds in total.")
    returned: int = 0
