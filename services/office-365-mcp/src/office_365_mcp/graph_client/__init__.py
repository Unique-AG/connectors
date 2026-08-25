"""Microsoft Graph transport using the official SDK for one caller's delegated token.

This package knows nothing about Teams, mail, calendars, or the service config.
"""

from office_365_mcp.graph_client.client import create_graph_transport, graph_client_for
from office_365_mcp.graph_client.errors import (
    GRAPH_STATUSES,
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphPagingUnending,
    GraphThrottled,
    GraphUnavailable,
    graph_errors,
    graph_step,
)
from office_365_mcp.graph_client.observability import (
    GRAPH_OPERATION_DURATION_SECONDS,
    GRAPH_OPERATIONS_TOTAL,
    GRAPH_PAGES_SCANNED,
    GRAPH_STEP_DURATION_SECONDS,
    GRAPH_STEPS_TOTAL,
    GRAPH_THROTTLED_TOTAL,
)
from office_365_mcp.graph_client.pagination import (
    CollectedItems,
    GraphCollection,
    collect_pages,
)
from office_365_mcp.graph_client.settings import GraphSettings

__all__ = [
    "GRAPH_OPERATIONS_TOTAL",
    "GRAPH_OPERATION_DURATION_SECONDS",
    "GRAPH_PAGES_SCANNED",
    "GRAPH_STATUSES",
    "GRAPH_STEPS_TOTAL",
    "GRAPH_STEP_DURATION_SECONDS",
    "GRAPH_THROTTLED_TOTAL",
    "CollectedItems",
    "GraphCollection",
    "GraphFailure",
    "GraphForbidden",
    "GraphNotFound",
    "GraphPagingUnending",
    "GraphSettings",
    "GraphThrottled",
    "GraphUnavailable",
    "collect_pages",
    "create_graph_transport",
    "graph_client_for",
    "graph_errors",
    "graph_step",
]
