from datetime import date
from typing import ClassVar, Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from world_check_mcp.contexts.screening import Gender
from world_check_mcp.contexts.screening import ScreeningMatch

DocumentType = Literal["PASSPORT", "ID1", "ID2"]


class Passport(BaseModel):
    given_name: str = Field(description="Given names as printed on the document.")
    last_name: str = Field(description="Surname as printed on the document.")
    gender: Gender = Field(description="MALE, FEMALE, or UNSPECIFIED.")
    date_of_birth: date = Field(description="Date of birth as printed. Not in the future.")
    issuing_state: str = Field(description="Issuing-state code from reference nationalities.")
    nationality: str = Field(description="Nationality code from reference nationalities.")
    identification_number: str = Field(description="Document number as printed.")
    date_of_expiry: date = Field(description="Expiry date as printed.")
    document_type: DocumentType = Field(default="PASSPORT", description="PASSPORT, ID1, or ID2.")


class Mrz(BaseModel):
    lines: list[str]
    conforms_with_icao: bool | None


class PassportCheck(BaseModel):
    case_id: str | None
    case_system_id: str
    name: str | None
    group_id: str | None
    passport_matches: list[ScreeningMatch]
    watchlist_matches: list[ScreeningMatch]
    watchlist_truncated: bool


class PassportVerificationRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    case_system_id: str
    mrz_matched: bool
    note: str


class PassportMrz(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    result_id: str | None
    mrz_line_1: str | None
    mrz_line_2: str | None
    mrz_line_3: str | None


class PassportVerificationPlan(BaseModel):
    """The comparison a person is asked to approve. Re-read before the write."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    case_system_id: str
    case_id: str | None
    case_name: str
    mrz_matched: bool
    note: str
    lines: tuple[PassportMrz, ...]


class PassportVerification(BaseModel):
    recorded: bool
    status: Literal["cancelled"] | None = None
    case_system_id: str | None = None
    mrz_matched: bool | None = None
    note: str | None = None
    guidance: str | None = None
