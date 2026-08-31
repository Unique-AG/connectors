from collections.abc import AsyncGenerator

import pytest

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.custom_fields import CustomFieldsService
from backstop_mcp.features.data_hygiene import EmploymentIndexFactory
from backstop_mcp.features.org_people import (
    GetOrganizationQuery,
    GetPeopleForOrganizationQuery,
    GetPersonQuery,
)
from tests.helpers import (
    build_employment_index_factory,
    client_factory,
    credential,
    custom_fields_service,
)


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_get_person_query(
    client: BackstopClient,
    *,
    custom_fields: CustomFieldsService | None = None,
    employment_index_factory: EmploymentIndexFactory | None = None,
) -> GetPersonQuery:
    return GetPersonQuery(
        client=client,
        custom_fields_service=custom_fields
        if custom_fields is not None
        else custom_fields_service(),
        employment_index_factory=(
            employment_index_factory
            if employment_index_factory is not None
            else build_employment_index_factory()
        ),
    )


def make_get_organization_query(
    client: BackstopClient,
    *,
    custom_fields: CustomFieldsService | None = None,
) -> GetOrganizationQuery:
    return GetOrganizationQuery(
        client=client,
        custom_fields_service=custom_fields
        if custom_fields is not None
        else custom_fields_service(),
    )


def make_get_people_for_organization_query(
    client: BackstopClient,
    *,
    employment_index_factory: EmploymentIndexFactory | None = None,
) -> GetPeopleForOrganizationQuery:
    return GetPeopleForOrganizationQuery(
        client=client,
        employment_index_factory=(
            employment_index_factory
            if employment_index_factory is not None
            else build_employment_index_factory()
        ),
    )
