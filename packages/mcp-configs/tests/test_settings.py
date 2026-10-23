from pathlib import Path

import pytest
from pydantic import AnyHttpUrl, SecretStr, ValidationError

from mcp_configs import (
    DiagnosticsDataPolicy,
    ElicitationSettings,
    LoggingSettings,
    LogLevel,
    RedisSettings,
    RetrySettings,
    ServerSettings,
    Toggle,
    TraceExporter,
    TracingSettings,
    ZitadelSettings,
    from_environment,
)

SIGNING_KEY = "k" * 32


@pytest.mark.parametrize(
    ("environment", "endpoint"),
    [
        (
            {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://c:4318/v1/traces"},
            "http://c:4318/v1/traces",
        ),
        ({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://c:4318/"}, "http://c:4318/v1/traces"),
        (
            {
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://traces:4318/t",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://c:4318",
            },
            "http://traces:4318/t",
        ),
        ({}, None),
    ],
    ids=["traces endpoint as given", "base endpoint with the traces path", "traces first", "none"],
)
def test_tracing_resolves_the_traces_endpoint_as_the_spec_does(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str], endpoint: str | None
) -> None:
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert TracingSettings().traces_endpoint == endpoint


def test_tracing_reads_an_endpoint_from_the_env_file() -> None:
    Path(".env").write_text("OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318\n")

    settings = TracingSettings()

    assert settings.exporter is TraceExporter.OTLP
    assert settings.traces_endpoint == "http://collector:4318/v1/traces"


@pytest.mark.parametrize("host", ["::1", "localhost"])
def test_server_settings_let_a_loopback_base_url_be_reached_by_any_loopback_name(
    host: str,
) -> None:
    settings = ServerSettings(host=host)

    assert set(settings.allowed_hosts) == {"localhost", "127.0.0.1", "[::1]"}


def test_tracing_is_off_unless_the_environment_turns_it_on() -> None:
    assert TracingSettings().exporter is TraceExporter.NONE


@pytest.mark.parametrize(
    ("environment", "exporter"),
    [
        ({"OTEL_TRACES_EXPORTER": "console"}, TraceExporter.CONSOLE),
        ({"OTEL_TRACES_EXPORTER": "none", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://c"}, None),
        ({"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://collector"}, TraceExporter.OTLP),
        ({"ENABLE_OPENTELEMETRY": "true"}, TraceExporter.OTLP),
        ({"ENABLE_OPENTELEMETRY": "true", "OTEL_SPAN_PROCESSOR": "console"}, TraceExporter.CONSOLE),
        ({"ENABLE_OPENTELEMETRY": "false", "OTEL_SPAN_PROCESSOR": "console"}, None),
    ],
)
def test_tracing_reads_the_standard_names_then_the_node_services_ones(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str], exporter: TraceExporter | None
) -> None:
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert TracingSettings().exporter is (exporter or TraceExporter.NONE)


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


def test_logging_reads_the_diagnostics_policy_in_any_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOGS_DIAGNOSTICS_DATA_POLICY", "DISCLOSE")

    assert LoggingSettings().discloses_diagnostics


def test_logging_rejects_an_unknown_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "verbose")

    with pytest.raises(ValidationError):
        LoggingSettings()


def test_retry_defaults_to_five_attempts_30_seconds_apart_on_429_and_503() -> None:
    settings = RetrySettings()

    assert (settings.max_attempts, settings.max_wait_seconds) == (5, 30)
    assert settings.statuses == frozenset({429, 503})


def test_retry_takes_another_prefix_for_a_second_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILLING_RETRY_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("UPSTREAM_RETRY_MAX_ATTEMPTS", "9")

    assert RetrySettings(_env_prefix="BILLING_RETRY_").max_attempts == 2  # pyright: ignore[reportCallIssue]


def test_redis_reads_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    url = from_environment(RedisSettings).url

    assert url.get_secret_value() == "redis://localhost:6379/0"


def test_redis_requires_a_url() -> None:
    with pytest.raises(ValidationError):
        from_environment(RedisSettings)


def test_redis_ignores_a_url_without_its_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URL", "redis://elsewhere:6379/0")

    with pytest.raises(ValidationError):
        from_environment(RedisSettings)


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

    settings = from_environment(ZitadelSettings)

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


def test_server_settings_default_to_a_local_origin_and_the_inspector() -> None:
    settings = ServerSettings()

    assert settings.base_url == "http://127.0.0.1:8000"
    assert settings.allowed_hosts == ["localhost", "127.0.0.1", "[::1]"]
    assert settings.allowed_origins == ["http://localhost:6274"]
    assert settings.binds_to_loopback


def test_server_settings_allow_only_the_public_host_when_deployed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_BASE_URL", "https://weather.example.com")

    settings = ServerSettings()

    assert settings.allowed_hosts == ["weather.example.com"]
    assert settings.allowed_origins == []
    assert not settings.binds_to_loopback


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_server_settings_know_a_loopback_host(host: str) -> None:
    assert ServerSettings(host=host).binds_to_loopback


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("https://weather.example.com/mcp", "bare origin"),
        ("http://weather.example.com", "requires HTTPS"),
    ],
)
def test_server_settings_reject_a_base_url_that_is_not_a_public_https_origin(
    url: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        ServerSettings(mcp_base_url=AnyHttpUrl(url))
