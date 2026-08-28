"""`get_opportunities_by_ids`: full records with resolved custom fields for up to 50 ids."""

import logging
from collections.abc import Sequence
from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.custom_fields import (
    CustomFieldFilters,
    CustomFieldsService,
    get_custom_fields_service,
)
from backstop_mcp.features.opportunities import (
    MAX_OPPORTUNITY_IDS,
    OpportunityIdErrorResponse,
    OpportunityResponse,
    OpportunityStagesService,
    fetch_opportunities_by_ids,
    get_opportunity_stages_service,
)
from backstop_mcp.models import CoercedId, OmitNoneModel, coerce_ids, published_output_schema

logger = logging.getLogger(__name__)


class OpportunitiesByIdsResolvedResponse(OmitNoneModel):
    """A completed by-id batch: found deals, missing ids, and per-id errors."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': every requested id was attempted.",
    )
    opportunities: tuple[OpportunityResponse, ...] = Field(
        description="Deals that were found, in the order their ids were requested."
    )
    not_found: tuple[str, ...] = Field(
        default=(),
        description="Requested ids that Backstop answered as 404.",
    )
    errors: tuple[OpportunityIdErrorResponse, ...] = Field(
        default=(),
        description="Requested ids that failed for a reason other than 404.",
    )
    custom_fields_unavailable: bool = Field(
        default=False,
        description=(
            "True when the custom-field catalog could not be loaded, so `custom_field_values` "
            "is empty rather than 'none recorded'."
        ),
    )


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(OpportunitiesByIdsResolvedResponse),
)
async def get_opportunities_by_ids(
    ids: Annotated[
        Sequence[CoercedId],
        Field(
            min_length=1,
            max_length=MAX_OPPORTUNITY_IDS,
            description=(
                f"Trusted opportunity ids from search_opportunities or get_opportunities. "
                f"At most {MAX_OPPORTUNITY_IDS} per call — a full batch is ~37,000 tokens "
                "with custom fields and without stage history. Batch further yourself."
            ),
        ),
    ],
    include_stage_history: Annotated[
        bool,
        Field(
            description=(
                "When true, each record includes stage_history. Off by default: history is "
                "31% of the record and a caller asking for custom fields usually did not ask "
                "for how the deal got here. get_opportunities always returns it."
            ),
        ),
    ] = False,
    custom_field_definition_ids: Annotated[
        Sequence[CoercedId],
        Field(
            description=(
                "Custom-field definition ids whose values to keep, as published on "
                "list_custom_fields `id` and on `custom_field_values[].definition_id`. "
                "JSON numbers are accepted. Combined with custom_field_names with AND. "
                "Omit to keep every definition."
            ),
        ),
    ] = (),
    custom_field_names: Annotated[
        Sequence[str],
        Field(
            description=(
                "Custom-field names whose values to keep. Case-insensitive. Combined with "
                "custom_field_definition_ids with AND. Omit to keep every name."
            ),
        ),
    ] = (),
    client: BackstopClient = Depends(get_backstop_client),
    opportunity_stages_service: OpportunityStagesService = Depends(get_opportunity_stages_service),
    custom_fields_service: CustomFieldsService = Depends(get_custom_fields_service),
) -> OpportunitiesByIdsResolvedResponse:
    """Fetch up to 50 opportunities by id, with resolved custom fields.

    Use after search_opportunities when the question needs a field that is not on the search
    row (Master Pipeline custom fields, amounts not in the sparse fieldset). Ids are trusted
    handles — never invent them. A missing id is named in `not_found`; a non-404 failure is
    named in `errors`. The rest of the batch is still returned.

    Stage history is omitted unless `include_stage_history` is true. A full 50-id batch without
    history is ~37,000 tokens; further batching is the caller's job.
    """
    opportunity_ids = coerce_ids(ids)
    logger.info(
        "opportunities.by_ids.start",
        extra={"count": len(opportunity_ids), "include_stage_history": include_stage_history},
    )
    fetched = await fetch_opportunities_by_ids(
        client,
        opportunity_ids=opportunity_ids,
        include_stage_history=include_stage_history,
        opportunity_stages_service=opportunity_stages_service,
        custom_fields_service=custom_fields_service,
        custom_fields_filters=CustomFieldFilters(
            definition_ids=coerce_ids(custom_field_definition_ids),
            names=tuple(custom_field_names),
        ),
    )
    logger.info(
        "opportunities.by_ids.completed",
        extra={
            "returned": len(fetched.opportunities),
            "not_found": len(fetched.not_found),
            "errors": len(fetched.errors),
        },
    )
    return OpportunitiesByIdsResolvedResponse(
        opportunities=fetched.opportunities,
        not_found=fetched.not_found,
        errors=fetched.errors,
        custom_fields_unavailable=fetched.custom_fields_unavailable,
    )
