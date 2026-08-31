from collections.abc import Mapping, Sequence

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    Included,
    IncludedResource,
    ResourceRef,
)
from backstop_mcp.features.opportunities.api_responses import OpportunityStageHistoryAttributes
from backstop_mcp.features.opportunities.opportunity_stages_service import (
    OpportunityStagesService,
)
from backstop_mcp.features.opportunities.resource_utils.get_stage_id_to_name_map import (
    get_stage_id_to_name_map,
)
from backstop_mcp.features.opportunities.responses import StageChangeResponse

_StageHistoryInclude = IncludedResource[OpportunityStageHistoryAttributes]


class GetStageHistoryQuery:
    """Resolve side-loaded `stageHistory` entries into named `StageChangeResponse`s."""

    def __init__(
        self,
        *,
        opportunity_stages_service: OpportunityStagesService,
    ) -> None:
        self._opportunity_stages_service: OpportunityStagesService = opportunity_stages_service

    async def run[AttrT](
        self,
        *,
        resource: BackstopApiResource[AttrT],
        api_include_resources: Sequence[dict[str, object]],
        preloaded_opportunity_id_to_name: Mapping[str, str] | None,
    ) -> tuple[StageChangeResponse, ...]:
        changes: list[StageChangeResponse] = []

        if preloaded_opportunity_id_to_name is None:
            preloaded_opportunity_id_to_name = get_stage_id_to_name_map(api_include_resources)

        for entry in Included(api_include_resources).related(
            resource, "stageHistory", schema=_StageHistoryInclude
        ):
            stage_ref = ResourceRef.safe_model_validate(entry.attributes.stage)
            stage_id = stage_ref.resource_id if stage_ref is not None else None
            stage_name = await self._opportunity_stages_service.get_stage_name(
                stage_id=stage_id,
                preloaded_opportunity_id_to_name=preloaded_opportunity_id_to_name,
            )
            changes.append(
                StageChangeResponse(
                    stage=stage_name,
                    stage_id=stage_id,
                    effective_date=entry.attributes.effective_date,
                )
            )
        return tuple(changes)
