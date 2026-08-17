"""`describe_data_model`: the entity documentation, rendered from the payload models themselves.

Every field description here is read off the pydantic model that tools return, so it cannot
drift from the payload. The include allowlist, the stage vocabulary, and which tool owns which
question are the three things a caller needs before reaching for the wrong tool.
"""

import re
from typing import ClassVar

from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.includes import (
    CompanyRefResponse,
    ContactCardResponse,
    ContactEmailResponse,
    ContactLocationResponse,
    InternalOwnerResponse,
    OrganizationIncludesResponse,
    PersonIncludesResponse,
)
from backstop_mcp.features.opportunities import (
    OpportunityResponse,
    OpportunityStage,
    StageChangeResponse,
)
from backstop_mcp.server.runtime import get_backstop_client, get_opportunity_stages_service


def _purpose(model: type[BaseModel]) -> str:
    """The model's first docstring paragraph, collapsed to one line."""
    doc = model.__doc__
    assert doc is not None, f"{model.__name__} has no docstring"
    paragraph = doc.strip().split("\n\n", 1)[0]
    return re.sub(r"\s+", " ", paragraph).strip()


def _fields(model: type[BaseModel]) -> tuple["DataModelField", ...]:
    return tuple(
        DataModelField(
            name=name,
            description=field.description or "",
        )
        for name, field in model.model_fields.items()
        if field.description
    )


class DataModelField(BaseModel):
    """One field of a returned entity, with the description published on the payload."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str = Field(description="Field name as it appears on the payload.")
    description: str = Field(
        description="What that field means, taken from the payload model itself."
    )


class DataModelEntity(BaseModel):
    """One returned entity: what it is, its fields, and which tool/include produces it."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str = Field(description="Entity name as this server publishes it.")
    purpose: str = Field(
        description="What this entity is, taken from the payload model's docstring."
    )
    fields: tuple[DataModelField, ...] = Field(description="Documented fields of this entity.")
    produced_by: tuple[str, ...] = Field(
        description=(
            "Which tool, and which `include` when relevant, returns this entity. "
            "e.g. 'get_organization include=locations'."
        )
    )


class StageVocabularyEntry(BaseModel):
    """One row of this instance's opportunity-stage vocabulary, in sort order."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of this stage.")
    name: str = Field(description="Stage name as this instance publishes it.")
    closed: bool = Field(description="True when this stage means the deal is closed.")
    sort_order: int | None = Field(
        default=None,
        description="Pipeline order of this stage. Omitted when the instance does not publish one.",
    )


class ToolOwnership(BaseModel):
    """Which tool answers which kind of question — so a caller does not reach for the wrong one."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    concern: str = Field(description="Kind of question this row answers.")
    tools: tuple[str, ...] = Field(description="Tools that answer that kind of question.")


class DescribeDataModelResponse(BaseModel):
    """The entities this server returns, the stage vocabulary, and which tool owns what."""

    entities: tuple[DataModelEntity, ...] = Field(
        description=(
            "The entities this server returns, with field descriptions taken from the "
            "payload models."
        )
    )
    stages: tuple[StageVocabularyEntry, ...] = Field(
        description="This instance's opportunity-stage vocabulary, Prospect through Closed."
    )
    ownership: tuple[ToolOwnership, ...] = Field(
        description="Which tool answers which kind of question."
    )


_OWNERSHIP: tuple[ToolOwnership, ...] = (
    ToolOwnership(concern="contact details", tools=("get_person", "get_organization")),
    ToolOwnership(
        concern="meetings, calls, notes, emails, documents",
        tools=("get_activity_history", "get_activity_detail"),
    ),
    ToolOwnership(concern="pipeline", tools=("get_opportunities",)),
    ToolOwnership(concern="custom field names", tools=("list_custom_fields",)),
)

_ENTITIES: tuple[DataModelEntity, ...] = (
    DataModelEntity(
        name="ContactLocation",
        purpose=_purpose(ContactLocationResponse),
        fields=_fields(ContactLocationResponse),
        produced_by=(
            "get_person include=locations",
            "get_organization include=locations",
        ),
    ),
    DataModelEntity(
        name="ContactEmail",
        purpose=_purpose(ContactEmailResponse),
        fields=_fields(ContactEmailResponse),
        produced_by=(
            "get_person include=email_addresses",
            "get_organization include=email_addresses",
        ),
    ),
    DataModelEntity(
        name="ContactCard",
        purpose=_purpose(ContactCardResponse),
        fields=_fields(ContactCardResponse),
        produced_by=("get_organization include=primary_contact",),
    ),
    DataModelEntity(
        name="CompanyRef",
        purpose=_purpose(CompanyRefResponse),
        fields=_fields(CompanyRefResponse),
        produced_by=("get_person include=company",),
    ),
    DataModelEntity(
        name="InternalOwner",
        purpose=_purpose(InternalOwnerResponse),
        fields=_fields(InternalOwnerResponse),
        produced_by=(
            "get_person include=representative",
            "get_organization include=representative",
        ),
    ),
    DataModelEntity(
        name="OrganizationIncludes",
        purpose=_purpose(OrganizationIncludesResponse),
        fields=_fields(OrganizationIncludesResponse),
        produced_by=("get_organization include=...",),
    ),
    DataModelEntity(
        name="PersonIncludes",
        purpose=_purpose(PersonIncludesResponse),
        fields=_fields(PersonIncludesResponse),
        produced_by=("get_person include=...",),
    ),
    DataModelEntity(
        name="Opportunity",
        purpose=_purpose(OpportunityResponse),
        fields=_fields(OpportunityResponse),
        produced_by=("get_opportunities",),
    ),
    DataModelEntity(
        name="StageChange",
        purpose=_purpose(StageChangeResponse),
        fields=_fields(StageChangeResponse),
        produced_by=("get_opportunities",),
    ),
)


def _stage_entries(vocabulary: dict[str, OpportunityStage]) -> tuple[StageVocabularyEntry, ...]:
    ordered = sorted(
        vocabulary.values(),
        key=lambda stage: (stage.sort_order is None, stage.sort_order or 0),
    )
    return tuple(
        StageVocabularyEntry(
            id=stage.id, name=stage.name, closed=stage.closed, sort_order=stage.sort_order
        )
        for stage in ordered
    )


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def describe_data_model() -> DescribeDataModelResponse:
    """Describe the entities this server returns: fields, include names, stages, tool ownership.

    Use this when you need to know what a field means, which `include` produces it, what the
    opportunity stages are, or which tool answers a question. Contact details come from
    `get_person` / `get_organization`; meetings, calls, notes, emails and documents from
    `get_activity_history`; pipeline from `get_opportunities`; custom-field names from
    `list_custom_fields`.
    """
    client = await get_backstop_client()
    vocabulary = await get_opportunity_stages_service().get(client)
    return DescribeDataModelResponse(
        entities=_ENTITIES,
        stages=_stage_entries(vocabulary),
        ownership=_OWNERSHIP,
    )
