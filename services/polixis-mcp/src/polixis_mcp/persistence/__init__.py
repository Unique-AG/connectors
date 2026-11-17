# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

"""Storage the MCP owns: Postgres holds the Zitadel sign-in state. Polixis data stays in Polixis."""

from polixis_mcp.persistence.persistence import open_persistence
from polixis_mcp.persistence.persistence import Persistence
from polixis_mcp.persistence.persistence import PersistenceSettings
from polixis_mcp.persistence.store import sign_in_store
from polixis_mcp.persistence.store import StoreSettings

__all__ = [
    "Persistence",
    "PersistenceSettings",
    "StoreSettings",
    "open_persistence",
    "sign_in_store",
]
