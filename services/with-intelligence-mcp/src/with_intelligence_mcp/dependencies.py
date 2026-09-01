"""The cached providers tools and `create_app` resolve their collaborators from.

Releasing them is `teardown.close_singletons()`, in its own module so it can import
feature-owned providers without this one importing `features/` back.
"""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from with_intelligence_mcp.config import AppConfig, DatabaseConfig, WithIntelligenceConfig
from with_intelligence_mcp.db import create_engine, create_session_factory


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    return AppConfig()


@lru_cache(maxsize=1)
def get_with_intelligence_config() -> WithIntelligenceConfig:
    return WithIntelligenceConfig()


@lru_cache(maxsize=1)
def get_database_config() -> DatabaseConfig:
    return DatabaseConfig()


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    return create_engine(get_database_config())


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return create_session_factory(get_engine())
