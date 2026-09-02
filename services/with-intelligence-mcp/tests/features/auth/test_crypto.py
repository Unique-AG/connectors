"""Session encryption: the round trip, and the trap that would store a placeholder."""

import json
from datetime import UTC, datetime
from typing import cast

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from with_intelligence_mcp.config import EncryptionConfig
from with_intelligence_mcp.features.auth import InvalidSessionEnvelopeError, load_key
from with_intelligence_mcp.features.auth.crypto import decrypt_session, encrypt_session
from with_intelligence_mcp.with_intelligence_client import VendorSession

SESSION = VendorSession(
    access_token=SecretStr("wi-access-token"),
    refresh_token=SecretStr("wi-refresh-token"),
    issued_at=datetime.now(UTC),
)


class TestRoundTrip:
    def test_encrypt_then_decrypt_returns_the_session(self) -> None:
        key = Fernet.generate_key()
        restored = decrypt_session(encrypt_session(SESSION, key), key)
        assert restored.access_token.get_secret_value() == "wi-access-token"
        assert restored.refresh_token.get_secret_value() == "wi-refresh-token"

    def test_the_real_tokens_are_encrypted_not_the_redacted_placeholder(self) -> None:
        """`SecretStr` serializes to "**********" — using it in the payload would store that."""
        key = Fernet.generate_key()
        plaintext = Fernet(key).decrypt(encrypt_session(SESSION, key))
        payload = cast("dict[str, str]", json.loads(plaintext))
        assert payload["refresh_token"] == "wi-refresh-token"
        assert "*" not in payload["access_token"]

    def test_the_blob_does_not_contain_a_token_in_clear(self) -> None:
        key = Fernet.generate_key()
        blob = encrypt_session(SESSION, key)
        assert b"wi-refresh-token" not in blob
        assert b"wi-access-token" not in blob

    def test_freshness_survives_the_round_trip(self) -> None:
        """`issued_at` is ours, not the vendor's, and is what `is_fresh` reads."""
        key = Fernet.generate_key()
        restored = decrypt_session(encrypt_session(SESSION, key), key)
        assert restored.is_fresh is True


class TestRejection:
    def test_a_blob_encrypted_with_another_key_is_refused(self) -> None:
        blob = encrypt_session(SESSION, Fernet.generate_key())
        with pytest.raises(InvalidSessionEnvelopeError):
            decrypt_session(blob, Fernet.generate_key())

    def test_a_tampered_blob_is_refused(self) -> None:
        key = Fernet.generate_key()
        blob = bytearray(encrypt_session(SESSION, key))
        blob[-1] ^= 0x01
        with pytest.raises(InvalidSessionEnvelopeError):
            decrypt_session(bytes(blob), key)

    def test_a_wrong_shaped_payload_is_refused(self) -> None:
        key = Fernet.generate_key()
        blob = Fernet(key).encrypt(b'{"access_token": "a"}')
        with pytest.raises(InvalidSessionEnvelopeError):
            decrypt_session(blob, key)


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
