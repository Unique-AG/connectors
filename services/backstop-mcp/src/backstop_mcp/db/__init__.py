"""Postgres: the engine/session helpers this service owns.

The public surface of the package. Callers take what they need from here rather than reaching
into `engine.py`, so a helper moving between modules is not a change to every feature that reads
it. Enforced by `tests/test_layering.py`.
"""

from backstop_mcp.db.engine import (
    create_engine,
    create_session_factory,
    read_session,
    transaction,
)

__all__ = [
    "create_engine",
    "create_session_factory",
    "read_session",
    "transaction",
]
