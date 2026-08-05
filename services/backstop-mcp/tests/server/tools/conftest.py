"""Wiring shared by the tool tests.

A tool reaches its collaborators through `runtime.get_services()`, exactly as it does in
production, so these fixtures install a real `Services` — one `BackstopClientFactory` (with an
auth context pointed at the test database) plus one `CustomFieldsService`.
"""

import os
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass

import pytest
from mcp.server.auth.provider import AccessToken
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client import BackstopClientFactory
from backstop_mcp.backstop_client.credential import BackstopCredentialSecret
from backstop_mcp.features.auth.context import BackstopAuthContext
from backstop_mcp.features.auth.credential_store import save_credential
from backstop_mcp.features.custom_fields import CustomFieldsService, FieldOverride
from tests.helpers import BASE_URL, client_factory, custom_fields_service, install_services

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


@dataclass(frozen=True)
class ConnectedUser:
    """A logged-in caller whose tools will resolve their own stored Backstop credential."""

    subject: str
    custom_fields: CustomFieldsService
    clients: BackstopClientFactory


type ConnectUser = Callable[..., "AsyncGenerator[ConnectedUser] | object"]


@pytest.fixture
async def connect_user(
    db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[Callable[..., object]]:
    """Return a coroutine factory that stores a credential and installs the runtime services."""
    _, session_factory = db
    built: list[BackstopClientFactory] = []

    async def connect(
        subject: str,
        username: str,
        api_token: str = "token",
        *,
        base_url: str = BASE_URL,
        overrides: dict[str, FieldOverride] | None = None,
    ) -> ConnectedUser:
        key = os.urandom(32)

        async def _noop_revoke(_subject: str) -> None:
            return None

        async with session_factory() as session:
            await save_credential(
                session,
                subject,
                BackstopCredentialSecret(username=username, api_token=SecretStr(api_token)),
                key,
            )
            await session.commit()

        monkeypatch.setattr(
            "backstop_mcp.features.auth.context.get_access_token",
            lambda: AccessToken(
                token="access-token", client_id="client-1", scopes=[], subject=subject
            ),
        )

        factory = client_factory(
            base_url,
            auth=BackstopAuthContext(
                session_factory=session_factory,
                encryption_key=key,
                revoke_tokens_for_subject=_noop_revoke,
            ),
        )
        built.append(factory)
        service = custom_fields_service(session_factory, base_url=base_url, overrides=overrides)
        install_services(backstop=factory, custom_fields=service)
        return ConnectedUser(subject=subject, custom_fields=service, clients=factory)

    yield connect
    for factory in built:
        await factory.aclose()
