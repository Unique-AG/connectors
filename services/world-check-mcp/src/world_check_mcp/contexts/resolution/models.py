from typing import ClassVar, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class ResolutionRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    case_system_id: str
    result_id: str
    status: str
    risk: str
    reason: str | None
    note: str


class ResolutionChoice(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    label: str
    status_type: str | None = None


class ResolutionPlan(BaseModel):
    """The match decision a person is asked to approve. Re-read before the write."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    case_system_id: str
    case_id: str | None
    case_name: str
    result_id: str
    reference_id: str | None
    submitted_term: str | None
    status: ResolutionChoice
    risk: ResolutionChoice
    reason: ResolutionChoice | None
    note: str
    rule_risks: tuple[str, ...]
    rule_reasons: tuple[str, ...]
    reason_required: bool
    remark_required: bool


class ResolutionOutcome(BaseModel):
    resolved: bool = Field(description="Whether the decision was saved to LSEG.")
    status: Literal["cancelled"] | None = Field(
        default=None, description="'cancelled' when the reviewer declined, otherwise null."
    )
    case_system_id: str | None = Field(
        default=None, description="LSEG-generated internal case ID (caseSystemId)."
    )
    result_id: str | None = Field(default=None, description="ID of the resolved result.")
    status_id: str | None = Field(default=None, description="Applied resolution status ID.")
    risk_id: str | None = Field(default=None, description="Applied risk rating ID.")
    reason_id: str | None = Field(default=None, description="Applied resolution reason ID, if any.")
    note: str | None = Field(default=None, description="Saved resolution note, with reviewer.")
