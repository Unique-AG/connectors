import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from backstop_mcp.backstop_client.credential import BackstopCredentialSecret
from backstop_mcp.config import EncryptionConfig
from backstop_mcp.features.auth.crypto import (
    InvalidCredentialEnvelopeError,
    decrypt_credential,
    encrypt_credential,
    load_key,
)


def _random_key() -> bytes:
    return Fernet.generate_key()


class TestLoadKey:
    def test_accepts_fernet_key(self) -> None:
        key = Fernet.generate_key()
        config = EncryptionConfig(encryption_key=SecretStr(key.decode()))

        assert load_key(config) == key

    def test_rejects_non_fernet_key(self) -> None:
        config = EncryptionConfig(encryption_key=SecretStr("not-a-fernet-key"))

        with pytest.raises(ValueError, match="Fernet key"):
            load_key(config)


class TestEncryptDecryptRoundTrip:
    def test_round_trip_recovers_original_credential(self) -> None:
        key = _random_key()
        credential = BackstopCredentialSecret(
            username="bob.smith", api_token=SecretStr("p@55W0rd321!")
        )

        blob = encrypt_credential(credential, key)
        recovered = decrypt_credential(blob, key)

        assert recovered == credential
        assert recovered.api_token.get_secret_value() == "p@55W0rd321!"

    def test_api_token_is_redacted_in_repr(self) -> None:
        credential = BackstopCredentialSecret(
            username="bob.smith", api_token=SecretStr("p@55W0rd321!")
        )

        assert "p@55W0rd321!" not in repr(credential)
        assert "p@55W0rd321!" not in str(credential)

    def test_ciphertext_is_unique_per_encryption(self) -> None:
        key = _random_key()
        credential = BackstopCredentialSecret(username="bob.smith", api_token=SecretStr("token"))

        blob_a = encrypt_credential(credential, key)
        blob_b = encrypt_credential(credential, key)

        assert blob_a != blob_b


class TestTamperDetection:
    def test_rejects_ciphertext_tampering(self) -> None:
        key = _random_key()
        credential = BackstopCredentialSecret(username="bob.smith", api_token=SecretStr("token"))
        blob = bytearray(encrypt_credential(credential, key))
        blob[-1] ^= 0xFF

        with pytest.raises(InvalidCredentialEnvelopeError):
            decrypt_credential(bytes(blob), key)

    def test_rejects_wrong_key(self) -> None:
        credential = BackstopCredentialSecret(username="bob.smith", api_token=SecretStr("token"))
        blob = encrypt_credential(credential, _random_key())

        with pytest.raises(InvalidCredentialEnvelopeError):
            decrypt_credential(blob, _random_key())

    def test_rejects_malformed_blob(self) -> None:
        with pytest.raises(InvalidCredentialEnvelopeError):
            decrypt_credential(b"not-a-fernet-token", _random_key())
