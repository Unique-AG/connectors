from collections.abc import AsyncGenerator

import pytest
from pydantic import SecretStr

from backstop_mcp.backstop_client import (
    BackstopClientFactory,
    BackstopCredentialSecret,
)
from backstop_mcp.dependencies import get_current_caller_username
from tests.helpers import client_factory, credential

_USERNAME = "alice.jones"
_TOKEN = "super-secret-token"


class _FakeCallerAuth:
    def __init__(self, cred: BackstopCredentialSecret) -> None:
        self._credential = cred

    async def current_credential(self) -> BackstopCredentialSecret:
        return self._credential

    def current_subject(self) -> str | None:
        return "mcp-subject"

    async def revoke_current_subject_tokens(self) -> None:
        return None


@pytest.fixture
async def factory() -> AsyncGenerator[BackstopClientFactory]:
    built = client_factory()
    yield built
    await built.aclose()


async def test_returns_the_attached_caller_username(factory: BackstopClientFactory) -> None:
    factory.attach_auth(_FakeCallerAuth(credential(username=_USERNAME, token=_TOKEN)))

    username = await factory.current_caller_username()

    assert type(username) is str
    assert username == _USERNAME
    assert username != _TOKEN
    assert not isinstance(username, SecretStr)


async def test_provider_returns_the_attached_caller_username(
    factory: BackstopClientFactory,
) -> None:
    factory.attach_auth(_FakeCallerAuth(credential(username=_USERNAME, token=_TOKEN)))

    username = await get_current_caller_username(factory)

    assert type(username) is str
    assert username == _USERNAME
    assert username != _TOKEN
    assert not isinstance(username, SecretStr)


async def test_without_attach_auth_fails_like_for_current_caller(
    factory: BackstopClientFactory,
) -> None:
    with pytest.raises(AssertionError):
        factory.for_current_caller()

    with pytest.raises(AssertionError):
        await factory.current_caller_username()
