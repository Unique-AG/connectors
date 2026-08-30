import logging
from collections.abc import Mapping, Sequence

from pydantic import TypeAdapter, ValidationError

from backstop_mcp.backstop_client import BackstopApiResource, ResourceRef, follow_included
from backstop_mcp.features.opportunities.opportunity_stages_service import (
    OpportunityStagesService,
)
from backstop_mcp.features.opportunities.resource_utils.get_stage_id_to_name_map import (
    get_stage_id_to_name_map,
)
from backstop_mcp.features.opportunities.responses import StageChangeResponse

logger = logging.getLogger(__name__)

_DictAttributesAdapter: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])


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
            stage_id = stage_ref.resource_id if stage_ref is not None else None
            stage_name = await self._opportunity_stages_service.get_stage_name(
                stage_id=stage_id,
                preloaded_opportunity_id_to_name=preloaded_opportunity_id_to_name,
            )
            changes.append(
                StageChangeResponse.model_validate(
                    {
                        **attributes,
                        "stage": stage_name,
                        "stage_id": stage_id,
                    }
                )
            )
        return tuple(changes)
