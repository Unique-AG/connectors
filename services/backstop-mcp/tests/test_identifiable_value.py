import hashlib
import json

import pytest

from backstop_mcp.utils import (
    IdentifiableValue,
    LogsDiagnosticDataPolicy,
    identifiable_value,
    is_disclosure_active,
)


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


class TestIdentifiableValue:
    def test_value_is_always_the_original(self) -> None:
        concealed = IdentifiableValue("mlucas", conceal=True)
        disclosed = IdentifiableValue("mlucas", conceal=False)

        assert concealed.value == "mlucas"
        assert disclosed.value == "mlucas"

    def test_logs_the_sha256_when_concealed(self) -> None:
        wrapped = IdentifiableValue("mlucas", conceal=True)

        assert str(wrapped) == _digest("mlucas")
        assert repr(wrapped) == _digest("mlucas")
        assert "mlucas" not in str(wrapped)
        assert "mlucas" not in repr(wrapped)

    def test_logs_the_original_when_disclosed(self) -> None:
        wrapped = IdentifiableValue("mlucas", conceal=False)

        assert str(wrapped) == "mlucas"
        assert repr(wrapped) == "mlucas"

    def test_same_value_is_stable_across_instances(self) -> None:
        first = IdentifiableValue("mlucas", conceal=True)
        second = IdentifiableValue("mlucas", conceal=True)

        assert str(first) == str(second)

    def test_pino_json_default_str_does_not_leak_the_value(self) -> None:
        wrapped = IdentifiableValue("mlucas", conceal=True)

        payload = json.dumps({"login": wrapped}, default=str)

        assert "mlucas" not in payload
        assert _digest("mlucas") in payload


class TestIdentifiableValueFactory:
    def test_conceals_when_the_policy_is_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOGS_DIAGNOSTICS_DATA_POLICY", raising=False)

        wrapped = identifiable_value("mlucas")

        assert is_disclosure_active() is False
        assert wrapped.conceal is True
        assert str(wrapped) == _digest("mlucas")

    def test_conceals_when_the_policy_is_conceal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "LOGS_DIAGNOSTICS_DATA_POLICY", LogsDiagnosticDataPolicy.CONCEAL
        )

        wrapped = identifiable_value("mlucas")

        assert wrapped.conceal is True
        assert str(wrapped) == _digest("mlucas")

    def test_discloses_when_the_policy_is_disclose(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "LOGS_DIAGNOSTICS_DATA_POLICY", LogsDiagnosticDataPolicy.DISCLOSE
        )

        wrapped = identifiable_value("mlucas")

        assert is_disclosure_active() is True
        assert wrapped.conceal is False
        assert str(wrapped) == "mlucas"

    def test_unknown_policy_conceals(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOGS_DIAGNOSTICS_DATA_POLICY", "invalid-value")

        wrapped = identifiable_value("mlucas")

        assert is_disclosure_active() is False
        assert wrapped.conceal is True
        assert str(wrapped) == _digest("mlucas")
