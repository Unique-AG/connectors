"""Microsoft Graph transport using the official SDK for one caller's delegated token.

This package knows nothing about Teams, mail, calendars, or the service config.
"""

from office_365_mcp.graph_client.client import (
    FetchedResponse,
    TypedQueryParameters,
    create_graph_transport,
    fetch_response,
    graph_client_for,
    native_response,
    no_retry,
    request_with_query,
)
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
    not_graph,
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
    "FetchedResponse",
    "GraphCollection",
    "GraphFailure",
    "GraphForbidden",
    "GraphNotFound",
    "GraphPagingUnending",
    "GraphSettings",
    "GraphThrottled",
    "GraphUnavailable",
    "TypedQueryParameters",
    "collect_pages",
    "create_graph_transport",
    "fetch_response",
    "graph_client_for",
    "graph_errors",
    "graph_step",
    "native_response",
    "no_retry",
    "not_graph",
    "request_with_query",
]
