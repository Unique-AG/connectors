"""Write-side wire shapes for person, organization, and contact-location PATCH/POST."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.lenient import LenientStr

__all__ = [
    "ContactLocationAttributes",
    "OrganizationWriteAttributes",
    "PersonWriteAttributes",
]


class PersonWriteAttributes(BaseModel):
    """Person attributes we re-read after a write. Phone is rewritten server-side."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: LenientStr = None
    mobile_phone: LenientStr = Field(default=None, validation_alias="mobilePhone")


class OrganizationWriteAttributes(BaseModel):
    """Organization attributes we re-read after a PATCH."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: LenientStr = None


class ContactLocationAttributes(BaseModel):
    """A `contact-locations` resource. Derived resolved-name fields are ignored."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    location_title: LenientStr = Field(default=None, validation_alias="locationTitle")
    phone_number: LenientStr = Field(default=None, validation_alias="phoneNumber")
