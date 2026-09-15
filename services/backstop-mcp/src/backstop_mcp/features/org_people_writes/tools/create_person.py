"""`create_person`: POST one person."""

import logging
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.org_people_writes import (
    CREATE_PERSON_INPUT_DESCRIPTION,
    CreatedPersonResponse,
    CreatePersonCommand,
    CreatePersonInput,
    get_create_person_command_factory,
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
    output_schema=published_output_schema(CreatedPersonResponse),
)
async def create_person(
    person: Annotated[CreatePersonInput, Field(description=CREATE_PERSON_INPUT_DESCRIPTION)],
    create_person_command: CreatePersonCommand = Depends(get_create_person_command_factory),
) -> CreatedPersonResponse:
    """Create one CRM person.

    `last_name` and `gender` are required. A repeated call creates a second record.
    `job_title` is at most 140 characters. Custom fields go through
    `update_custom_field_values`. To change an existing person, use `update_person`.
    `destructive_hint` is true because this writes a new CRM record.

    Call like: {"person": {"last_name": "Smith", "gender": "Female",
    "category_ids": ["<contact-category id>"]}}
    """
    logger.info("org_people_writes.create_person.start")
    return await create_person_command.run(person=person)
