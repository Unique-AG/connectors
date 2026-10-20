import pytest
from pydantic import SecretStr, ValidationError

from mcp_runtime import (
    DiagnosticsDataPolicy,
    ElicitationSettings,
    LoggingSettings,
    LogLevel,
    RedisSettings,
    RetrySettings,
    Toggle,
    ZitadelSettings,
)

SIGNING_KEY = "k" * 32


def test_logging_defaults_to_info_and_conceals_diagnostics() -> None:
    settings = LoggingSettings()

    assert settings.log_level is LogLevel.INFO
    assert settings.diagnostics_data_policy is DiagnosticsDataPolicy.CONCEAL
    assert not settings.discloses_diagnostics


def test_logging_reads_the_lowercase_level_the_charts_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("LOGS_DIAGNOSTICS_DATA_POLICY", "disclose")

    settings = LoggingSettings()

    assert settings.log_level is LogLevel.DEBUG
    assert settings.discloses_diagnostics


def test_logging_rejects_an_unknown_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "verbose")

    with pytest.raises(ValidationError):
        LoggingSettings()


def test_retry_defaults_match_the_openapi_client() -> None:
    settings = RetrySettings()

    assert (settings.max_attempts, settings.max_wait_seconds) == (5, 30)
    assert settings.statuses == frozenset({429, 503})


def test_retry_takes_another_prefix_for_a_second_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILLING_RETRY_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("UPSTREAM_RETRY_MAX_ATTEMPTS", "9")

    assert RetrySettings(_env_prefix="BILLING_RETRY_").max_attempts == 2  # pyright: ignore[reportCallIssue]


def test_redis_reads_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    assert RedisSettings().url.get_secret_value() == "redis://localhost:6379/0"  # pyright: ignore[reportCallIssue]


def test_redis_requires_a_url() -> None:
    with pytest.raises(ValidationError):
        RedisSettings()  # pyright: ignore[reportCallIssue]


def test_redis_ignores_a_url_without_its_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL", "redis://elsewhere:6379/0")

    with pytest.raises(ValidationError):
        RedisSettings()  # pyright: ignore[reportCallIssue]


def test_elicitation_asks_for_everything_by_default() -> None:
    settings = ElicitationSettings()

    assert settings.for_disambiguation is Toggle.ENABLED
    assert settings.for_data_modification is Toggle.ENABLED
    assert settings.for_data_removal is Toggle.ENABLED
    assert settings.timeout_before_cancel_seconds == 120


def test_elicitation_reads_each_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELICITATION_FOR_DATA_MODIFICATION", "Disabled")
    monkeypatch.setenv("ELICITATION_TIMEOUT_BEFORE_CANCEL_SECONDS", "45")

    settings = ElicitationSettings()

    assert settings.for_data_modification is Toggle.DISABLED
    assert settings.for_data_removal is Toggle.ENABLED
    assert settings.timeout_before_cancel_seconds == 45


def test_elicitation_rejects_a_toggle_that_is_not_enabled_or_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELICITATION_FOR_DATA_REMOVAL", "sometimes")

    with pytest.raises(ValidationError):
        ElicitationSettings()


def test_zitadel_derives_the_issuer_and_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZITADEL_BASE_URL", "https://auth.example.com/")
    monkeypatch.setenv("ZITADEL_CLIENT_ID", "client")
    monkeypatch.setenv("ZITADEL_JWT_SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setenv("ZITADEL_ORG_ID", "42")

    settings = ZitadelSettings()  # pyright: ignore[reportCallIssue]

    assert settings.issuer == "https://auth.example.com"
    assert settings.config_url == "https://auth.example.com/.well-known/openid-configuration"
    assert settings.client_secret is None
    assert settings.required_scopes == [
        "openid",
        "profile",
        "urn:zitadel:iam:user:resourceowner",
        "urn:zitadel:iam:org:id:42",
    ]


def test_zitadel_requires_https_outside_localhost() -> None:
    with pytest.raises(ValidationError, match="must use https"):
        ZitadelSettings(
            base_url="http://auth.example.com",  # pyright: ignore[reportArgumentType]
            client_id="client",
            jwt_signing_key=SecretStr(SIGNING_KEY),
        )


def test_zitadel_allows_http_on_localhost() -> None:
    settings = ZitadelSettings(
        base_url="http://localhost:8080",  # pyright: ignore[reportArgumentType]
        client_id="client",
        jwt_signing_key=SecretStr(SIGNING_KEY),
    )

    assert settings.issuer == "http://localhost:8080"


def test_zitadel_rejects_a_short_signing_key() -> None:
    with pytest.raises(ValidationError):
        ZitadelSettings(
            base_url="https://auth.example.com",  # pyright: ignore[reportArgumentType]
            client_id="client",
            jwt_signing_key=SecretStr("short"),
        )
