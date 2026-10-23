from typing import Literal

from pydantic import BaseModel

UpdateMode = Literal["FULL", "SUMMARY"]


class OngoingScreening(BaseModel):
    case_system_id: str
    enabled: bool
    provider_type: str
    failures: list[str]


class OgsWindow(BaseModel):
    since: str
    until: str


class OgsUpdate(BaseModel):
    case_id: str | None
    case_system_id: str
    group_id: str | None
    update_date: str | None
    new_results: int | None
    updated_results: int | None


class OgsPage(BaseModel):
    window: OgsWindow
    updates: list[OgsUpdate]
    next_page: str | None
