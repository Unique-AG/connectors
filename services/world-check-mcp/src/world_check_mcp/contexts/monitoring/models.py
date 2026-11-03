from typing import Literal

from pydantic import BaseModel
from pydantic import Field

UpdateMode = Literal["FULL", "SUMMARY"]


class OngoingScreening(BaseModel):
    case_system_id: str = Field(description="LSEG-generated internal case ID (caseSystemId).")
    enabled: bool = Field(description="Whether WATCHLIST ongoing screening is now enabled.")
    provider_type: str = Field(description="Provider the monitoring applies to, WATCHLIST.")
    failures: list[str] = Field(description="Reasons LSEG did not enable monitoring, if any.")


class OgsWindow(BaseModel):
    since: str = Field(description="Start of the update window (ISO 8601).")
    until: str = Field(description="End of the update window (ISO 8601).")


class OgsUpdate(BaseModel):
    case_id: str | None = Field(
        description="Client-provided external case ID, if the case has one."
    )
    case_system_id: str = Field(description="LSEG-generated internal case ID (caseSystemId).")
    group_id: str | None = Field(description="ID of the group that owns the case.")
    update_date: str | None = Field(description="When the update was recorded (ISO 8601).")
    new_results: int | None = Field(description="Number of new WATCHLIST results in the update.")
    updated_results: int | None = Field(
        description="Number of changed WATCHLIST results in the update."
    )


class OgsPage(BaseModel):
    window: OgsWindow = Field(description="The date window these updates cover.")
    updates: list[OgsUpdate] = Field(description="Monitoring updates on this page.")
    next_page: str | None = Field(
        description="Cursor for the next page, or null when there is none."
    )
