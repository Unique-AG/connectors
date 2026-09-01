"""The cached providers tools and `create_app` resolve their collaborators from.

Releasing them is `teardown.close_singletons()`, in its own module so it can import
feature-owned providers without this one importing `features/` back.
"""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from with_intelligence_mcp.config import AppConfig, DatabaseConfig, WithIntelligenceConfig
from with_intelligence_mcp.db import create_engine, create_session_factory
from with_intelligence_mcp.with_intelligence_client import (
    RetrySettings,
    TransportSettings,
    WithIntelligenceClientFactory,
)


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


@lru_cache(maxsize=1)
def get_with_intelligence_client_factory() -> WithIntelligenceClientFactory:
    config = get_with_intelligence_config()
    return WithIntelligenceClientFactory(transport_settings(config), retry_settings(config))


def transport_settings(config: WithIntelligenceConfig) -> TransportSettings:
    """Field-for-field and deliberately explicit: a knob the transport should not see never
    appears here."""
    return TransportSettings(
        base_url=config.base_url,
        default_timeout_seconds=config.default_timeout_seconds,
        default_page_size=config.default_page_size,
        max_concurrent_requests_per_user=config.max_concurrent_requests_per_user,
        asset_class_groups=tuple(group.value for group in config.asset_class_groups),
    )


def retry_settings(config: WithIntelligenceConfig) -> RetrySettings:
    return RetrySettings(
        max_attempts=config.max_retry_attempts, max_wait_ms=config.max_retry_wait_ms
    )
