from pydantic_settings import BaseSettings, SettingsConfigDict


def shared_config(env_prefix: str = "") -> SettingsConfigDict:
    """How every MCP's settings read the environment: a `.env` file under the real environment,
    unset when empty, unknown names ignored, and values kept out of validation errors."""
    return SettingsConfigDict(
        env_prefix=env_prefix,
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
        validate_by_name=True,
    )


def from_environment[S: BaseSettings](settings: type[S]) -> S:
    """`settings` read from the environment alone. Called directly, a class with a required field
    fails the type check, which cannot see that the environment gives the field."""
    return settings()
