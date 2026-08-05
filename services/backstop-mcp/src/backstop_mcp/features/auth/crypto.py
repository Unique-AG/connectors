import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, SecretStr, ValidationError

from backstop_mcp.backstop_client import BackstopCredentialSecret
from backstop_mcp.config import EncryptionConfig

_NONCE_SIZE = 12
_ENVELOPE_VERSION = b"\x01"
_KEY_SIZE = 32


class InvalidCredentialEnvelopeError(ValueError):
    """Raised when a stored credential blob is malformed, tampered with, or wrong-keyed."""


class _CredentialPayload(BaseModel):
    """The JSON shape encrypted inside a credential blob (see `encrypt_credential`).

    Plain `str`, not `SecretStr`: this is the payload we actually encrypt, and pydantic's
    `SecretStr` serializes to the literal string "**********" via `model_dump_json()` — using
    it here would mean encrypting the redacted placeholder instead of the real token.
    """

    username: str
    api_token: str


def load_key(config: EncryptionConfig) -> bytes:
    assert config.encryption_key is not None, "EncryptionConfig validates this is set"
    key = base64.b64decode(config.encryption_key.get_secret_value())
    if len(key) != _KEY_SIZE:
        raise ValueError(
            f"BACKSTOP_MCP_ENCRYPTION_KEY must decode to {_KEY_SIZE} bytes (AES-256), got "
            + str(len(key))
        )
    return key


def encrypt_credential(credential: BackstopCredentialSecret, key: bytes) -> bytes:
    """Encrypt a Backstop credential for storage.

    Envelope: version byte || 12-byte nonce || AES-256-GCM ciphertext+tag over the
    credential serialized as JSON. A fresh random nonce is used every call.
    """
    plaintext = (
        _CredentialPayload(
            username=credential.username, api_token=credential.api_token.get_secret_value()
        )
        .model_dump_json()
        .encode("utf-8")
    )
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return _ENVELOPE_VERSION + nonce + ciphertext


def decrypt_credential(blob: bytes, key: bytes) -> BackstopCredentialSecret:
    """Decrypt a credential blob previously produced by `encrypt_credential`."""
    if len(blob) < len(_ENVELOPE_VERSION) + _NONCE_SIZE:
        raise InvalidCredentialEnvelopeError("Credential blob is too short to be valid")

    version = blob[: len(_ENVELOPE_VERSION)]
    if version != _ENVELOPE_VERSION:
        raise InvalidCredentialEnvelopeError(
            f"Unsupported credential envelope version: {version!r}"
        )

    nonce = blob[len(_ENVELOPE_VERSION) : len(_ENVELOPE_VERSION) + _NONCE_SIZE]
    ciphertext = blob[len(_ENVELOPE_VERSION) + _NONCE_SIZE :]

    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise InvalidCredentialEnvelopeError(
            "Credential blob failed authentication — wrong key or tampered data"
        ) from exc

    try:
        payload = _CredentialPayload.model_validate_json(plaintext)
    except ValidationError as exc:
        raise InvalidCredentialEnvelopeError(
            "Decrypted credential payload has an unexpected shape"
        ) from exc

    return BackstopCredentialSecret(
        username=payload.username, api_token=SecretStr(payload.api_token)
    )
