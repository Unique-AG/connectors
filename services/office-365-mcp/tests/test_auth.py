import base64
import json
import time
from collections.abc import Iterator, Mapping

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

import office_365_mcp.auth as auth_module
from office_365_mcp.auth import (
    OrganizationsAzureProvider,
    TenantBoundJWTVerifier,
    build_auth,
    build_oauth_storage,
    home_tenant,
    tenant_issuer,
)
from office_365_mcp.config import ORGANIZATIONS, DatabaseConfig, EntraConfig

_DATABASE_URL = "postgresql://user:pass@db:5432/office"

_GRAPH_SCOPES = ("https://graph.microsoft.com/User.Read",)

_TENANT_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_ANOTHER_TENANT_ID = "0f1e2d3c-4b5a-4697-8899-aabbccddeeff"
_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"


def _entra_config(tenant_id: str = _TENANT_ID) -> EntraConfig:
    return EntraConfig.model_validate(
        {"tenant_id": tenant_id, "client_id": _CLIENT_ID, "client_secret": "s3cr3t"}
    )


def _database_config(url: str = _DATABASE_URL) -> DatabaseConfig:
    return DatabaseConfig.model_validate({"url": url})


class TestOAuthStorage:
    def test_state_is_encrypted_and_kept_in_postgres_not_on_the_pod(self) -> None:
        """FastMCP's default store is a file tree under the *process's* home directory, which no
        pod outlives and no two replicas share, and FastMCP encrypts it — a bare table would turn
        at-rest encryption off while looking like configuration. Decryption errors count as misses,
        so rotating the client secret costs each user one re-login rather than every request."""
        storage = build_oauth_storage(_entra_config(), _database_config())

        assert isinstance(storage, FernetEncryptionWrapper)
        assert isinstance(storage.key_value, PostgreSQLStore)
        assert storage.raise_on_decryption_error is False

    def test_the_store_gets_the_driver_dsn_not_the_configured_url(self) -> None:
        """The store hands this string to asyncpg itself, and neither a `postgresql+asyncpg://`
        scheme nor `sslmode=verify` fails until the first user logs in."""
        database = _database_config(f"{_DATABASE_URL}?sslmode=verify")
        storage = build_oauth_storage(_entra_config(), database)

        assert isinstance(storage, FernetEncryptionWrapper)
        store = storage.key_value
        assert isinstance(store, PostgreSQLStore)
        assert store._url == "postgresql://user:pass@db:5432/office?sslmode=verify-full"  # pyright: ignore[reportPrivateUsage]


_BASE_URL = "https://office-365-mcp.example"


def _build_auth(entra: EntraConfig | None = None) -> AzureProvider:
    entra = entra or _entra_config()
    return build_auth(
        entra,
        base_url=_BASE_URL,
        client_storage=build_oauth_storage(entra, _database_config()),
        graph_scopes=_GRAPH_SCOPES,
    )


def _validator_of(provider: AzureProvider) -> JWTVerifier:
    validator = provider._token_validator  # pyright: ignore[reportPrivateUsage]
    assert isinstance(validator, JWTVerifier)
    return validator


class TestAuthProvider:
    def test_the_app_registration_comes_from_config(self) -> None:
        entra = _entra_config()

        provider = _build_auth(entra)

        assert provider.identifier_uri == f"api://{entra.client_id}"

    def test_the_server_gates_access_on_its_own_scope_not_a_graph_one(self) -> None:
        """Entra omits OIDC scopes from `scp`, so the provider needs a custom API scope to
        enforce. A Graph scope among the required ones is validated on every token and fails every
        request, because this API's tokens never carry Graph permissions."""
        provider = _build_auth()

        assert provider.required_scopes == ["access_as_user"]

    def test_the_graph_permissions_ride_the_authorize_request(self) -> None:
        """Without this, sign-in never asks for Graph consent and each tool's On-Behalf-Of
        exchange fails with AADSTS65001, per call, long after the sign-in that would have fixed it.
        Containment and not equality: the provider adds `offline_access` to this list itself."""
        provider = _build_auth()

        assert set(_GRAPH_SCOPES) <= set(provider.additional_authorize_scopes)
        assert not set(_GRAPH_SCOPES) & set(provider.required_scopes)

    def test_it_uses_the_exact_storage_it_was_given(self) -> None:
        """Identity and not just type: `create_app` hands the same object to the readiness probe,
        so a provider that copied its store leaves `/ready` proving a connection nothing uses."""
        storage = build_oauth_storage(_entra_config(), _database_config())

        provider = build_auth(
            _entra_config(),
            base_url=_BASE_URL,
            client_storage=storage,
            graph_scopes=_GRAPH_SCOPES,
        )

        assert provider._client_storage is storage  # pyright: ignore[reportPrivateUsage]


class TestWhichProviderATenantGets:
    def test_one_tenant_keeps_fastmcps_provider_untouched(self) -> None:
        provider = _build_auth(_entra_config(_TENANT_ID))

        assert type(provider) is AzureProvider
        validator = _validator_of(provider)
        assert not isinstance(validator, TenantBoundJWTVerifier)
        assert validator.issuer == tenant_issuer(_TENANT_ID)

    def test_organizations_gets_the_tenant_bound_provider(self) -> None:
        provider = _build_auth(_entra_config(ORGANIZATIONS))

        assert isinstance(provider, OrganizationsAzureProvider)
        validator = _validator_of(provider)
        assert isinstance(validator, TenantBoundJWTVerifier)
        assert validator.issuer is None
        assert validator.jwks_uri == (
            "https://login.microsoftonline.com/organizations/discovery/v2.0/keys"
        )
        assert validator.audience == [_CLIENT_ID, f"api://{_CLIENT_ID}"]
        assert validator.algorithm == "RS256"
        assert validator.required_scopes == ["access_as_user"]

    def test_sign_in_and_the_code_exchange_go_through_organizations(self) -> None:
        """Entra accepts the `organizations` literal only at the authorize and token endpoints."""
        provider = _build_auth(_entra_config(ORGANIZATIONS))

        assert provider._upstream_authorization_endpoint == (  # pyright: ignore[reportPrivateUsage]
            "https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize"
        )
        assert provider._upstream_token_endpoint == (  # pyright: ignore[reportPrivateUsage]
            "https://login.microsoftonline.com/organizations/oauth2/v2.0/token"
        )


class TestWhatBindsATokenToItsTenant:
    def test_a_token_whose_issuer_is_its_own_tenant_names_that_tenant(self) -> None:
        assert home_tenant({"tid": _TENANT_ID, "iss": tenant_issuer(_TENANT_ID)}) == _TENANT_ID

    @pytest.mark.parametrize(
        "claims",
        [
            pytest.param(
                {"tid": _TENANT_ID, "iss": tenant_issuer(_ANOTHER_TENANT_ID)}, id="iss-another"
            ),
            pytest.param(
                {"tid": _TENANT_ID, "iss": tenant_issuer(ORGANIZATIONS)}, id="iss-literal"
            ),
            pytest.param(
                {"tid": ORGANIZATIONS, "iss": tenant_issuer(ORGANIZATIONS)}, id="tid-literal"
            ),
            pytest.param(
                {"tid": "contoso.onmicrosoft.com", "iss": tenant_issuer("contoso.onmicrosoft.com")},
                id="tid-domain",
            ),
            pytest.param({"iss": tenant_issuer(_TENANT_ID)}, id="no-tid"),
            pytest.param({"tid": _TENANT_ID}, id="no-iss"),
            pytest.param(
                {"tid": _TENANT_ID, "iss": f"https://sts.windows.net/{_TENANT_ID}/"}, id="v1-issuer"
            ),
        ],
    )
    def test_anything_else_binds_no_tenant(self, claims: Mapping[str, object]) -> None:
        assert home_tenant(claims) is None


@pytest.fixture(scope="module")
def signing_key() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private_pem, public_pem


@pytest.fixture
def verifier(signing_key: tuple[str, str]) -> TenantBoundJWTVerifier:
    """Public key in hand rather than a JWKS URI, so nothing is fetched."""
    _, public_pem = signing_key
    stock = JWTVerifier(
        public_key=public_pem,
        audience=[_CLIENT_ID, f"api://{_CLIENT_ID}"],
        algorithm="RS256",
        required_scopes=["access_as_user"],
    )
    return TenantBoundJWTVerifier(stock)


_ABSENT = object()


def _entra_token(private_pem: str, **overrides: object) -> str:
    """A v2.0 Entra access token; a claim passed `_ABSENT` is left out."""
    claims: dict[str, object] = {
        "aud": _CLIENT_ID,
        "iss": tenant_issuer(_TENANT_ID),
        "tid": _TENANT_ID,
        "sub": "synthetic-subject",
        "scp": "access_as_user",
        "exp": int(time.time()) + 300,
    }
    for name, value in overrides.items():
        if value is _ABSENT:
            del claims[name]
        else:
            claims[name] = value
    return jwt.encode(claims, private_pem, algorithm="RS256")


class TestTenantBoundTokens:
    async def test_a_token_from_any_tenant_is_accepted_when_its_issuer_is_that_tenant(
        self, verifier: TenantBoundJWTVerifier, signing_key: tuple[str, str]
    ) -> None:
        private_pem, _ = signing_key

        for tenant_id in (_TENANT_ID, _ANOTHER_TENANT_ID):
            token = _entra_token(private_pem, tid=tenant_id, iss=tenant_issuer(tenant_id))

            accepted = await verifier.verify_token(token)

            assert accepted is not None, f"a token from tenant {tenant_id} was refused"
            assert accepted.claims["tid"] == tenant_id
            assert accepted.scopes == ["access_as_user"]

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"iss": tenant_issuer(_ANOTHER_TENANT_ID)}, id="another-tenants-issuer"),
            pytest.param({"iss": tenant_issuer(ORGANIZATIONS)}, id="the-organizations-literal"),
            pytest.param({"tid": "not-a-guid"}, id="tid-not-a-guid"),
            pytest.param({"tid": _ABSENT}, id="no-tid"),
        ],
    )
    async def test_a_signed_token_whose_issuer_does_not_vouch_for_its_tenant_is_refused(
        self,
        verifier: TenantBoundJWTVerifier,
        signing_key: tuple[str, str],
        overrides: dict[str, object],
    ) -> None:
        private_pem, _ = signing_key
        token = _entra_token(private_pem, **overrides)

        assert await verifier.verify_token(token) is None

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"aud": "another-app"}, id="another-apps-token"),
            pytest.param({"scp": "User.Read"}, id="without-this-apis-scope"),
            pytest.param({"exp": int(time.time()) - 60}, id="expired"),
        ],
    )
    async def test_the_stock_checks_still_run_first(
        self,
        verifier: TenantBoundJWTVerifier,
        signing_key: tuple[str, str],
        overrides: dict[str, object],
    ) -> None:
        private_pem, _ = signing_key
        token = _entra_token(private_pem, **overrides)

        assert await verifier.verify_token(token) is None

    async def test_a_token_signed_by_another_key_is_refused(
        self, verifier: TenantBoundJWTVerifier
    ) -> None:
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pem = other_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()

        assert await verifier.verify_token(_entra_token(other_pem)) is None


def _unsigned_jwt(claims: Mapping[str, object]) -> str:
    """Unsigned: the provider only exchanges tokens its verifier has already accepted."""

    def segment(value: object) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{segment({'alg': 'RS256'})}.{segment(claims)}.synthetic-signature"


class _RecordedCredential:
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        *,
        user_assertion: str,
        client_secret: str,
        authority: str,
    ) -> None:
        self.tenant_id: str = tenant_id
        self.client_id: str = client_id
        self.user_assertion: str = user_assertion
        self.client_secret: str = client_secret
        self.authority: str = authority
        self.closed: bool = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[_RecordedCredential]]:
    built: list[_RecordedCredential] = []

    def record(
        tenant_id: str,
        client_id: str,
        *,
        user_assertion: str,
        client_secret: str,
        authority: str,
    ) -> _RecordedCredential:
        credential = _RecordedCredential(
            tenant_id,
            client_id,
            user_assertion=user_assertion,
            client_secret=client_secret,
            authority=authority,
        )
        built.append(credential)
        return credential

    monkeypatch.setattr(auth_module, "OnBehalfOfCredential", record)
    yield built


def _assertion_from(tenant_id: str) -> str:
    return _unsigned_jwt({"tid": tenant_id, "iss": tenant_issuer(tenant_id), "sub": "somebody"})


class TestOnBehalfOfAgainstTheTokensOwnTenant:
    async def test_the_exchange_is_made_against_the_tenant_that_issued_the_token(
        self, credentials: list[_RecordedCredential]
    ) -> None:
        """Microsoft requires the OBO exchange to name the assertion's issuing tenant."""
        provider = _build_auth(_entra_config(ORGANIZATIONS))
        assertion = _assertion_from(_TENANT_ID)

        _ = await provider.get_obo_credential(user_assertion=assertion)

        assert len(credentials) == 1
        credential = credentials[0]
        assert credential.tenant_id == _TENANT_ID
        assert credential.authority == "https://login.microsoftonline.com"
        assert credential.client_id == _CLIENT_ID
        assert credential.client_secret == "s3cr3t"
        assert credential.user_assertion == assertion

    async def test_one_credential_per_token_as_the_stock_provider_keeps_it(
        self, credentials: list[_RecordedCredential]
    ) -> None:
        """The Azure SDK caches the Graph token inside the credential, so a second credential is a
        second exchange."""
        provider = _build_auth(_entra_config(ORGANIZATIONS))
        assertion = _assertion_from(_TENANT_ID)

        _ = await provider.get_obo_credential(user_assertion=assertion)
        _ = await provider.get_obo_credential(user_assertion=assertion)

        assert len(credentials) == 1

    async def test_two_tenants_get_two_credentials(
        self, credentials: list[_RecordedCredential]
    ) -> None:
        provider = _build_auth(_entra_config(ORGANIZATIONS))

        _ = await provider.get_obo_credential(user_assertion=_assertion_from(_TENANT_ID))
        _ = await provider.get_obo_credential(user_assertion=_assertion_from(_ANOTHER_TENANT_ID))

        assert [credential.tenant_id for credential in credentials] == [
            _TENANT_ID,
            _ANOTHER_TENANT_ID,
        ]

    async def test_the_oldest_credential_is_closed_when_the_cache_is_full(
        self, credentials: list[_RecordedCredential]
    ) -> None:
        provider = _build_auth(_entra_config(ORGANIZATIONS))
        provider._obo_max_credentials = 1  # pyright: ignore[reportPrivateUsage]

        _ = await provider.get_obo_credential(user_assertion=_assertion_from(_TENANT_ID))
        _ = await provider.get_obo_credential(user_assertion=_assertion_from(_ANOTHER_TENANT_ID))

        assert [credential.closed for credential in credentials] == [True, False]

    async def test_a_token_that_binds_no_tenant_is_never_exchanged(
        self, credentials: list[_RecordedCredential]
    ) -> None:
        """Unreachable through the verifier, hence an assertion rather than a handled error."""
        provider = _build_auth(_entra_config(ORGANIZATIONS))
        assertion = _unsigned_jwt({"tid": _TENANT_ID, "iss": tenant_issuer(ORGANIZATIONS)})

        with pytest.raises(AssertionError):
            _ = await provider.get_obo_credential(user_assertion=assertion)

        assert credentials == []
