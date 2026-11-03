from datetime import date
from typing import Literal

from pydantic import BaseModel
from pydantic import Field

EntityType = Literal["INDIVIDUAL", "ORGANISATION"]
Gender = Literal["MALE", "FEMALE", "UNSPECIFIED"]


class FieldValue(BaseModel):
    type_id: str = Field(description="typeId from get_group_settings.")
    value: str | None = Field(default=None, description="Text, country, or gender value.")
    date_time_value: date | None = Field(default=None, description="Date value for a DATE field.")


class ScreeningMatch(BaseModel):
    result_id: str | None = Field(description="ID of the result within the case.")
    reference_id: str | None = Field(
        description="World-Check record reference ID, for get_profile."
    )
    provider_type: str | None = Field(
        description="Provider that produced the match, e.g. WATCHLIST."
    )
    match_strength: str | None = Field(description="Match strength, e.g. EXACT or WEAK.")
    submitted_term: str | None = Field(description="Submitted term that produced the match.")
    mrz_line_1: str | None = Field(
        default=None, description="First MRZ line, passport results only."
    )
    mrz_line_2: str | None = Field(
        default=None, description="Second MRZ line, passport results only."
    )
    mrz_line_3: str | None = Field(
        default=None, description="Third MRZ line, passport results only."
    )


class ScreeningOutcome(BaseModel):
    case_id: str | None = Field(
        description="Client-provided external case ID, if the case has one."
    )
    case_system_id: str = Field(description="LSEG-generated internal case ID (caseSystemId).")
    name: str | None = Field(description="Screened entity name.")
    entity_type: str | None = Field(description="Entity type, INDIVIDUAL or ORGANISATION.")
    group_id: str | None = Field(description="ID of the group that owns the case.")
    matches_returned: int = Field(description="Total matches the screening returned.")
    watchlist_matches: list[ScreeningMatch] = Field(
        description="WATCHLIST matches, truncated to the requested limit."
    )
    watchlist_truncated: bool = Field(
        description="Whether WATCHLIST matches were cut to the limit."
    )
    passport_matches: list[ScreeningMatch] = Field(description="Passport-check matches, if any.")
