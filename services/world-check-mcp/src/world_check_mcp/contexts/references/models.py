from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class Profile(BaseModel):
    reference_id: str = Field(description="World-Check record reference ID.")
    entity_type: str = Field(description="Entity type, INDIVIDUAL or ORGANISATION.")
    names: list[str] = Field(description="Names on the record, primary first.")
    categories: list[str] = Field(description="Record categories, e.g. Sanctions or PEP.")


class ProviderSummary(BaseModel):
    code: str | None = Field(description="Provider short code, e.g. trwc.")
    identifier: str | None = Field(description="Provider identifier used by the API.")
    name: str | None = Field(description="Human-readable provider name.")


class SearchFilter(BaseModel):
    kind: Literal["query", "custom", "filter"] = Field(description="Kind of search parameter.")
    fields: list[str] = Field(description="Field names available for this parameter.")


class ReferenceData(BaseModel):
    kind: Literal["countries", "nationalities", "providers", "search_filters", "api_info"] = Field(
        description="Which reference dataset this response carries."
    )
    names_by_code: dict[str, str] | None = Field(
        default=None, description="Name keyed by code, for countries and nationalities."
    )
    providers: list[ProviderSummary] | None = Field(
        default=None, description="Available providers, for the providers kind."
    )
    search_filters: list[SearchFilter] | None = Field(
        default=None, description="Available search parameters, for the search_filters kind."
    )
    api_version: str | None = Field(default=None, description="LSEG API version, for api_info.")
    system_date_time: str | None = Field(
        default=None, description="LSEG system time (ISO 8601), for api_info."
    )
