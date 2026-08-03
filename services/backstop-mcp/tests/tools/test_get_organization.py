import os

import httpx
import pytest
import respx
from mcp.server.auth.provider import AccessToken
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.auth import context as auth_context
from backstop_mcp.auth.credential_store import save_credential
from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.backstop_client import BackstopResponseSchemaError
from backstop_mcp.party_resolver import (
    CandidateEcho,
    NeedsDisambiguationResponse,
    ResolvedPartyEcho,
)
from backstop_mcp.tools.get_organization import OrganizationResolvedResponse, get_organization
from tests.party_resolver.helpers import (
    BASE_URL,
    collection,
    ctx_decline,
    ctx_never_elicit,
    resource,
)

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


async def _connect_user(db: DatabaseFixture, subject: str, username: str, api_token: str) -> bytes:
    _, factory = db
    key = os.urandom(32)

    async def _noop_revoke(_subject: str) -> None:
        return None

    auth_context.configure(
        auth_context.BackstopAuthContext(
            session_factory=factory,
            encryption_key=key,
            revoke_tokens_for_subject=_noop_revoke,
        )
    )
    async with factory() as session:
        await save_credential(
            session,
            subject,
            BackstopCredentialSecret(username=username, api_token=SecretStr(api_token)),
            key,
        )
        await session.commit()
    return key


def _fake_access_token(subject: str) -> AccessToken:
    return AccessToken(token="access-token", client_id="client-1", scopes=[], subject=subject)


class TestGetOrganization:
    @pytest.mark.asyncio
    @respx.mock
    async def test_unique_search_fetches_organization_and_echoes_resolved(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _connect_user(db, "user-org-1", "org-bob.smith", "token-1")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: _fake_access_token("user-org-1"),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", BASE_URL)

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(resource("o42", "organizations", name="Capstone")),
            )
        )
        org_body = {
            "data": {
                "type": "organizations",
                "id": "o42",
                "attributes": {"name": "Capstone", "status": "active"},
            }
        }
        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(200, json=org_body)
        )

        result = await get_organization(ctx_never_elicit(), search="Capstone")

        assert isinstance(result, OrganizationResolvedResponse)
        assert result.organization == org_body
        assert result.resolved == ResolvedPartyEcho(id="o42", type="organizations", name="Capstone")

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_search_returns_candidates_without_org_get(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _connect_user(db, "user-org-2", "org-carol.diaz", "token-2")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: _fake_access_token("user-org-2"),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", BASE_URL)

        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json=collection(
                    resource("o1", "organizations", name="Capstone A"),
                    resource("o2", "organizations", name="Capstone B"),
                ),
            )
        )
        org_get = respx.get(url__regex=rf"{BASE_URL}/organizations/\w+").mock(
            return_value=httpx.Response(200, json={})
        )

        result = await get_organization(ctx_decline(), search="Capstone")

        assert result == NeedsDisambiguationResponse(
            search="Capstone",
            search_type="organizations",
            candidates=[
                CandidateEcho(id="o1", name="Capstone A", label="Capstone A"),
                CandidateEcho(id="o2", name="Capstone B", label="Capstone B"),
            ],
        )
        assert org_get.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_trusted_party_id_fetches_organization(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _connect_user(db, "user-org-3", "org-dave.lee", "token-3")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: _fake_access_token("user-org-3"),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", BASE_URL)

        org_body = {
            "data": {
                "type": "organizations",
                "id": "trusted-9",
                "attributes": {"name": "From Body"},
            }
        }
        respx.get(f"{BASE_URL}/organizations/trusted-9").mock(
            return_value=httpx.Response(200, json=org_body)
        )
        quick = respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json=collection())
        )

        result = await get_organization(ctx_never_elicit(), party_id="trusted-9")

        assert isinstance(result, OrganizationResolvedResponse)
        assert result.resolved == ResolvedPartyEcho(
            id="trusted-9", type="organizations", name="From Body"
        )
        assert quick.call_count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_organization_body_raises_schema_error(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _connect_user(db, "user-org-4", "org-erin.ng", "token-4")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: _fake_access_token("user-org-4"),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", BASE_URL)

        # `id` is entirely absent from the organization resource — fails
        # `BackstopApiDocument[OrganizationAttributes]` schema validation outright.
        respx.get(f"{BASE_URL}/organizations/trusted-9").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"type": "organizations", "attributes": {"name": "From Body"}}},
            )
        )

        with pytest.raises(BackstopResponseSchemaError) as exc_info:
            await get_organization(ctx_never_elicit(), party_id="trusted-9")

        assert exc_info.value.path == "/organizations/trusted-9"
        assert exc_info.value.schema_name == "BackstopApiDocument[OrganizationAttributes]"
