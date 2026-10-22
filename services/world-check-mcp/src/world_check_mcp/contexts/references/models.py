from typing import Literal

from pydantic import BaseModel


class Profile(BaseModel):
    reference_id: str
    entity_type: str
    names: list[str]
    categories: list[str]


class ProviderSummary(BaseModel):
    code: str | None
    identifier: str | None
    name: str | None


class SearchFilter(BaseModel):
    kind: Literal["query", "custom", "filter"]
    fields: list[str]


class ReferenceData(BaseModel):
    kind: Literal["countries", "nationalities", "providers", "search_filters", "api_info"]
    names_by_code: dict[str, str] | None = None
    providers: list[ProviderSummary] | None = None
    search_filters: list[SearchFilter] | None = None
    api_version: str | None = None
    system_date_time: str | None = None
