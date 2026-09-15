from cryptography.fernet import Fernet, InvalidToken
from mcp_credential_auth import load_fernet_key
from pydantic import BaseModel, SecretStr, ValidationError

from backstop_mcp.backstop_client import BackstopCredentialSecret
from backstop_mcp.config import EncryptionConfig


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
    """Load and validate a Fernet key from `BACKSTOP_MCP_ENCRYPTION_KEY`.

    The env value must be a Fernet key: url-safe base64 encoding of 32 bytes. Generate with
    `Fernet.generate_key()`.
    """
    return load_fernet_key(config.encryption_key, setting_name="BACKSTOP_MCP_ENCRYPTION_KEY")


def encrypt_credential(credential: BackstopCredentialSecret, key: bytes) -> bytes:
    """Encrypt a Backstop credential for storage with Fernet (AES-128-CBC + HMAC)."""
    plaintext = (
        _CredentialPayload(
            username=credential.username, api_token=credential.api_token.get_secret_value()
        )
        .model_dump_json()
        .encode("utf-8")
    )
    return Fernet(key).encrypt(plaintext)


def decrypt_credential(blob: bytes, key: bytes) -> BackstopCredentialSecret:
    """Decrypt a credential blob previously produced by `encrypt_credential`."""
    try:
        plaintext = Fernet(key).decrypt(blob)
    except InvalidToken as exc:
        raise InvalidCredentialEnvelopeError(
            "Credential blob failed authentication — wrong key, tampered, or malformed data"
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
