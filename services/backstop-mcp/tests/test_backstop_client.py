import base64

import pytest

from backstop_mcp.backstop_client import (
    MissingBackstopCredentialsError,
    create_backstop_client,
    extract_backstop_auth_headers,
)

_BASIC_AUTH = "Basic " + base64.b64encode(b"bob.smith:p@55W0rd321!").decode()


def test_extract_backstop_auth_headers_passes_through_password_auth() -> None:
    headers = extract_backstop_auth_headers({"authorization": _BASIC_AUTH})

    assert headers == {"authorization": _BASIC_AUTH}


def test_extract_backstop_auth_headers_passes_through_token_auth() -> None:
    headers = extract_backstop_auth_headers({"authorization": _BASIC_AUTH, "token": "true"})

    assert headers == {"authorization": _BASIC_AUTH, "token": "true"}


def test_extract_backstop_auth_headers_ignores_unrelated_headers() -> None:
    headers = extract_backstop_auth_headers(
        {"authorization": _BASIC_AUTH, "user-agent": "some-mcp-client"}
    )

    assert headers == {"authorization": _BASIC_AUTH}


def test_extract_backstop_auth_headers_requires_authorization_header() -> None:
    with pytest.raises(MissingBackstopCredentialsError):
        extract_backstop_auth_headers({})


def test_extract_backstop_auth_headers_rejects_non_basic_authorization() -> None:
    with pytest.raises(MissingBackstopCredentialsError):
        extract_backstop_auth_headers({"authorization": "Bearer sometoken"})


def test_create_backstop_client_forwards_headers_and_base_url() -> None:
    base_url = "https://example.backstopsolutions.com"
    client = create_backstop_client(base_url, {"authorization": _BASIC_AUTH})

    assert client.headers["authorization"] == _BASIC_AUTH
    assert str(client.base_url) == base_url
