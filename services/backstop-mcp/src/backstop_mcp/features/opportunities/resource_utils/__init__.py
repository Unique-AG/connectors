"""Shared mapping and aggregation used by the opportunity queries."""

from backstop_mcp.features.opportunities.resource_utils.aggregate_search_opportunities import (
    aggregate_search_opportunities,
)
from backstop_mcp.features.opportunities.resource_utils.get_stage_history_query import (
    GetStageHistoryQuery,
)
from backstop_mcp.features.opportunities.resource_utils.get_stage_id_to_name_map import (
    get_stage_id_to_name_map,
)
from backstop_mcp.features.opportunities.resource_utils.map_opportunity_to_response_util import (
    MapOpportunityToResponseUtil,
)

__all__ = [
    "GetStageHistoryQuery",
    "MapOpportunityToResponseUtil",
    "aggregate_search_opportunities",
    "get_stage_id_to_name_map",
]
