"""Credential encryption: the round trip, and the trap that would store a placeholder."""

import json
from typing import cast

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from with_intelligence_mcp.config import EncryptionConfig
from with_intelligence_mcp.features.auth import InvalidCredentialEnvelopeError, load_key
from with_intelligence_mcp.features.auth.crypto import decrypt_credential, encrypt_credential
from with_intelligence_mcp.with_intelligence_client import VendorCredential

CREDENTIAL = VendorCredential(username="ir@example.invalid", password=SecretStr("s3cret-pw"))


class TestRoundTrip:
    def test_encrypt_then_decrypt_returns_the_credential(self) -> None:
        key = Fernet.generate_key()
        restored = decrypt_credential(encrypt_credential(CREDENTIAL, key), key)
        assert restored.username == CREDENTIAL.username
        assert restored.password.get_secret_value() == "s3cret-pw"

    def test_the_real_password_is_encrypted_not_the_redacted_placeholder(self) -> None:
        """`SecretStr` serializes to "**********" — using it in the payload would store that."""
        key = Fernet.generate_key()
        plaintext = Fernet(key).decrypt(encrypt_credential(CREDENTIAL, key))
        payload = cast("dict[str, str]", json.loads(plaintext))
        assert payload["password"] == "s3cret-pw"
        assert "*" not in payload["password"]

    def test_the_blob_does_not_contain_the_password_in_clear(self) -> None:
        key = Fernet.generate_key()
        assert b"s3cret-pw" not in encrypt_credential(CREDENTIAL, key)


class TestRejection:
    def test_a_blob_encrypted_with_another_key_is_refused(self) -> None:
        blob = encrypt_credential(CREDENTIAL, Fernet.generate_key())
        with pytest.raises(InvalidCredentialEnvelopeError):
            decrypt_credential(blob, Fernet.generate_key())

    def test_a_tampered_blob_is_refused(self) -> None:
        key = Fernet.generate_key()
        blob = bytearray(encrypt_credential(CREDENTIAL, key))
        blob[-1] ^= 0x01
        with pytest.raises(InvalidCredentialEnvelopeError):
            decrypt_credential(bytes(blob), key)

    def test_a_wrong_shaped_payload_is_refused(self) -> None:
        key = Fernet.generate_key()
        blob = Fernet(key).encrypt(b'{"username": "u"}')
        with pytest.raises(InvalidCredentialEnvelopeError):
            decrypt_credential(blob, key)


class TestLoadKey:
    def test_accepts_a_fernet_key(self) -> None:
        generated = Fernet.generate_key().decode()
        config = EncryptionConfig.model_validate({"encryption_key": generated})
        assert load_key(config) == generated.encode("ascii")

    def test_rejects_a_string_that_is_not_a_fernet_key(self) -> None:
        config = EncryptionConfig.model_validate({"encryption_key": "not-a-key"})
        with pytest.raises(ValueError, match="WITH_INTELLIGENCE_MCP_ENCRYPTION_KEY"):
            load_key(config)

    def test_an_unset_key_fails_at_config_time(self) -> None:
        with pytest.raises(ValueError, match="WITH_INTELLIGENCE_MCP_ENCRYPTION_KEY not set"):
            EncryptionConfig()
