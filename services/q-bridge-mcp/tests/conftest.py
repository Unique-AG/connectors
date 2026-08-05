import os


def set_default_environment(name: str, value: str) -> None:
    if name not in os.environ:
        os.environ[name] = value


set_default_environment("MCP_BASE_URL", "http://localhost:8000")
set_default_environment(
    "MCP_JWT_SIGNING_KEY",
    "test-signing-key-with-at-least-32-characters",
)
set_default_environment(
    "STORAGE_ENCRYPTION_KEY",
    "o6CHCcv2631fJfq5W-i4wfrHAMLl0bDuFGVYWoH2r-A=",
)
set_default_environment("ZITADEL_ISSUER_URL", "https://zitadel.example.com")
set_default_environment("ZITADEL_CLIENT_ID", "test-client-id")
set_default_environment("ZITADEL_CLIENT_SECRET", "test-client-secret")
