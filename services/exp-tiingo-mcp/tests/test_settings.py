from typing import Any

import pytest
from pydantic import SecretStr

from tiingo_mcp.settings import Settings

SIGNING_KEY = "k" * 32
ZITADEL_IDENTITY = {
    "zitadel_issuer_url": "https://issuer.example.com",
    "zitadel_client_id": "client",
}
PROD_URL = {"mcp_base_url": "https://tiingo.example.com"}
ZITADEL = ZITADEL_IDENTITY | {"mcp_jwt_signing_key": SIGNING_KEY}


def build(**overrides: Any) -> Settings:  # noqa: ANN401
    return Settings(_env_file=None, tiingo_api_key=SecretStr("k"), **overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"mcp_auth_mode": "none"},
        {"mcp_auth_mode": "none", "mcp_base_url": "https://tunnel.example.com"},
        {"mcp_auth_mode": "zitadel", **ZITADEL},
        {"mcp_auth_mode": "zitadel", "mcp_base_url": "https://tiingo.example.com", **ZITADEL},
    ],
    ids=["none-local", "none-behind-https-tunnel", "zitadel-local", "zitadel-remote"],
)
def test_accepted_configurations(overrides: dict[str, Any]) -> None:
    build(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"mcp_auth_mode": "none", "python_env": "production"},
        {"mcp_auth_mode": "none", "host": "0.0.0.0"},
        {"mcp_auth_mode": "none", "mcp_base_url": "http://example.com"},
        {"mcp_auth_mode": "zitadel", "python_env": "production", **ZITADEL},
        {"mcp_auth_mode": "none", "mcp_base_url": "http://localhost:8741/mcp"},
        {"mcp_auth_mode": "none", "mcp_base_url": "http://user:pw@localhost:8741"},
        {"mcp_auth_mode": "zitadel"},
        {"mcp_auth_mode": "zitadel", **ZITADEL_IDENTITY},
        {
            "mcp_auth_mode": "zitadel",
            "mcp_base_url": "https://tiingo.example.com",
            **ZITADEL_IDENTITY,
        },
    ],
    ids=[
        "none-in-production",
        "none-on-public-bind",
        "none-with-remote-http",
        "production-without-https",
        "base-url-with-path",
        "base-url-with-credentials",
        "zitadel-without-settings",
        "zitadel-without-signing-key",
        "remote-zitadel-without-signing-key",
    ],
)
def test_rejected_configurations(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        build(**overrides)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "http://127.0.0.1:8741"),
        ({"port": 9000}, "http://127.0.0.1:9000"),
        ({"host": "::1"}, "http://[::1]:8741"),
        ({"mcp_base_url": "https://tunnel.example.com"}, "https://tunnel.example.com"),
    ],
)
def test_base_url_defaults_to_host_and_port(overrides: dict[str, Any], expected: str) -> None:
    assert build(mcp_auth_mode="none", **overrides).base_url == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"mcp_auth_mode": "none"}, ["localhost", "127.0.0.1"]),
        (
            {"mcp_auth_mode": "none", "mcp_base_url": "http://localhost:8741"},
            ["localhost", "127.0.0.1"],
        ),
        (
            {"mcp_auth_mode": "zitadel", "mcp_base_url": "https://tiingo.example.com", **ZITADEL},
            ["tiingo.example.com"],
        ),
    ],
    ids=["default", "localhost", "remote"],
)
def test_allowed_hosts(overrides: dict[str, Any], expected: list[str]) -> None:
    assert build(**overrides).allowed_hosts == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"tiingo_timeout_seconds": 0},
        {"tiingo_timeout_seconds": 121},
        {"tiingo_api_url": "http://api.tiingo.com"},
        {"mcp_auth_mode": "basic"},
        {"mcp_auth_mode": "zitadel", "mcp_jwt_signing_key": "short", **ZITADEL_IDENTITY},
    ],
    ids=["timeout-zero", "timeout-too-long", "tiingo-over-http", "unknown-auth-mode", "short-key"],
)
def test_invalid_values_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        build(**{"mcp_auth_mode": "none"} | overrides)


def test_signing_key_is_not_printed() -> None:
    assert SIGNING_KEY not in repr(build(mcp_auth_mode="zitadel", **ZITADEL))


@pytest.mark.parametrize(
    ("python_env", "expected"),
    [("development", ["http://localhost:6274/"]), ("production", [])],
)
def test_allowed_origins_default_to_the_inspector_only_in_development(
    python_env: str, expected: list[str]
) -> None:
    settings = build(mcp_auth_mode="zitadel", python_env=python_env, **ZITADEL | PROD_URL)
    assert [str(origin) for origin in settings.mcp_allowed_origins] == expected


def test_log_level_is_validated() -> None:
    assert build(mcp_auth_mode="none", log_level="DEBUG").log_level == "DEBUG"
    with pytest.raises(ValueError):
        build(mcp_auth_mode="none", log_level="LOUD")
