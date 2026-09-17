"""`create_organization`: POST one organization."""

import logging
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.org_people_writes import (
    CREATE_ORGANIZATION_INPUT_DESCRIPTION,
    CreatedOrganizationResponse,
    CreateOrganizationCommand,
    CreateOrganizationInput,
    get_create_organization_command_factory,
)
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(CreatedOrganizationResponse),
)
async def create_organization(
    organization: Annotated[
        CreateOrganizationInput, Field(description=CREATE_ORGANIZATION_INPUT_DESCRIPTION)
    ],
    create_organization_command: CreateOrganizationCommand = Depends(
        get_create_organization_command_factory
    ),
) -> CreatedOrganizationResponse:
    """Create one CRM organization.

    `name` is required and at most 50 characters. A repeated call creates a second
    record. Custom fields go through `update_custom_field_values`. Category ids come
    from `list_contact_categories`. To change an existing organization, use
    `update_organization`. `destructive_hint` is true because this writes a new CRM
    record.

    Call like: {"organization": {"name": "Acme Advisors",
    "category_ids": ["<id from list_contact_categories>"]}}
    """
    logger.info("org_people_writes.create_organization.start")
    return await create_organization_command.run(organization=organization)
