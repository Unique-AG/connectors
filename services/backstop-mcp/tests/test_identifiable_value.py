import hashlib
import hmac
import json

import pytest

from backstop_mcp.observability import span_attributes
from backstop_mcp.utils import (
    IdentifiableValue,
    LogsDiagnosticDataPolicy,
    PseudonymMode,
    configure_identifiable_values,
    identifiable_value,
    is_disclosure_active,
)

_ENCRYPTION_KEY = b"encryption-key-material"
_LABEL = b"backstop-mcp/log-pseudonyms/v1"


def _plain(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _derived(encryption_key: bytes) -> bytes:
    return hmac.new(encryption_key, _LABEL, hashlib.sha256).digest()


def _keyed(value: str, key: bytes) -> str:
    digest = hmac.new(key, value.encode(), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


class TestIdentifiableValue:
    def test_value_is_always_the_original(self) -> None:
        concealed = IdentifiableValue("mlucas", mode=PseudonymMode.PLAIN)
        disclosed = IdentifiableValue("mlucas", mode=PseudonymMode.DISCLOSE)

        assert concealed.value == "mlucas"
        assert disclosed.value == "mlucas"

    def test_keyed_prints_hmac_sha256_and_depends_on_the_key(self) -> None:
        first_key = b"one-key"
        second_key = b"another-key"
        first = IdentifiableValue("mlucas", mode=PseudonymMode.KEYED, key=first_key)
        again = IdentifiableValue("mlucas", mode=PseudonymMode.KEYED, key=first_key)
        other = IdentifiableValue("mlucas", mode=PseudonymMode.KEYED, key=second_key)

        assert str(first) == _keyed("mlucas", first_key)
        assert str(first) == str(again)
        assert str(first) != str(other)
        assert str(first).startswith("hmac-sha256:")
        assert len(str(first).removeprefix("hmac-sha256:")) == 64
        assert "mlucas" not in str(first)

    def test_keyed_output_differs_from_the_plain_sha256(self) -> None:
        wrapped = IdentifiableValue("mlucas", mode=PseudonymMode.KEYED, key=_ENCRYPTION_KEY)

        assert str(wrapped) != _plain("mlucas")

    def test_plain_prints_sha256(self) -> None:
        wrapped = IdentifiableValue("mlucas", mode=PseudonymMode.PLAIN)

        assert str(wrapped) == _plain("mlucas")
        assert repr(wrapped) == _plain("mlucas")
        assert "mlucas" not in str(wrapped)

    def test_disclose_prints_the_value(self) -> None:
        wrapped = IdentifiableValue("mlucas", mode=PseudonymMode.DISCLOSE)

        assert str(wrapped) == "mlucas"
        assert repr(wrapped) == "mlucas"

    def test_pino_json_and_span_attributes_carry_the_pseudonym(self) -> None:
        wrapped = IdentifiableValue("mlucas", mode=PseudonymMode.KEYED, key=_ENCRYPTION_KEY)

        payload = json.dumps({"login": wrapped}, default=str)
        attributes = span_attributes({"login": wrapped})

        assert "mlucas" not in payload
        assert _keyed("mlucas", _ENCRYPTION_KEY) in payload
        assert attributes["login"] == _keyed("mlucas", _ENCRYPTION_KEY)


class TestConfigureIdentifiableValues:
    @pytest.mark.parametrize("log_level", ["debug", "info", "warning"])
    def test_disclose_wins_over_every_level(self, log_level: str) -> None:
        configure_identifiable_values(
            policy=LogsDiagnosticDataPolicy.DISCLOSE,
            log_level=log_level,
            encryption_key=_ENCRYPTION_KEY,
        )

        assert is_disclosure_active() is True
        assert str(identifiable_value("mlucas")) == "mlucas"

    def test_debug_is_plain_when_concealed(self) -> None:
        configure_identifiable_values(
            policy=LogsDiagnosticDataPolicy.CONCEAL,
            log_level="debug",
            encryption_key=_ENCRYPTION_KEY,
        )

        assert is_disclosure_active() is False
        assert str(identifiable_value("mlucas")) == _plain("mlucas")

    def test_info_is_keyed(self) -> None:
        configure_identifiable_values(
            policy=LogsDiagnosticDataPolicy.CONCEAL,
            log_level="info",
            encryption_key=_ENCRYPTION_KEY,
        )

        assert str(identifiable_value("mlucas")) == _keyed("mlucas", _derived(_ENCRYPTION_KEY))

    def test_the_derived_key_is_not_the_encryption_key(self) -> None:
        derived = _derived(_ENCRYPTION_KEY)

        assert derived != _ENCRYPTION_KEY
        direct = hmac.new(_ENCRYPTION_KEY, b"mlucas", hashlib.sha256).hexdigest()
        configure_identifiable_values(
            policy=LogsDiagnosticDataPolicy.CONCEAL,
            log_level="info",
            encryption_key=_ENCRYPTION_KEY,
        )
        assert str(identifiable_value("mlucas")) != f"hmac-sha256:{direct}"

    def test_unconfigured_falls_back_to_plain(self) -> None:
        wrapped = identifiable_value("mlucas")

        assert is_disclosure_active() is False
        assert str(wrapped) == _plain("mlucas")
