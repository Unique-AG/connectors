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
from backstop_mcp.features.custom_fields.api_responses import (
    BulkCustomFieldValuesAttributes,
    BulkCustomFieldValuesDocument,
)
from backstop_mcp.features.custom_fields.custom_fields_service import CustomFieldsService
from backstop_mcp.features.custom_fields.internal_dto import CustomFieldDefinitionDto
from backstop_mcp.features.custom_fields.responses import (
    RecordOutcomeResponse,
    UpdateCustomFieldValuesResponse,
)
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
                self._raise_if_invalid(requested_row, catalog)
            payload = json_api_create(
                resource_type="bulk-custom-field-values",
                attributes={
                    "records": [
                        omit_none_values(
                            {
                                "definitionId": requested_row.definition_id,
                                "value": requested_row.value,
                                "effectiveDate": isoformat(requested_row.effective_date),
                            }
                        )
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
            outcomes = self._outcomes(update.values, document.data.attributes)
            applied_count = sum(1 for outcome in outcomes if outcome.status == "applied")
            logger.info(
                "custom_fields.values.updated",
                extra={
                    "entity_type": update.entity_type,
                    "total_count": len(outcomes),
                    "applied_count": applied_count,
                    "failed_count": len(outcomes) - applied_count,
                },
            )
            return UpdateCustomFieldValuesResponse(
                total_count=len(outcomes),
                applied_count=applied_count,
                records=outcomes,
            )

    def _raise_if_invalid(
        self,
        requested_row: UpdateCustomFieldValueInput,
        catalog: dict[str, CustomFieldDefinitionDto],
    ) -> None:
        definition = catalog.get(str(requested_row.definition_id))
        if definition is None:
            raise ToolError(
                f"No custom-field definition has id {requested_row.definition_id}. "
                + "Use list_custom_fields."
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
    ) -> tuple[RecordOutcomeResponse, ...]:
        summary = attributes.summary()
        error_by_index = {
            message.index: message.message
            for message in summary.error_messages
            if message.index is not None
        }
        batch_error = next(
            (
                message.message
                for message in summary.error_messages
                if message.index is None and message.message
            ),
            None,
        )
        written_ids = [
            written_row.definition_id
            for written_row in attributes.records
            if written_row.definition_id
        ]
        outcomes: list[RecordOutcomeResponse] = []
        for index, requested_row in enumerate(requested_rows):
            definition_id = str(requested_row.definition_id)
            if index in error_by_index:
                error: str | None = error_by_index[index]
            elif summary.success_count == 0:
                error = batch_error or "Backstop reported successCount 0 for this batch."
            elif definition_id in written_ids:
                written_ids.remove(definition_id)
                error = None
            else:
                error = batch_error or (
                    "Backstop did not return this row among the written records."
                )
            outcomes.append(
                RecordOutcomeResponse(
                    index=index,
                    record_id=definition_id,
                    status="failed" if error else "applied",
                    error=error,
                )
            )
        return tuple(outcomes)


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
