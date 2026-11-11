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
    lines: list[str] = Field(description="Generated MRZ lines.")
    conforms_with_icao: bool | None = Field(
        description="Whether the MRZ conforms to ICAO, or null when LSEG does not say."
    )


class PassportCheck(BaseModel):
    case_id: str | None = Field(
        description="Client-provided external case ID, if the case has one."
    )
    case_system_id: str = Field(description="LSEG-generated internal case ID (caseSystemId).")
    name: str | None = Field(description="Screened entity name.")
    group_id: str | None = Field(description="ID of the group that owns the case.")
    passport_matches: list[ScreeningMatch] = Field(description="Passport-check matches, if any.")
    watchlist_matches: list[ScreeningMatch] = Field(
        description="WATCHLIST matches, truncated to the requested limit."
    )
    watchlist_truncated: bool = Field(
        description="Whether WATCHLIST matches were cut to the limit."
    )


class PassportVerificationRequest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    case: str
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
    recorded: bool = Field(description="Whether the verification was saved to LSEG.")
    status: Literal["cancelled"] | None = Field(
        default=None, description="'cancelled' when the reviewer declined, otherwise null."
    )
    case_system_id: str | None = Field(
        default=None, description="LSEG-generated internal case ID (caseSystemId)."
    )
    mrz_matched: bool | None = Field(
        default=None, description="Whether the reviewer confirmed the MRZ matched."
    )
    note: str | None = Field(default=None, description="Saved verification note, with reviewer.")
    guidance: str | None = Field(default=None, description="Next-step guidance for the caller.")
