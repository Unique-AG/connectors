from typing import ClassVar

from mcp_openapi.upstream import Operation
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import TypeAdapter

from world_check_mcp.upstream.generated.vendor_requests import GetResultsRequest
from world_check_mcp.upstream.generated.vendor_responses import PaginationReferenceResponse


class ResultWire(BaseModel):
    """A case result. Hand-written because it carries the passport mrzLine fields that the generated
    AbstractScreeningResult drops (the spec models them on a subtype the codegen collapses away).
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    result_id: str | None = Field(default=None, alias="resultId")
    reference_id: str | None = Field(default=None, alias="referenceId")
    provider_type: str | None = Field(default=None, alias="providerType")
    match_strength: str | None = Field(default=None, alias="matchStrength")
    submitted_term: str | None = Field(default=None, alias="submittedTerm")
    mrz_line_1: str | None = Field(default=None, alias="mrzLine1")
    mrz_line_2: str | None = Field(default=None, alias="mrzLine2")
    mrz_line_3: str | None = Field(default=None, alias="mrzLine3")


class ResultsWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    results: list[ResultWire] = []
    pagination: PaginationReferenceResponse | None = None


class ProviderCountWire(BaseModel):
    """A per-provider screening summary. The generated CaseResultsSummary types reviewRequired as a
    bool, but the API sends the count there, so this stays hand-written.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    total_matches: int | None = Field(default=None, alias="totalMatches")
    review_required: int | None = Field(default=None, alias="reviewRequired")
    unresolved: int | None = None


class ScreeningStatusWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    case_system_id: str = Field(alias="caseSystemId")
    screening_status: str | None = Field(default=None, alias="screeningStatus")
    provider_summaries: dict[str, ProviderCountWire] = Field(
        default_factory=dict, alias="providerSummaries"
    )


# getResults keeps its generated request model but a hand-written response, since the results carry
# the passport mrzLine fields the generated model drops.
GET_RESULTS = Operation[ResultsWire, GetResultsRequest]("getResults", TypeAdapter(ResultsWire))
# getScreeningStatus has a JSON response but the generated model types reviewRequired as a bool
# where the API sends the count, so it stays hand-written and call_untyped.
GET_SCREENING_STATUS = Operation[list[ScreeningStatusWire]](
    "getScreeningStatus", TypeAdapter(list[ScreeningStatusWire])
)


def next_page(pagination: PaginationReferenceResponse | None) -> str | None:
    if pagination is None or pagination.page_references is None:
        return None
    reference = pagination.page_references.next
    return reference or None
