"""Fetch one person record by collection and id, with employment links and optional includes."""

from collections.abc import Sequence
from typing import ClassVar
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResourceDocument, BackstopClient
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    EmploymentLinkResponse,
    EntityRelationshipInclude,
    project_entity_relationships,
)
from backstop_mcp.features.includes import PersonInclude, PersonIncludesResponse, include_plan
from backstop_mcp.features.org_people.responses import PersonRecordResponse


class _PersonFetch(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    person: PersonRecordResponse
    employments: list[EmploymentLinkResponse]
    included: PersonIncludesResponse | None = None


async def fetch_person(
    client: BackstopClient,
    factory: EmploymentIndexFactory,
    *,
    search_type: str,
    party_id: str,
    include: Sequence[PersonInclude] = (),
) -> _PersonFetch:
    """One person's record, employment links, and any requested side-loads."""
    # Quick-search for people uses the shared PERSON_* types, so a hit may be a
    # contact/employee; follow `party.search_type` instead of hard-coding `/people`.
    path = f"/{search_type}/{quote(party_id, safe='')}"
    plan = include_plan(PersonIncludesResponse, requested=include)
    # `plan.param` is empty when nothing was requested, so join only the non-empty parts.
    include_param = ",".join(
        part for part in (EntityRelationshipInclude.for_employment(), plan.param) if part
    )
    document = await client.get(
        path,
        params={"include": include_param} if include_param else None,
        schema=BackstopApiResourceDocument[PersonRecordResponse],
    )
    person = document.require_data(path=path).attributes
    loaded = project_entity_relationships(document)
    index = factory.index(
        relationships=loaded.relationships,
        relationship_types=loaded.relationship_types,
    )
    return _PersonFetch(
        person=person,
        employments=index.links(),
        included=plan.project(document=document) if plan.planned else None,
    )
