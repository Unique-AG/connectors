from fastmcp.server.providers.openapi import (
    MCPType,
    OpenAPIResource,
    OpenAPIResourceTemplate,
    OpenAPITool,
)
from fastmcp.utilities.openapi import HTTPRoute
from mcp_types import ToolAnnotations

MCP_NAMES = {
    "get-companies": "get_companies",
    "get-companies-kyckrId": "get_companies_kyckr_id",
    "get-companies-kyckrId-enhanced": "get_companies_kyckr_id_enhanced",
    "get-companies-kyckrId-documents": "get_companies_kyckr_id_documents",
    "post-orders": "post_orders",
    "get-orders-orderId": "get_orders_order_id",
    "get-order": "get_orders",
    "get-orders-orderId-download": "get_orders_order_id_download",
}

EXPOSED = dict.fromkeys(MCP_NAMES, MCPType.TOOL)

PAID_OPERATIONS = frozenset(
    {"get-companies-kyckrId", "get-companies-kyckrId-enhanced", "post-orders"}
)


def route_map_fn(route: HTTPRoute, _default: MCPType) -> MCPType:
    return EXPOSED.get(route.operation_id or "", MCPType.EXCLUDE)


def annotate_component(
    route: HTTPRoute, component: OpenAPITool | OpenAPIResource | OpenAPIResourceTemplate
) -> None:
    if isinstance(component, OpenAPITool):
        component.annotations = ToolAnnotations(
            read_only_hint=route.method.upper() == "GET",
            destructive_hint=False,
            idempotent_hint=route.operation_id not in PAID_OPERATIONS,
            open_world_hint=True,
        )
