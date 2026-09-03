from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, SecretStr, ValidationError

from with_intelligence_mcp.config import EncryptionConfig
from with_intelligence_mcp.with_intelligence_client import VendorSession


class InvalidSessionEnvelopeError(ValueError):
    """Raised when a stored session blob is malformed, tampered with, or wrong-keyed."""


class _SessionPayload(BaseModel):
    """The JSON shape encrypted inside a session blob.

    Plain `str`, not `SecretStr`: this is the payload actually encrypted, and pydantic's
    `SecretStr` serializes to the literal "**********" via `model_dump_json()` — using it here
    would encrypt the redacted placeholder instead of the real token.
    """

    access_token: str
    refresh_token: str
    issued_at: datetime


def load_key(config: EncryptionConfig) -> bytes:
    """Load and validate the Fernet key: url-safe base64 encoding of 32 bytes."""
    assert config.encryption_key is not None, "EncryptionConfig validates this is set"
    key = config.encryption_key.get_secret_value().encode("ascii")
    try:
        Fernet(key)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "WITH_INTELLIGENCE_MCP_ENCRYPTION_KEY must be a Fernet key "
            + "(url-safe base64-encoded 32-byte key); generate with: "
            + 'python -c "from cryptography.fernet import Fernet; '
            + 'print(Fernet.generate_key().decode())"'
        ) from exc
    return key


def encrypt_session(session: VendorSession, key: bytes) -> bytes:
    """Encrypt a vendor session for storage with Fernet (AES-128-CBC + HMAC)."""
    plaintext = (
        _SessionPayload(
            access_token=session.access_token.get_secret_value(),
            refresh_token=session.refresh_token.get_secret_value(),
            issued_at=session.issued_at,
        )
        .model_dump_json()
        .encode("utf-8")
    )
    return Fernet(key).encrypt(plaintext)


def decrypt_session(blob: bytes, key: bytes) -> VendorSession:
    """Decrypt a session blob previously produced by `encrypt_session`."""
    try:
        plaintext = Fernet(key).decrypt(blob)
    except InvalidToken as exc:
        raise InvalidSessionEnvelopeError(
            "Session blob failed authentication — wrong key, tampered, or malformed data"
        ) from exc

    try:
        payload = _SessionPayload.model_validate_json(plaintext)
    except ValidationError as exc:
        raise InvalidSessionEnvelopeError(
            "Decrypted session payload has an unexpected shape"
        ) from exc

    return VendorSession(
        access_token=SecretStr(payload.access_token),
        refresh_token=SecretStr(payload.refresh_token),
        issued_at=payload.issued_at,
    )
