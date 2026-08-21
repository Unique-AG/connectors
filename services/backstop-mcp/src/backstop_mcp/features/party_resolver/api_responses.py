from typing import Annotated, ClassVar

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

__all__ = [
    "PartyAttributes",
]


_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]
# Blank/whitespace inputs become `None` via `field_validator` on `PartyResolveItemDto` — putting
# a BeforeValidator that returns `None` on `Annotated[str, ...]` alone fails union matching.
_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PartyAttributes(BaseModel):
    """Shape of a party resource's `attributes` in `search.py`'s JSON:API responses.

    Deserialized straight off the wire via `BackstopApiCollectionDocument[PartyAttributes]` /
    `BackstopApiResourceDocument[PartyAttributes]` — see `backstop_client.json_api`.
    `extra="ignore"` since only `id`/`name`/`label` (derived here) ever leave `search.py`.
    Names are stripped here so `search.py`'s display-name fallback can use plain truthiness
    checks instead of re-stripping at point of use.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: _StrippedStr | None = None
    first_name: _StrippedStr | None = Field(
        default=None, validation_alias=AliasChoices("firstName", "first_name")
    )
    last_name: _StrippedStr | None = Field(
        default=None, validation_alias=AliasChoices("lastName", "last_name")
    )
    # Quick-search's `id` comes back prefixed (`organizations_341208613`), unusable against
    # `/organizations/{id}`; `resourceId` is the real id. Other party endpoints don't send this
    # attribute, so it's optional and `search.py` falls back to stripping the `id` prefix.
    # `_NonEmptyStr` (not `_StrippedStr`) so a blank/whitespace-only value can't bind to `""` and
    # slip past `search.py`'s `is not None` check — that would return `""` as the id instead of
    # falling through to the prefix-strip fallback. Needs the same blank→None coercion as
    # `PartyResolveItemDto` since `_NonEmptyStr` alone rejects (rather than coerces) blank input.
    resource_id: _NonEmptyStr | None = Field(
        default=None, validation_alias=AliasChoices("resourceId", "resource_id")
    )

    @field_validator("resource_id", mode="before")
    @classmethod
    def _blank_resource_id_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def display_name(self) -> str | None:
        if self.name:
            return self.name
        composed = " ".join(part for part in (self.first_name, self.last_name) if part)
        return composed or None
