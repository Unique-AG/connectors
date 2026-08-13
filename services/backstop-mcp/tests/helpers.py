"""Shared test construction helpers.

Mirrors what `create_app()` does, minus the web layer: build one `BackstopClientFactory` the way
production does. Tests that need a client go through the factory exactly as production does, so
the concurrency gate and config injection under test are the real ones.
"""

from pydantic import SecretStr

from backstop_mcp.app import retry_settings, transport_settings
from backstop_mcp.backstop_client.credential import BackstopCredentialSecret
from backstop_mcp.backstop_client.factory import BackstopClientFactory
from backstop_mcp.config import BackstopConfig
from backstop_mcp.features.auth.context import BackstopAuthContext

BASE_URL = "https://example.backstopsolutions.com"


def credential(username: str = "bob.smith", token: str = "token") -> BackstopCredentialSecret:
    return BackstopCredentialSecret(username=username, api_token=SecretStr(token))


def backstop_config(base_url: str = BASE_URL, **overrides: object) -> BackstopConfig:
    """Build a config, applying `overrides` on top of the validated defaults.

    `model_copy` rather than passing the overrides to `__init__`: it keeps the helper's
    signature honest (`**overrides: object`, since a test may tune any field) without
    surrendering the constructor's own parameter types to `object`.
    """
    return BackstopConfig(base_url=base_url).model_copy(update=overrides)


def client_factory(
    base_url: str = BASE_URL,
    *,
    auth: BackstopAuthContext | None = None,
    **overrides: object,
) -> BackstopClientFactory:
    """Build a factory the way `create_app` does: config in, transport settings out.

    Goes through the same `app.transport_settings` / `app.retry_settings` translation as
    production rather than constructing settings directly, so a knob that stops being propagated
    at the composition root fails these tests too.
    """
    config = backstop_config(base_url, **overrides)
    return BackstopClientFactory(transport_settings(config), retry_settings(config), auth=auth)
