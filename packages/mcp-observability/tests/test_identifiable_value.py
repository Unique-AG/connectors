import hashlib
import hmac
import json
from collections.abc import Iterator

import pytest
from mcp_configs import DiagnosticsDataPolicy
from mcp_configs import LoggingSettings
from mcp_configs import LogLevel

from mcp_observability import configure_identifiable_values
from mcp_observability import identifiable_value
from mcp_observability import reset_identifiable_values
from mcp_observability.identifiable_value import IdentifiableValue
from mcp_observability.identifiable_value import PseudonymMode

_SECRET = b"pseudonym-secret"
_LOGIN = "jdoe"


@pytest.fixture(autouse=True)
def unconfigured() -> Iterator[None]:
    yield
    reset_identifiable_values()


def _plain(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _keyed(value: str, key: bytes) -> str:
    return f"hmac-sha256:{hmac.new(key, value.encode(), hashlib.sha256).hexdigest()}"


def _settings(
    level: LogLevel, policy: DiagnosticsDataPolicy = DiagnosticsDataPolicy.CONCEAL
) -> LoggingSettings:
    return LoggingSettings(log_level=level, diagnostics_data_policy=policy)


class TestIdentifiableValue:
    def test_value_is_always_the_original(self) -> None:
        for mode in PseudonymMode:
            assert IdentifiableValue(_LOGIN, mode=mode, key=_SECRET).value == _LOGIN

    def test_keyed_prints_hmac_sha256_and_depends_on_the_key(self) -> None:
        first = IdentifiableValue(_LOGIN, mode=PseudonymMode.KEYED, key=_SECRET)
        again = IdentifiableValue(_LOGIN, mode=PseudonymMode.KEYED, key=_SECRET)
        other = IdentifiableValue(_LOGIN, mode=PseudonymMode.KEYED, key=b"another-secret")

        assert str(first) == _keyed(_LOGIN, _SECRET)
        assert str(first) == str(again)
        assert str(first) != str(other)
        assert str(first) != _plain(_LOGIN)

    def test_plain_prints_sha256(self) -> None:
        wrapped = IdentifiableValue(_LOGIN, mode=PseudonymMode.PLAIN)

        assert str(wrapped) == _plain(_LOGIN)
        assert repr(wrapped) == _plain(_LOGIN)

    def test_disclose_prints_the_value(self) -> None:
        wrapped = IdentifiableValue(_LOGIN, mode=PseudonymMode.DISCLOSE)

        assert str(wrapped) == _LOGIN
        assert repr(wrapped) == _LOGIN

    def test_pino_json_carries_the_pseudonym(self) -> None:
        wrapped = IdentifiableValue(_LOGIN, mode=PseudonymMode.KEYED, key=_SECRET)

        payload = json.dumps({"login": wrapped}, default=str)

        assert _LOGIN not in payload
        assert _keyed(_LOGIN, _SECRET) in payload


class TestConfigureIdentifiableValues:
    @pytest.mark.parametrize("level", [LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR])
    def test_info_and_above_is_keyed_with_the_secret(self, level: LogLevel) -> None:
        configure_identifiable_values(_settings(level), secret=_SECRET)

        assert str(identifiable_value(_LOGIN)) == _keyed(_LOGIN, _SECRET)

    def test_debug_is_plain(self) -> None:
        configure_identifiable_values(_settings(LogLevel.DEBUG), secret=_SECRET)

        assert str(identifiable_value(_LOGIN)) == _plain(_LOGIN)

    @pytest.mark.parametrize("level", [LogLevel.DEBUG, LogLevel.INFO])
    def test_disclose_wins_over_every_level(self, level: LogLevel) -> None:
        configure_identifiable_values(
            _settings(level, DiagnosticsDataPolicy.DISCLOSE), secret=_SECRET
        )

        assert str(identifiable_value(_LOGIN)) == _LOGIN

    def test_unconfigured_is_plain(self) -> None:
        assert str(identifiable_value(_LOGIN)) == _plain(_LOGIN)
