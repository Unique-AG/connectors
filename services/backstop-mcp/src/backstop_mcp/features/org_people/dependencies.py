from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.custom_fields import CustomFieldsService, get_custom_fields_service
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    get_employment_index_factory,
)
from backstop_mcp.features.org_people.queries import (
    GetOrganizationQuery,
    GetPeopleForOrganizationQuery,
    GetPersonQuery,
)


@lru_cache(maxsize=1)
def get_person_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    employment_index_factory: EmploymentIndexFactory = Depends(get_employment_index_factory),
    custom_fields_service: CustomFieldsService = Depends(get_custom_fields_service),
) -> GetPersonQuery:
    return GetPersonQuery(
        client=client,
        employment_index_factory=employment_index_factory,
        custom_fields_service=custom_fields_service,
    )


@lru_cache(maxsize=1)
def get_organization_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    custom_fields_service: CustomFieldsService = Depends(get_custom_fields_service),
) -> GetOrganizationQuery:
    return GetOrganizationQuery(client=client, custom_fields_service=custom_fields_service)


@lru_cache(maxsize=1)
def get_people_for_organization_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    employment_index_factory: EmploymentIndexFactory = Depends(get_employment_index_factory),
) -> GetPeopleForOrganizationQuery:
    return GetPeopleForOrganizationQuery(
        client=client, employment_index_factory=employment_index_factory
    )
