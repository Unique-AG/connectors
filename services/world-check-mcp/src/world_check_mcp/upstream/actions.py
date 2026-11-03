from typing import ClassVar

from mcp_openapi.upstream import Operation
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import TypeAdapter

from world_check_mcp.upstream.generated.vendor_requests import (
    ToggleOngoingScreeningByProviderTypesRequest,
)
from world_check_mcp.upstream.generated.vendor_responses import CaseBulkResponse


class ScreeningMatchWire(BaseModel):
    """A screening result. The generated model drops mrzLine1-3: the spec puts them on a passport
    result subtype that the codegen collapses into the base, so this stays hand-written.
    Pinned by tests/test_spec_overrides.py.
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


class ScreenedCaseWire(BaseModel):
    """The save-and-screen response the tools read. Hand-written because its results carry the
    passport mrzLine fields that the generated ScreeningResultCollection drops.
    Pinned by tests/test_spec_overrides.py.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    case_id: str | None = Field(default=None, alias="caseId")
    case_system_id: str | None = Field(default=None, alias="caseSystemId")
    name: str | None = None
    entity_type: str | None = Field(default=None, alias="entityType")
    group_id: str | None = Field(default=None, alias="groupId")
    results: list[ScreeningMatchWire] = []


# saveAndScreenCase and partialUpdateCase build their bodies dynamically and return results that
# carry the passport mrzLine fields the spec omits, so they stay hand-written and call_untyped.
SAVE_AND_SCREEN = Operation[ScreenedCaseWire]("saveAndScreenCase", TypeAdapter(ScreenedCaseWire))
PARTIAL_UPDATE_CASE = Operation[ScreenedCaseWire](
    "partialUpdateCase", TypeAdapter(ScreenedCaseWire)
)
# A success is an empty 204, so the response is widened to None over the generated model, which the
# codegen types without it. The generated request model still types the call.
# Pinned by tests/test_spec_overrides.py.
TOGGLE_ONGOING_SCREENING = Operation[
    CaseBulkResponse | None, ToggleOngoingScreeningByProviderTypesRequest
]("toggleOngoingScreeningByProviderTypes", TypeAdapter(CaseBulkResponse | None))
# Neither write returns a JSON body, so the codegen cannot generate an operation for them.
# Pinned by tests/test_spec_overrides.py.
VERIFY_PASSPORT = Operation[None]("mrzDataValidation", TypeAdapter(None))
RESOLVE_RESULTS = Operation[None]("resolveResults", TypeAdapter(None))
