import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from mcp_credential_auth import load_fernet_key


def test_loads_a_valid_key() -> None:
    key = Fernet.generate_key()

    assert load_fernet_key(SecretStr(key.decode()), setting_name="AUTH_KEY") == key


@pytest.mark.parametrize("value", [None, SecretStr("invalid"), SecretStr("é" * 32)])
def test_rejects_an_invalid_key(value: SecretStr | None) -> None:
    with pytest.raises((AssertionError, ValueError), match="AUTH_KEY"):
        load_fernet_key(value, setting_name="AUTH_KEY")
