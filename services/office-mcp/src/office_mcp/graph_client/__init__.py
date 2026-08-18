"""Microsoft Graph transport using the official SDK for one caller's delegated token.

This package knows nothing about Teams, mail, calendars, or the service config. create_app
will translate app config into GraphSettings and inject it.
"""

from office_mcp.graph_client.client import create_graph_transport, graph_client_for
from office_mcp.graph_client.errors import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphThrottled,
    GraphUnavailable,
    graph_errors,
)
from office_mcp.graph_client.pagination import (
    MAX_SCANNED_ITEMS,
    CollectedItems,
    collect_pages,
)
from office_mcp.graph_client.settings import GraphSettings

__all__ = [
    "MAX_SCANNED_ITEMS",
    "CollectedItems",
    "GraphFailure",
    "GraphForbidden",
    "GraphNotFound",
    "GraphSettings",
    "GraphThrottled",
    "GraphUnavailable",
    "collect_pages",
    "create_graph_transport",
    "graph_client_for",
    "graph_errors",
]
