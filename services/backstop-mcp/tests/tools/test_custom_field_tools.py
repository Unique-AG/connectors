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
from backstop_mcp.config import CustomFieldOverrideConfig
from backstop_mcp.custom_fields import (
    configure_custom_fields_service,
    create_custom_fields_service,
)
from backstop_mcp.party_resolver import ResolvedPartyEcho
from backstop_mcp.tools.get_organization_custom_field import (
    OrganizationCustomFieldResolvedResponse,
    get_organization_custom_field,
)
from backstop_mcp.tools.resolve_custom_field import (
    ResolveCustomFieldResolvedResponse,
    resolve_custom_field,
)
from tests.party_resolver.helpers import BASE_URL, ctx_never_elicit, resource

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


async def _connect_user(db: DatabaseFixture, subject: str, username: str, api_token: str) -> None:
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


def _fake_access_token(subject: str) -> AccessToken:
    return AccessToken(token="access-token", client_id="client-1", scopes=[], subject=subject)


def _configure_service(db: DatabaseFixture, *, base_url: str = BASE_URL) -> None:
    _, factory = db
    configure_custom_fields_service(
        create_custom_fields_service(
            session_factory=factory,
            base_url=base_url,
            overrides={
                "organizations:is1": CustomFieldOverrideConfig(
                    display_name="Investor Status",
                    aliases=["investor status"],
                )
            },
        )
    )


class TestResolveCustomFieldTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_resolves_with_refresh(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _connect_user(db, "user-cf-1", "cf-bob", "token-1")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: _fake_access_token("user-cf-1"),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", BASE_URL)
        _configure_service(db)

        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "99",
                            "custom-field-definitions",
                            name="is1",
                            entityType="Organization",
                            fieldType="picklist",
                            isTimeSeries=False,
                            selectOptions=[{"label": "Active"}],
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        result = await resolve_custom_field(
            entity_type="organizations", query="Investor Status", refresh=True
        )

        assert isinstance(result, ResolveCustomFieldResolvedResponse)
        assert result.definition.definition_id == "99"
        assert result.definition.display_name == "Investor Status"
        assert result.definition.allowed_values[0].label == "Active"


class TestGetOrganizationCustomFieldTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_reads_investor_status_for_capstone(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _connect_user(db, "user-cf-2", "cf-alice", "token-2")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: _fake_access_token("user-cf-2"),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", BASE_URL)
        _configure_service(db)

        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "99",
                            "custom-field-definitions",
                            name="is1",
                            entityType="Organization",
                            fieldType="picklist",
                            isTimeSeries=False,
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json={"data": [resource("o42", "organizations", name="Capstone")]},
            )
        )
        respx.get(f"{BASE_URL}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "organizations",
                        "id": "o42",
                        "attributes": {
                            "regularCustomFieldValues": [
                                {"definitionId": "99", "value": "Active LP"}
                            ]
                        },
                    }
                },
            )
        )

        result = await get_organization_custom_field(
            ctx_never_elicit(),
            field="Investor Status",
            search="Capstone",
        )

        assert isinstance(result, OrganizationCustomFieldResolvedResponse)
        assert result.value == "Active LP"
        assert result.definition.definition_id == "99"
        assert result.resolved == ResolvedPartyEcho(
            id="o42", type="organizations", name="Capstone"
        )
