import uuid
from hashlib import sha256

_TRANSACTION_NAMESPACE = uuid.UUID("eb6f3437-0196-4593-b4d7-a6044db0acdf")


def confirmation_id_for(target: str, *fields: str) -> str:
    return str(uuid.uuid5(_TRANSACTION_NAMESPACE, _canonical(target, *fields)))


def write_state_for(*parts: str) -> str:
    return sha256("\x1f".join(parts).encode()).hexdigest()


def _canonical(*fields: str) -> str:
    return "".join(f"{len(field)}:{field}" for field in fields)
