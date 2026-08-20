from functools import lru_cache

from fastmcp.dependencies import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client import (
    BackstopClient,
    BackstopClientFactory,
    BackstopTransportSettings,
    RetrySettings,
)
from backstop_mcp.config import (
    ActivityHistoryConfig,
    AppConfig,
    AuthConfig,
    BackstopConfig,
    DatabaseConfig,
    EncryptionConfig,
)
from backstop_mcp.db import create_engine, create_session_factory
from backstop_mcp.features.auth import (
    BackstopAuthContext,
    BackstopOAuthProvider,
    ThrottleConfig,
    load_key,
)


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    return AppConfig()


@lru_cache(maxsize=1)
def get_backstop_config() -> BackstopConfig:
    return BackstopConfig()


@lru_cache(maxsize=1)
def get_database_config() -> DatabaseConfig:
    return DatabaseConfig()


@lru_cache(maxsize=1)
def get_encryption_config() -> EncryptionConfig:
    return EncryptionConfig()


@lru_cache(maxsize=1)
def get_auth_config() -> AuthConfig:
    return AuthConfig()


@lru_cache(maxsize=1)
def get_activity_history_config() -> ActivityHistoryConfig:
    return ActivityHistoryConfig()


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    return create_engine(get_database_config())


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return create_session_factory(get_engine())


@lru_cache(maxsize=1)
def get_encryption_key() -> bytes:
    return load_key(get_encryption_config())


@lru_cache(maxsize=1)
def get_backstop_client_factory() -> BackstopClientFactory:
    factory = BackstopClientFactory(
        transport_settings(get_backstop_config()), retry_settings(get_backstop_config())
    )
    factory.attach_auth(
        BackstopAuthContext(
            session_factory=get_session_factory(),
            encryption_key=get_encryption_key(),
            # Deferred: get_auth_provider() needs this factory, so the hook looks the
            # provider up only when a mid-session 401 fires, after both caches are warm.
            revoke_tokens_for_subject=_revoke_subject_tokens,
        )
    )
    return factory


async def _revoke_subject_tokens(subject: str) -> None:
    await get_auth_provider().revoke_all_tokens_for_subject(subject)


@lru_cache(maxsize=1)
def get_auth_provider() -> BackstopOAuthProvider:
    config = get_app_config()
    auth_config = get_auth_config()
    return BackstopOAuthProvider(
        base_url=config.issuer,
        secure_cookies=config.public_base_url.scheme == "https",
        session_factory=get_session_factory(),
        encryption_key=get_encryption_key(),
        backstop_clients=get_backstop_client_factory(),
        throttle=ThrottleConfig(
            max_attempts=auth_config.login_max_attempts,
            window=auth_config.login_attempt_window,
        ),
    )


async def get_backstop_client(
    factory: BackstopClientFactory = Depends(get_backstop_client_factory),
) -> BackstopClient:
    return await factory.for_current_caller()


def transport_settings(config: BackstopConfig) -> BackstopTransportSettings:
    """Translate the env-parsed Backstop config into the transport's own settings type.

    Field-for-field, and deliberately explicit rather than derived by reflection: adding a knob
    to `BackstopConfig` that the transport should see is then a visible edit here, and one it
    should *not* see (schema TTL) simply never appears.
    """
    return BackstopTransportSettings(
        base_url=config.base_url,
        default_timeout_seconds=config.default_timeout_seconds,
        reports_timeout_seconds=config.reports_timeout_seconds,
        max_concurrent_requests_per_user=config.max_concurrent_requests_per_user,
        default_page_size=config.default_page_size,
        report_page_size=config.report_page_size,
        page_limit_param=config.page_limit_param,
        page_offset_param=config.page_offset_param,
    )


def retry_settings(config: BackstopConfig) -> RetrySettings:
    return RetrySettings(
        max_attempts=config.max_retry_attempts, max_wait_ms=config.max_retry_wait_ms
    )


async def close_singletons() -> None:
    try:
        if get_backstop_client_factory.cache_info().currsize:
            await get_backstop_client_factory().aclose()
        if get_engine.cache_info().currsize:
            await get_engine().dispose()
    finally:
        get_app_config.cache_clear()
        get_backstop_config.cache_clear()
        get_database_config.cache_clear()
        get_encryption_config.cache_clear()
        get_auth_config.cache_clear()
        get_activity_history_config.cache_clear()
        get_engine.cache_clear()
        get_session_factory.cache_clear()
        get_encryption_key.cache_clear()
        get_backstop_client_factory.cache_clear()
        get_auth_provider.cache_clear()
