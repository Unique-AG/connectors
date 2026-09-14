"""`update_custom_field_values`: write catalog-validated values on one entity."""

import logging
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.custom_fields import (
    UPDATE_CUSTOM_FIELD_VALUES_INPUT_DESCRIPTION,
    UpdateCustomFieldValuesCommand,
    UpdateCustomFieldValuesInput,
    UpdateCustomFieldValuesResponse,
    get_update_custom_field_values_command_factory,
)
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(UpdateCustomFieldValuesResponse),
)
async def update_custom_field_values(
    update: Annotated[
        UpdateCustomFieldValuesInput,
        Field(description=UPDATE_CUSTOM_FIELD_VALUES_INPUT_DESCRIPTION),
    ],
    update_custom_field_values_command: UpdateCustomFieldValuesCommand = Depends(
        get_update_custom_field_values_command_factory
    ),
) -> UpdateCustomFieldValuesResponse:
    """Write custom-field values on one person, organization, or opportunity.

    Identify each field by `definition_id` from `list_custom_fields`, never by name. An
    opportunity has a custom field literally called Probability that is not the native
    `probability` attribute. Time-series vs regular branching comes from the catalog: a
    time-series field needs `effective_date`; a regular field rejects one. Picklist values
    must match current options. Do not write custom fields on `update_opportunity` — that
    skips this validation. The entity id comes from `get_person`, `get_organization`, or
    `get_opportunities`. A `201` is not success: read `records[].status`.

    Call like: {"update": {"entity_type": "people", "entity_id": "<id from get_person>",
    "values": [{"definition_id": 9823191, "value": "Direct"}]}}
    """
    logger.info(
        "custom_fields.update_values.start",
        extra={
            "entity_type": update.entity_type,
            "record_count": len(update.values),
        },
    )
    return await update_custom_field_values_command.run(update=update)
