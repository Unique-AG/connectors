from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.lenient import LenientBool

__all__ = ["SystemUserAttributes"]


class SystemUserAttributes(BaseModel):
    """Wire shape for `system-users` attributes (subset we publish).

    Every field is optional because `client.paginate` deserializes a whole page in one pass: a
    required field would fail the entire catalog fetch over one malformed row.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str | None = None
    user_name: str | None = Field(default=None, alias="userName")
    email: str | None = None
    phone: str | None = Field(default=None, alias="phoneNumber")
    disabled: LenientBool = None
