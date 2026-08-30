"""`get_opportunities_by_ids`: full records with resolved custom fields for up to 50 ids."""

import logging
from collections.abc import Sequence
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.custom_fields import (
    CustomFieldFilters,
)
from backstop_mcp.features.opportunities import (
    MAX_OPPORTUNITY_IDS,
    GetOpportunitiesByIdsQuery,
    GetOpportunitiesByIdsResponse,
)
from backstop_mcp.features.opportunities.dependencies import get_opportunities_by_ids_query_factory
from backstop_mcp.models import CoercedId, coerce_ids, published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetOpportunitiesByIdsResponse),
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
    get_opportunities_by_ids_query: GetOpportunitiesByIdsQuery = Depends(
        get_opportunities_by_ids_query_factory
    ),
) -> GetOpportunitiesByIdsResponse:
    """Fetch up to 50 opportunities by id, with resolved custom fields.

    Use after search_opportunities when the question needs a field that is not on the search
    row (Master Pipeline custom fields, amounts not in the sparse fieldset). Ids are trusted
    handles — never invent them. A missing id is named in `not_found`; a non-404 failure is
    named in `errors`. The rest of the batch is still returned. When
    `custom_fields_unavailable` is true, an empty `custom_field_values` list means the
    catalog could not be loaded, not that the deal has none.

    Stage history is omitted unless `include_stage_history` is true. A full 50-id batch without
    history is ~37,000 tokens; further batching is the caller's job.
    """
    opportunity_ids = coerce_ids(ids)
    logger.info(
        "opportunities.by_ids.start",
        extra={"count": len(opportunity_ids), "include_stage_history": include_stage_history},
    )
    result = await get_opportunities_by_ids_query.run(
        opportunity_ids=opportunity_ids,
        include_stage_history=include_stage_history,
        custom_fields_filters=CustomFieldFilters(
            definition_ids=coerce_ids(custom_field_definition_ids),
            names=tuple(custom_field_names),
        ),
    )
    logger.info(
        "opportunities.by_ids.completed",
        extra={
            "returned": len(result.opportunities),
            "not_found": len(result.not_found),
            "errors": len(result.errors),
        },
    )
    return result
