from collections.abc import Mapping, Sequence

from pydantic import TypeAdapter, ValidationError

from backstop_mcp.app import logger
from backstop_mcp.backstop_client import BackstopApiResource, ResourceRef, follow_included
from backstop_mcp.features.opportunities import StageChangeResponse
from backstop_mcp.features.opportunities.oppportunity_stage_service_v2 import (
    OpportunityStagesServiceV2,
)
from backstop_mcp.features.opportunities.resource_utils.get_stage_id_to_name_map import (
    get_stage_id_to_name_map,
)

_DictAttributesAdapter: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])


class GetStageHistoryQuery:
    def __init__(
        self,
        *,
        opportunity_stages_service: OpportunityStagesServiceV2,
    ) -> None:
        self._opportunity_stages_service: OpportunityStagesServiceV2 = opportunity_stages_service

    async def run[AttrT](
        self,
        *,
        resource: BackstopApiResource[AttrT],
        # Top level include in backstop
        api_include_resources: Sequence[dict[str, object]],
        # Optional it can be obtained from backstop_resource_top_level_include
        preloaded_opportunity_id_to_name: Mapping[str, str] | None,
    ) -> tuple[StageChangeResponse, ...]:
        changes: list[StageChangeResponse] = []

        if preloaded_opportunity_id_to_name is None:
            preloaded_opportunity_id_to_name = get_stage_id_to_name_map(api_include_resources)

        for raw in follow_included(api_include_resources, resource, "stageHistory"):
            try:
                attributes = _DictAttributesAdapter.validate_python(raw.get("attributes"))
            except ValidationError as exc:
                logger.warning(
                    "opportunities.stage_history.unreadable",
                    extra={"opportunity_id": resource.id, "entry_id": raw.get("id")},
                    exc_info=exc,
                )
                continue

            stage_ref = ResourceRef.safe_model_validate(attributes.get("stage", None))

            if stage_ref is None:
                continue

            stage_name = await self._opportunity_stages_service.get_stage_name(
                stage_id=stage_ref.resource_id,
                preloaded_opportunity_id_to_name=preloaded_opportunity_id_to_name,
            )
            changes.append(
                StageChangeResponse.model_validate(
                    {
                        **attributes,
                        "stage": stage_name,
                        "stage_id": stage_ref.resource_id,
                    }
                )
            )
        return tuple(changes)
