from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, SecretStr, ValidationError

from with_intelligence_mcp.config import EncryptionConfig
from with_intelligence_mcp.with_intelligence_client import VendorCredential


class InvalidCredentialEnvelopeError(ValueError):
    """Raised when a stored credential blob is malformed, tampered with, or wrong-keyed."""


class _CredentialPayload(BaseModel):
    """The JSON shape encrypted inside a credential blob.

    Plain `str`, not `SecretStr`: this is the payload actually encrypted, and pydantic's
    `SecretStr` serializes to the literal "**********" via `model_dump_json()` — using it here
    would encrypt the redacted placeholder instead of the real password.
    """

    username: str
    password: str


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


def encrypt_credential(credential: VendorCredential, key: bytes) -> bytes:
    """Encrypt a vendor credential for storage with Fernet (AES-128-CBC + HMAC)."""
    plaintext = (
        _CredentialPayload(
            username=credential.username, password=credential.password.get_secret_value()
        )
        .model_dump_json()
        .encode("utf-8")
    )
    return Fernet(key).encrypt(plaintext)


def decrypt_credential(blob: bytes, key: bytes) -> VendorCredential:
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

    return VendorCredential(username=payload.username, password=SecretStr(payload.password))
