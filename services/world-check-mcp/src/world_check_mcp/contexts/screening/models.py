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
    result_id: str | None
    reference_id: str | None
    provider_type: str | None
    match_strength: str | None
    submitted_term: str | None
    mrz_line_1: str | None = None
    mrz_line_2: str | None = None
    mrz_line_3: str | None = None


class ScreeningOutcome(BaseModel):
    case_id: str | None
    case_system_id: str
    name: str | None
    entity_type: str | None
    group_id: str | None
    matches_returned: int
    watchlist_matches: list[ScreeningMatch]
    watchlist_truncated: bool
    passport_matches: list[ScreeningMatch]
