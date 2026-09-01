"""Postgres: the engine/session helpers and the ORM tables this service owns.

The public surface of the package. Callers take what they need from here rather than reaching
into `engine.py` / `models.py`, so a table moving between modules is not a change to every
feature that reads it. Enforced by `tests/test_layering.py`.
"""

from with_intelligence_mcp.db.engine import (
    create_engine,
    create_session_factory,
    read_session,
    transaction,
)
from with_intelligence_mcp.db.models import Base

__all__ = [
    "Base",
    "create_engine",
    "create_session_factory",
    "read_session",
    "transaction",
]
