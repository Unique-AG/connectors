"""The vendor's person shapes, from the v3 schemas.

A person's roles span every organisation they have worked at, so the role that matters has to
be picked by organisation rather than assumed to be the first.
"""

from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from with_intelligence_mcp.features.investors import ClassificationAttributes
from with_intelligence_mcp.with_intelligence_client import SEQUENCE


class RoleOrganisationAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int | None = None
    org_entity_id: int | None = None
    name: str | None = None
    org_type: str | None = None


class PersonRoleAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    organisation: RoleOrganisationAttributes | None = None
    seniority: ClassificationAttributes | None = None
    specialisms: ClassificationAttributes | None = None
    job_title: str | None = None
    role_name: str | None = None
    main_for_organisation: bool | None = None
    main_for_person: bool | None = None
    primary_email: str | None = None
    primary_phone: str | None = None
    office_phone: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class PersonListItemAttributes(BaseModel):
    """What `/v3/persons` returns — and unlike the investor record's `contacts`, it has names."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    updated_at: str | None = None


class PersonExtendedAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: int
    name: str | None = None
    full_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    biography: str | None = None
    linked_in_url: str | None = None
    updated_at: str | None = None
    person_roles: Annotated[list[PersonRoleAttributes], SEQUENCE] = Field(default_factory=list)
