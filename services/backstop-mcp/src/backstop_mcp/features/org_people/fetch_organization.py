"""Fetch one organization record by id, with optional side-loaded includes."""

from collections.abc import Sequence
from typing import ClassVar
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResourceDocument, BackstopClient
from backstop_mcp.features.includes import (
    OrganizationInclude,
    OrganizationIncludesResponse,
    include_plan,
)
from backstop_mcp.features.org_people.responses import OrganizationRecordResponse


class _OrganizationFetch(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    organization: OrganizationRecordResponse
    included: OrganizationIncludesResponse | None = None


async def fetch_organization(
    client: BackstopClient,
    *,
    party_id: str,
    include: Sequence[OrganizationInclude] = (),
) -> _OrganizationFetch:
    """One organization's record and any requested side-loads."""
    path = f"/organizations/{quote(party_id, safe='')}"
    plan = include_plan(OrganizationIncludesResponse, requested=include)
    document = await client.get(
        path,
        params={"include": plan.param} if plan.param else None,
        schema=BackstopApiResourceDocument[OrganizationRecordResponse],
    )
    organization = document.require_data(path=path).attributes
    return _OrganizationFetch(
        organization=organization,
        included=plan.project(document=document) if plan.planned else None,
    )
