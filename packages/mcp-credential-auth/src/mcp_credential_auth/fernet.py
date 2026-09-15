from cryptography.fernet import Fernet
from pydantic import SecretStr


def load_fernet_key(value: SecretStr | None, *, setting_name: str) -> bytes:
    assert value is not None, f"{setting_name} must be configured"
    try:
        key = value.get_secret_value().encode("ascii")
        Fernet(key)
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ValueError(
            f"{setting_name} must be a Fernet key "
            + "(url-safe base64-encoded 32-byte key); generate with: "
            + 'python -c "from cryptography.fernet import Fernet; '
            + 'print(Fernet.generate_key().decode())"'
        ) from exc
    return key
