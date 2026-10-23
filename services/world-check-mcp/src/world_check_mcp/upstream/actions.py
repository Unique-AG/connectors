from typing import ClassVar

from mcp_openapi.upstream import Operation
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import TypeAdapter

from world_check_mcp.upstream.queries import PaginationWire
from world_check_mcp.upstream.queries import ResultWire


class ScreenedCaseWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    case_id: str | None = Field(default=None, alias="caseId")
    case_system_id: str | None = Field(default=None, alias="caseSystemId")
    name: str | None = None
    entity_type: str | None = Field(default=None, alias="entityType")
    group_id: str | None = Field(default=None, alias="groupId")
    results: list[ResultWire] = []


class BulkErrorWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    code: str | None = None
    message: str | None = None


class FailedCaseWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    case_system_id: str | None = Field(default=None, alias="caseSystemId")
    errors: list[BulkErrorWire] = []


class BulkResultWire(BaseModel):
    """A 200 body lists the cases LSEG did not update. A 204 body is empty."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    failed_cases: list[FailedCaseWire] = Field(default_factory=list, alias="failedCases")


class WatchlistUpdateWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    new_results: int | None = Field(default=None, alias="numberOfNewResults")
    updated_results: int | None = Field(default=None, alias="numberOfUpdatedResults")


class OgsUpdateWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    case_id: str | None = Field(default=None, alias="caseId")
    case_system_id: str | None = Field(default=None, alias="caseSystemId")
    group_id: str | None = Field(default=None, alias="groupId")
    update_date: str | None = Field(default=None, alias="updateDate")
    watchlist_results: WatchlistUpdateWire | None = Field(default=None, alias="watchlistResults")


class OgsUpdatesWire(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    results: list[OgsUpdateWire] = []
    pagination: PaginationWire | None = None


SAVE_AND_SCREEN = Operation[ScreenedCaseWire]("saveAndScreenCase", TypeAdapter(ScreenedCaseWire))
PARTIAL_UPDATE_CASE = Operation[ScreenedCaseWire](
    "partialUpdateCase", TypeAdapter(ScreenedCaseWire)
)
TOGGLE_ONGOING_SCREENING = Operation[BulkResultWire | None](
    "toggleOngoingScreeningByProviderTypes", TypeAdapter(BulkResultWire | None)
)
GET_OGS_UPDATES = Operation[OgsUpdatesWire](
    "getOngoingScreeningUpdates", TypeAdapter(OgsUpdatesWire)
)
