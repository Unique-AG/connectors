from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from tiingo_mcp.auth import create_auth
from tiingo_mcp.settings import Settings

ISSUER = "https://issuer.example.com"
OIDC_CONFIG = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/oauth/v2/authorize",
    "token_endpoint": f"{ISSUER}/oauth/v2/token",
    "jwks_uri": f"{ISSUER}/oauth/v2/keys",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256"],
}


@pytest.fixture(autouse=True)
def zitadel_discovery(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    requested: list[str] = []

    def get(url: str, **_: Any) -> httpx2.Response:  # noqa: ANN401
        requested.append(url)
        return httpx2.Response(200, json=OIDC_CONFIG, request=httpx2.Request("GET", url))

    monkeypatch.setattr(httpx2, "get", get)
    return requested


def zitadel_settings(**overrides: Any) -> Settings:  # noqa: ANN401
    return Settings(
        _env_file=None,
        tiingo_api_key=SecretStr("k"),
        mcp_auth_mode="zitadel",
        zitadel_issuer_url=ISSUER,
        zitadel_client_id="client",
        mcp_jwt_signing_key="k" * 32,
        **overrides,
    )


def test_no_auth_in_none_mode() -> None:
    settings = Settings(_env_file=None, tiingo_api_key=SecretStr("k"), mcp_auth_mode="none")
    assert create_auth(settings) is None


def test_zitadel_proxy_discovers_the_issuer(zitadel_discovery: list[str]) -> None:
    auth = create_auth(zitadel_settings())
    assert auth is not None
    assert zitadel_discovery == [f"{ISSUER}/.well-known/openid-configuration"]
    assert auth.required_scopes == ["openid", "profile", "urn:zitadel:iam:user:resourceowner"]


def test_zitadel_proxy_is_a_public_client_even_if_a_secret_is_in_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZITADEL_CLIENT_SECRET", "from-the-environment")
    auth = create_auth(zitadel_settings())
    assert auth is not None
    assert auth._upstream_client_secret is None
    assert auth._token_endpoint_auth_method == "none"


def test_org_restriction_is_required_and_requested() -> None:
    auth = create_auth(zitadel_settings(zitadel_org_id="42"))
    assert auth is not None
    org_scope = "urn:zitadel:iam:org:id:42"
    assert org_scope in auth.required_scopes
    assert org_scope in auth._extra_authorize_params["scope"].split()
