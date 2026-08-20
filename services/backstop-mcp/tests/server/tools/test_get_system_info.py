from collections.abc import Callable

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AccessToken
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client import BackstopAuthError
from backstop_mcp.features.auth import BackstopAuthContext, NotConnectedError
from backstop_mcp.server.tools.get_system_info import get_system_info
from tests.helpers import BASE_URL, client_factory, custom_fields_service, install_services
from tests.server.tools.helpers import tool_payload

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]
type ConnectUser = Callable[..., object]


def _fake_access_token(subject: str) -> AccessToken:
    return AccessToken(token="access-token", client_id="client-1", scopes=[], subject=subject)


class TestGetSystemInfo:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_backstop_response_for_connected_user(
        self, connect_user: ConnectUser
    ) -> None:
        await connect_user("user-tool-1", "tool-bob.smith")  # pyright: ignore[reportGeneralTypeIssues]
        respx.get(f"{BASE_URL}/system-info").mock(
            return_value=httpx.Response(200, json={"version": "1.0"})
        )

        result = tool_payload(await get_system_info())

        assert result == {"version": "1.0"}

    @pytest.mark.asyncio
    async def test_raises_not_connected_when_no_credential(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, session_factory = db

        async def _noop_revoke(_subject: str) -> None:
            return None

        factory = client_factory(
            BASE_URL,
            auth=BackstopAuthContext(
                session_factory=session_factory,
                encryption_key=Fernet.generate_key(),
                revoke_tokens_for_subject=_noop_revoke,
            ),
        )
        install_services(backstop=factory, custom_fields=custom_fields_service())
        monkeypatch.setattr(
            "backstop_mcp.features.auth.context.get_access_token",
            lambda: _fake_access_token("user-never-connected"),
        )

        try:
            with pytest.raises(NotConnectedError):
                await get_system_info()
        finally:
            await factory.aclose()

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_backstop_auth_error_when_credential_revoked(
        self, connect_user: ConnectUser
    ) -> None:
        """A mid-session Backstop 401 revokes the caller's MCP tokens, forcing a re-login."""
        revoked_subjects: list[str] = []

        async def _record_revoke(subject: str) -> None:
            revoked_subjects.append(subject)

        await connect_user(  # pyright: ignore[reportGeneralTypeIssues]
            "user-tool-2",
            "tool-carol.diaz",
            "revoked-token",
            revoke_tokens_for_subject=_record_revoke,
        )
        respx.get(f"{BASE_URL}/system-info").mock(return_value=httpx.Response(401))

        with pytest.raises(BackstopAuthError):
            await get_system_info()

        assert revoked_subjects == ["user-tool-2"]
