from collections.abc import Mapping, Sequence

from backstop_mcp.backstop_client import IncludedResource, filter_included
from backstop_mcp.features.opportunities.api_responses import OpportunityStageAttributes


def get_stage_id_to_name_map(
    included: Sequence[dict[str, object]],
) -> Mapping[str, str]:
    """Stage id to name for every `opportunity-stages` resource side-loaded with the response.

    Selected by JSON:API `type` rather than followed from linkage, because the stages a history
    entry points at are reached through an inline `ResourceRef` that nothing on the primary
    resource links to. An unnamed or unreadable row is skipped: naming a stage is the only thing
    this index is for.
    """
    return {
        stage.id: stage.attributes.name
        for stage in filter_included(
            included,
            resource_type="opportunity-stages",
            schema=IncludedResource[OpportunityStageAttributes],
        )
        if stage.attributes.name
    }
