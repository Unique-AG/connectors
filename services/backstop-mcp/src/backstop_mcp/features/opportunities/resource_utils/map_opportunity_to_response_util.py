from collections.abc import Sequence

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.custom_fields import (
    CustomFieldFilters,
    CustomFieldsService,
)
from backstop_mcp.features.opportunities.oppportunity_stage_service_v2 import (
    OpportunityStagesServiceV2,
)
from backstop_mcp.features.opportunities.queries.opportuntity_resource import OpportunityResource
from backstop_mcp.features.opportunities.resource_utils import GetStageHistoryQuery
from backstop_mcp.features.opportunities.resource_utils.get_stage_id_to_name_map import (
    get_stage_id_to_name_map,
)
from backstop_mcp.features.opportunities.responses import OpportunityResponse
from backstop_mcp.utils import first_item


class MapOpportunityToResponseUtil:
    def __init__(
        self,
        *,
        client: BackstopClient,
        opportunity_stages_service: OpportunityStagesServiceV2,
        custom_fields_service: CustomFieldsService,
        get_stage_history_query: GetStageHistoryQuery,
    ) -> None:
        self._client: BackstopClient = client
        self._opportunity_stages_service: OpportunityStagesServiceV2 = opportunity_stages_service
        self._custom_fields_service: CustomFieldsService = custom_fields_service
        self._get_stage_history_query: GetStageHistoryQuery = get_stage_history_query

    async def run(
        self,
        *,
        row: OpportunityResource,
        api_include_resources: Sequence[dict[str, object]],
        custom_fields_filters: CustomFieldFilters,
        include_stage_history: bool = True,
    ) -> OpportunityResponse:
        stage_id = first_item(row.related_ids("stage"))

        custom_field_values = await self._custom_fields_service.join_values(
            self._client,
            row.attributes.regular_custom_field_values,
            filters=custom_fields_filters,
        )
        preloaded_opportunity_id_to_name = get_stage_id_to_name_map(api_include_resources)
        stage_name = await self._opportunity_stages_service.get_stage_name(
            stage_id=stage_id, preloaded_opportunity_id_to_name=preloaded_opportunity_id_to_name
        )
        stage_history = (
            await self._get_stage_history_query.run(
                resource=row,
                api_include_resources=api_include_resources,
                preloaded_opportunity_id_to_name=preloaded_opportunity_id_to_name,
            )
            if include_stage_history
            else ()
        )

        return OpportunityResponse.from_resource(
            row,
            stage=stage_name,
            stage_id=stage_id,
            stage_history=stage_history,
            custom_field_values=tuple(custom_field_values),
        )
