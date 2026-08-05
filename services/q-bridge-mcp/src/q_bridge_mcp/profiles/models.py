from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserProfile(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    skills_root_folder: str | None = Field(
        default=None,
        alias="skillsRootFolder",
        max_length=255,
    )

    @field_validator("skills_root_folder")
    @classmethod
    def validate_skills_root_folder(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized_value = value.strip()
        folder_name = normalized_value.removeprefix("/")
        if (
            not folder_name
            or folder_name in {".", ".."}
            or "/" in folder_name
            or "\\" in folder_name
        ):
            raise ValueError("skillsRootFolder must be a folder name")

        return normalized_value


class OrganizationCredentials(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(populate_by_name=True)

    app_id: str = Field(alias="appId", min_length=1, max_length=255)
    api_key: str = Field(alias="apiKey", min_length=1, repr=False)
    configured_by: str = Field(alias="configuredBy", min_length=1)
    updated_at: datetime = Field(alias="updatedAt")

    @field_validator("app_id", "api_key")
    @classmethod
    def strip_credential_value(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("credential values must not be empty")
        return normalized_value

    @property
    def api_key_hint(self) -> str:
        return f"…{self.api_key[-4:]}"
