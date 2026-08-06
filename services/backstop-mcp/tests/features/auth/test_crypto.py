import base64
import os

import pytest
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
    return os.urandom(32)


class TestLoadKey:
    def test_decodes_base64_32_byte_key(self) -> None:
        raw_key = os.urandom(32)
        config = EncryptionConfig(encryption_key=SecretStr(base64.b64encode(raw_key).decode()))

        assert load_key(config) == raw_key

    def test_rejects_wrong_length_key(self) -> None:
        config = EncryptionConfig(
            encryption_key=SecretStr(base64.b64encode(os.urandom(16)).decode())
        )

        with pytest.raises(ValueError, match="32 bytes"):
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

    def test_nonce_is_unique_per_encryption(self) -> None:
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

    def test_rejects_unsupported_envelope_version(self) -> None:
        key = _random_key()
        credential = BackstopCredentialSecret(username="bob.smith", api_token=SecretStr("token"))
        blob = encrypt_credential(credential, key)
        tampered = b"\x99" + blob[1:]

        with pytest.raises(InvalidCredentialEnvelopeError, match="version"):
            decrypt_credential(tampered, key)

    def test_rejects_too_short_blob(self) -> None:
        with pytest.raises(InvalidCredentialEnvelopeError, match="too short"):
            decrypt_credential(b"\x01short", _random_key())
