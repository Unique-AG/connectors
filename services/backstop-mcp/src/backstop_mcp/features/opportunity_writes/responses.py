"""Published opportunity-write responses.

A single-deal write reports the stage Backstop landed on after a re-read. A bulk history
backfill reports per-record outcomes — HTTP 201 is not success.
"""

from typing import Literal

from pydantic import Field

from backstop_mcp.features.bulk_writes import RecordOutcomeResponse
from backstop_mcp.features.party_resolver import PartyAmbiguousResponse
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.models import OmitNoneModel

_URL_DESCRIPTION = (
    "Canonical CRM UI URL for this opportunity (no tab). Omitted when this deployment "
    "has no UI origin. Echo it; never invent one. Call build_backstop_links for tabs "
    "or a layout."
)

__all__ = [
    "BackfillOpportunityStageHistoryResponse",
    "CreateOpportunityResponse",
    "CreatedOpportunityResponse",
    "DeleteOpportunityResponse",
    "DeletedOpportunityResponse",
    "UpdatedOpportunityResponse",
]


class CreatedOpportunityResponse(OmitNoneModel):
    """An opportunity after a POST, with the stage Backstop actually stored."""

    id: str = Field(
        description="Backstop id of the created opportunity. Echo it; never invent one."
    )
    resource_type: Literal["opportunities"] = Field(
        default="opportunities",
        description="Always `opportunities`.",
    )
    name: str | None = Field(
        default=None,
        description="Deal name READ BACK after the write.",
    )
    stage: str | None = Field(
        default=None,
        description=(
            "Stage name READ BACK after the write. A requested stage that did not land "
            "is named here as whatever Backstop stored, with an entry in `warnings`."
        ),
    )
    stage_id: str | None = Field(
        default=None,
        description="Backstop id of that stage, kept even when the name could not be resolved.",
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description=(
            "Silent-failure notes: a requested stage that did not land. Empty when the "
            "write landed as asked."
        ),
    )
    url: str | None = Field(default=None, description=_URL_DESCRIPTION)


class DeletedOpportunityResponse(OmitNoneModel):
    """A hard delete: Backstop has no recycle bin, so `permanent` is always true."""

    id: str = Field(
        description="Backstop id of the deleted opportunity. Echo it; never invent one."
    )
    resource_type: Literal["opportunities"] = Field(
        default="opportunities",
        description="Always `opportunities`.",
    )
    permanent: Literal[True] = Field(
        default=True,
        description="Always true: Backstop hard-deletes the record. There is no recycle bin.",
    )


class UpdatedOpportunityResponse(OmitNoneModel):
    """An opportunity after a PATCH, with the stage Backstop actually stored."""

    id: str = Field(description="Backstop id of the opportunity. Echo it; never invent one.")
    resource_type: str = Field(
        default="opportunities",
        description="Always `opportunities`.",
    )
    stage: str | None = Field(
        default=None,
        description=(
            "Stage name READ BACK after the write. A requested stage that did not move "
            "is named here as the previous stage, with an entry in `warnings`."
        ),
    )
    stage_id: str | None = Field(
        default=None,
        description="Backstop id of that stage, kept even when the name could not be resolved.",
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description=(
            "Silent-failure notes: a requested stage that did not move, or a notify "
            "login that did not match a system user. Empty when the write landed as asked."
        ),
    )
    url: str | None = Field(default=None, description=_URL_DESCRIPTION)


class BackfillOpportunityStageHistoryResponse(OmitNoneModel):
    """Per-record outcomes of a stage-history backfill. This does not move any deal's stage."""

    total_count: int = Field(description="How many records were sent.")
    applied_count: int = Field(
        description=(
            "How many request rows came back with `status` `applied`. A `201` is not success; "
            "compare this with `total_count`."
        )
    )
    records: tuple[RecordOutcomeResponse, ...] = Field(
        description="One outcome per request record, in request order."
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description=(
            "Messages Backstop returned that could not be attributed to a single request "
            "row. Empty when every message landed on a record."
        ),
    )


type DeleteOpportunityResponse = DeletedOpportunityResponse

type CreateOpportunityResponse = (
    CreatedOpportunityResponse | PartyAmbiguousResponse | NotFoundResponse
)
