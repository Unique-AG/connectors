from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class OmitNoneModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")


class MandateAmountResponse(OmitNoneModel):
    value_millions: float | None = Field(
        default=None, description="Size of the search, in MILLIONS of `currency`."
    )
    currency: str | None = None


class MandateResponse(OmitNoneModel):
    """One allocation search by this investor."""

    id: int
    status: str | None = Field(
        default=None, description="Where the search stands, in the vendor's own words."
    )
    sub_status: str | None = None
    service: str | None = Field(
        default=None, description="What kind of mandate it is, e.g. a manager search."
    )
    amount: MandateAmountResponse | None = None
    asset_classes: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    structures: list[str] = Field(default_factory=list)
    market_focuses: list[str] = Field(default_factory=list)
    awarded_to: str | None = Field(default=None, description="The fund that won it, once one has.")
    consultant: str | None = None
    consultant_firm: str | None = None
    rfp_link: str | None = None
    last_reviewed: str | None = Field(
        default=None,
        description="When the vendor last confirmed it. An old date is a stale mandate.",
    )
    updated_at: str | None = None
    note: str | None = None
    latest_note: str | None = None
    latest_note_date: str | None = None


class InvestorMandatesResponse(OmitNoneModel):
    """An investor's allocation searches, newest first.

    Status is the vendor's vocabulary, not a boolean: read it rather than assuming "active".
    """

    investor_id: int
    investor_name: str | None = None
    mandates: list[MandateResponse] = Field(default_factory=list)
    total: int = Field(default=0, description="How many mandates the vendor holds in total.")
    returned: int = 0
