import logging
from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from backstop_mcp.backstop_client import included_by_type
from backstop_mcp.features.opportunities.api_responses import OpportunityStageAttributes

logger = logging.getLogger(__name__)


def get_stage_id_to_name_map(
    included: Sequence[dict[str, object]],
) -> Mapping[str, str]:
    """Stage id to name for every `opportunity-stages` resource side-loaded with the response.

    Selected by JSON:API `type` rather than followed from linkage, because the stages a history
    entry points at are reached through an inline `ResourceRef` that nothing on the primary
    resource links to. An unnamed or unreadable row is skipped: naming a stage is the only thing
    this index is for.
    """
    names: dict[str, str] = {}
    for raw in included_by_type(included, "opportunity-stages"):
        stage_id = raw.get("id")
        if not isinstance(stage_id, str) or not stage_id.strip():
            continue
        try:
            attributes = OpportunityStageAttributes.model_validate(raw.get("attributes"))
        except ValidationError as exc:
            logger.warning(
                "opportunities.side_loaded_stage.unreadable",
                extra={"stage_id": stage_id},
                exc_info=exc,
            )
            continue
        if attributes.name:
            names[stage_id.strip()] = attributes.name
    return names
