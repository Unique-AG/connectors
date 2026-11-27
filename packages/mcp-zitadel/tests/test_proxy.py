import httpx2
import pytest
from fastmcp.server.auth import StaticTokenVerifier
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from key_value.aio.stores.memory import MemoryStore
from mcp_configs import ZitadelSettings
from pydantic import AnyHttpUrl
from pydantic import SecretStr

from mcp_zitadel import IdTokenVerifier
from mcp_zitadel import create_zitadel_oidc_proxy

_ORG_SCOPE = "urn:zitadel:iam:org:id:org-1"
_ORG_CLAIM = "urn:zitadel:iam:user:resourceowner:id"
_IDENTITY = ["openid", "profile", "urn:zitadel:iam:user:resourceowner"]
_TOKENS: dict[str, dict[str, object]] = {
    "match": {"client_id": "client", "scopes": [], "sub": "user-a", _ORG_CLAIM: "org-1"},
    "other": {"client_id": "client", "scopes": [], "sub": "user-b", _ORG_CLAIM: "org-2"},
    "none": {"client_id": "client", "scopes": [], "sub": "user-c"},
}


def _zitadel(
    issuer: str,
    *,
    org_id: str | None = None,
    signing_key: str = "k" * 32,
    client_secret: str | None = None,
) -> ZitadelSettings:
    return ZitadelSettings(
        base_url=AnyHttpUrl(issuer),
        client_id="mcp",
        client_secret=None if client_secret is None else SecretStr(client_secret),
        jwt_signing_key=SecretStr(signing_key),
        org_id=org_id,
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


@pytest.fixture
def zitadel_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def get(url: str, **_: object) -> httpx2.Response:
        issuer = url.removesuffix("/.well-known/openid-configuration")
        configuration = {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/v2/authorize",
            "token_endpoint": f"{issuer}/oauth/v2/token",
            "jwks_uri": f"{issuer}/oauth/v2/keys",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        return httpx2.Response(200, json=configuration, request=httpx2.Request("GET", url))

    monkeypatch.setattr(httpx2, "get", get)


@pytest.mark.usefixtures("zitadel_discovery")
def test_identity_scopes_are_required_and_offline_access_is_registrable_but_not_required() -> None:
    auth = create_zitadel_oidc_proxy(
        zitadel=_zitadel("https://zitadel.example.com"),
        base_url="http://127.0.0.1:8000",
        client_storage=MemoryStore(),
    )

    assert isinstance(auth, OIDCProxy)
    assert auth.required_scopes == _IDENTITY
    registration = auth.client_registration_options
    assert registration is not None
    valid = registration.valid_scopes or []
    asked = auth._extra_authorize_params["scope"].split()
    assert "offline_access" in valid
    assert "offline_access" in asked
    assert "offline_access" not in (auth.required_scopes or [])
    assert "mcp:tools" in valid
    assert isinstance(auth._token_validator, IdTokenVerifier)
    assert auth._token_validator._org_id is None


@pytest.mark.usefixtures("zitadel_discovery")
def test_an_org_id_is_asked_for_and_checked_and_a_client_cannot_register_it() -> None:
    auth = create_zitadel_oidc_proxy(
        zitadel=_zitadel("https://org.zitadel.example.com", org_id="org-1"),
        base_url="http://127.0.0.1:8000",
        client_storage=MemoryStore(),
    )

    registration = auth.client_registration_options
    assert registration is not None
    assert _ORG_SCOPE not in (auth.required_scopes or [])
    assert _ORG_SCOPE not in (registration.valid_scopes or [])
    assert _ORG_SCOPE in auth._extra_authorize_params["scope"].split()
    assert isinstance(auth._token_validator, IdTokenVerifier)
    assert auth._token_validator._org_id == "org-1"


@pytest.mark.usefixtures("zitadel_discovery")
@pytest.mark.parametrize("client_secret", [None, ""])
def test_a_missing_or_empty_client_secret_is_a_public_client(client_secret: str | None) -> None:
    auth = create_zitadel_oidc_proxy(
        zitadel=_zitadel("https://public.zitadel.example.com", client_secret=client_secret),
        base_url="http://127.0.0.1:8000",
        client_storage=MemoryStore(),
    )

    assert auth._token_endpoint_auth_method == "none"


@pytest.mark.usefixtures("zitadel_discovery")
def test_a_client_secret_is_sent_with_client_secret_post() -> None:
    auth = create_zitadel_oidc_proxy(
        zitadel=_zitadel("https://secret.zitadel.example.com", client_secret="s3cret"),
        base_url="http://127.0.0.1:8000",
        client_storage=MemoryStore(),
    )

    assert auth._token_endpoint_auth_method == "client_secret_post"


@pytest.mark.usefixtures("zitadel_discovery")
async def test_a_salt_encrypts_the_store_and_a_new_signing_key_cannot_read_it() -> None:
    at_rest = MemoryStore()
    issuer = "https://store.zitadel.example.com"
    auth = create_zitadel_oidc_proxy(
        zitadel=_zitadel(issuer),
        base_url="http://127.0.0.1:8000",
        client_storage=at_rest,
        encryption_salt="service-sign-in",
    )
    rotated = create_zitadel_oidc_proxy(
        zitadel=_zitadel(issuer, signing_key="r" * 32),
        base_url="http://127.0.0.1:8000",
        client_storage=at_rest,
        encryption_salt="service-sign-in",
    )

    await auth._client_storage.put("client-1", {"token": "plain-token"}, collection="clients")

    stored = await at_rest.get("client-1", collection="clients")
    assert stored is not None
    assert "plain-token" not in str(stored)
    assert await auth._client_storage.get("client-1", collection="clients") == {
        "token": "plain-token"
    }
    assert await rotated._client_storage.get("client-1", collection="clients") is None


@pytest.mark.usefixtures("zitadel_discovery")
async def test_without_a_salt_the_store_keeps_the_value_it_was_given() -> None:
    at_rest = MemoryStore()
    auth = create_zitadel_oidc_proxy(
        zitadel=_zitadel("https://plain.zitadel.example.com"),
        base_url="http://127.0.0.1:8000",
        client_storage=at_rest,
    )

    await auth._client_storage.put("client-1", {"token": "plain-token"}, collection="clients")

    assert await at_rest.get("client-1", collection="clients") == {"token": "plain-token"}


def _verifier(org_id: str | None) -> IdTokenVerifier:
    return IdTokenVerifier(StaticTokenVerifier(tokens=_TOKENS), org_id=org_id, required_scopes=[])


async def test_an_org_check_accepts_only_that_org() -> None:
    verifier = _verifier("org-1")

    assert await verifier.verify_token("match") is not None
    assert await verifier.verify_token("other") is None
    assert await verifier.verify_token("none") is None
    assert await verifier.verify_token("unknown") is None


async def test_without_an_org_id_a_token_needs_no_org_claim() -> None:
    verifier = _verifier(None)

    assert await verifier.verify_token("none") is not None
