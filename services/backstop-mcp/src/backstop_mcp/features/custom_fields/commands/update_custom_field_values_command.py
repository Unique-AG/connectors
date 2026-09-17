"""POST `/bulk-custom-field-values`. Validates against the catalog, then writes."""

import logging

from fastmcp.exceptions import ToolError
from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopClient,
    isoformat,
    json_api_create,
    omit_none_values,
    resource_pointer,
)
from backstop_mcp.features.bulk_writes import (
    BulkRequestedRowDto,
    RecordOutcomeResponse,
    bulk_record_outcomes,
)
from backstop_mcp.features.custom_fields.api_responses import (
    BulkCustomFieldValuesAttributes,
    BulkCustomFieldValuesDocument,
)
from backstop_mcp.features.custom_fields.custom_fields_service import CustomFieldsService
from backstop_mcp.features.custom_fields.entity_types import (
    CustomFieldEntityType,
    custom_field_entity_type_from_bean,
)
from backstop_mcp.features.custom_fields.internal_dto import CustomFieldDefinitionDto
from backstop_mcp.features.custom_fields.responses import UpdateCustomFieldValuesResponse
from backstop_mcp.features.custom_fields.update_custom_field_values_input import (
    UpdateCustomFieldValueInput,
    UpdateCustomFieldValuesInput,
)

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)


class UpdateCustomFieldValuesCommand:
    """Write custom-field values on one person, organization, or opportunity."""

    def __init__(
        self, *, client: BackstopClient, custom_fields_service: CustomFieldsService
    ) -> None:
        self._client: BackstopClient = client
        self._custom_fields_service: CustomFieldsService = custom_fields_service

    async def run(self, *, update: UpdateCustomFieldValuesInput) -> UpdateCustomFieldValuesResponse:
        with _tracer.start_as_current_span("custom_fields.command.update_values") as span:
            span.set_attribute("entity_type", update.entity_type)
            span.set_attribute("record_count", len(update.values))
            catalog, _freshness = await self._custom_fields_service.get()
            for requested_row in update.values:
                self._raise_if_invalid(requested_row, catalog, entity_type=update.entity_type)
            payload = json_api_create(
                resource_type="bulk-custom-field-values",
                attributes={
                    "records": [
                        {
                            "definitionId": requested_row.definition_id,
                            # `value` is written even when null — that is how a non-required
                            # field is cleared. Dropping it would post a record with nothing
                            # to write, which Backstop echoes back as if it had landed.
                            "value": requested_row.value,
                            **omit_none_values(
                                {"effectiveDate": isoformat(requested_row.effective_date)}
                            ),
                        }
                        for requested_row in update.values
                    ],
                    "resource": resource_pointer(
                        resource_id=update.entity_id,
                        resource_type=update.entity_type,
                    ),
                },
            )
            document = await self._client.post(
                "/bulk-custom-field-values",
                schema=BulkCustomFieldValuesDocument,
                json=payload,
            )
            outcomes, warnings = self._outcomes(update.values, document.data.attributes)
            applied_count = sum(1 for outcome in outcomes if outcome.status == "applied")
            logger.info(
                "custom_fields.values.updated",
                extra={
                    "entity_type": update.entity_type,
                    "total_count": len(outcomes),
                    "applied_count": applied_count,
                    "failed_count": len(outcomes) - applied_count,
                    "warning_count": len(warnings),
                },
            )
            return UpdateCustomFieldValuesResponse(
                total_count=len(outcomes),
                applied_count=applied_count,
                records=outcomes,
                warnings=warnings,
            )

    def _raise_if_invalid(
        self,
        requested_row: UpdateCustomFieldValueInput,
        catalog: dict[str, CustomFieldDefinitionDto],
        *,
        entity_type: str,
    ) -> None:
        definition = catalog.get(str(requested_row.definition_id))
        if definition is None:
            raise ToolError(
                f"No custom-field definition has id {requested_row.definition_id}. "
                + "Use list_custom_fields."
            )
        owned_by = custom_field_entity_type_from_bean(definition.entity_type)
        if owned_by is CustomFieldEntityType.PARTY:
            if entity_type not in ("people", "organizations"):
                raise ToolError(
                    f"Custom field {requested_row.definition_id} belongs to "
                    + f"{definition.entity_type}, not {entity_type}. Use list_custom_fields."
                )
        elif owned_by is None or owned_by.value != entity_type:
            raise ToolError(
                f"Custom field {requested_row.definition_id} belongs to "
                + f"{definition.entity_type}, not {entity_type}. Use list_custom_fields."
            )
        if definition.is_time_series and requested_row.effective_date is None:
            raise ToolError(
                f"TimeSeriesCustomField({requested_row.definition_id}) need effectiveDate"
            )
        if not definition.is_time_series and requested_row.effective_date is not None:
            raise ToolError(
                f"RegularCustomField({requested_row.definition_id}) does not need effectiveDate"
            )
        if definition.required and _is_blank(requested_row.value):
            raise ToolError(f"Custom field {requested_row.definition_id} is required.")
        if (
            definition.max_length is not None
            and isinstance(requested_row.value, str)
            and len(requested_row.value) > definition.max_length
        ):
            raise ToolError(
                f"Custom field {requested_row.definition_id} exceeds maxLength "
                + f"{definition.max_length}."
            )
        if definition.select_options and self._custom_fields_service.is_outside_current_options(
            requested_row.value, definition.select_options
        ):
            allowed = self._custom_fields_service.current_option_texts(definition.select_options)
            raise ToolError(
                f"Invalid value for {requested_row.value}, valid options are "
                + f"[{', '.join(allowed)}]"
            )

    def _outcomes(
        self,
        requested_rows: tuple[UpdateCustomFieldValueInput, ...],
        attributes: BulkCustomFieldValuesAttributes,
    ) -> tuple[tuple[RecordOutcomeResponse, ...], tuple[str, ...]]:
        # A value row is identified by the definition it targets; the entity is the same for
        # the whole batch.
        return bulk_record_outcomes(
            requested_rows=[
                BulkRequestedRowDto(
                    record_id=str(requested_row.definition_id),
                    match_key=str(requested_row.definition_id),
                )
                for requested_row in requested_rows
            ],
            written_keys=[
                written_row.definition_id
                for written_row in attributes.records
                if written_row.definition_id
            ],
            summary=attributes.summary(),
        )


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
