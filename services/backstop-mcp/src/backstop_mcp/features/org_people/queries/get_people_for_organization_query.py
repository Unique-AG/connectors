"""Walk an organization's `/employees` with employment includes, annotated via `EmploymentIndex`."""

from urllib.parse import quote

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient, Included
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    EmploymentLinkResponse,
    EntityRelationshipAttributes,
    EntityRelationshipInclude,
    EntityRelationshipRef,
    RelationshipTypeAttributes,
)
from backstop_mcp.features.org_people.api_responses import EmployeeResource
from backstop_mcp.features.org_people.responses import (
    PartyOrgPeopleResponse,
    PersonAtOrganizationResponse,
)

MAX_ORG_PEOPLE = 500


class GetPeopleForOrganizationQuery:
    """People the employment index ties to one organization, with their `/employees` card.

    Current staff are one paginated walk of `/organizations/{id}/employees` with
    `include=entityRelationships,entityRelationships.entityRelationshipType` and a sparse
    employee fieldset for the contact card. Status comes from `EmploymentIndex` — not from
    `numberOfEmployees`. `/employees` is current staff only, so the organization's
    `entityRelationships` are always walked as well: former people live there, and without
    that walk `former_omitted` cannot tell an empty roster from a former-only one.
    `include_former` only controls whether those former people are returned.
    """

    def __init__(
        self,
        *,
        client: BackstopClient,
        employment_index_factory: EmploymentIndexFactory,
    ) -> None:
        self._client: BackstopClient = client
        self._employment_index_factory: EmploymentIndexFactory = employment_index_factory

    async def run(self, *, organization_id: str, include_former: bool) -> PartyOrgPeopleResponse:
        quoted_organization_id = quote(organization_id, safe="")
        employees_page = await self._client.paginate(
            f"/organizations/{quoted_organization_id}/employees",
            schema=EmployeeResource,
            params={
                "include": EntityRelationshipInclude.for_employment(),
                "fields[employees]": "name,jobTitle,email,phone,companyName,categories",
            },
            max_records=None,
            page_size=100,
        )
        organization_relationships_page = await self._client.paginate(
            f"/organizations/{quoted_organization_id}/entityRelationships",
            schema=BackstopApiResource[EntityRelationshipAttributes],
            params={"include": EntityRelationshipRef.TYPE.value},
            max_records=None,
            page_size=100,
        )
        employee_includes = Included(employees_page.included)
        organization_includes = Included(organization_relationships_page.included)
        relationships = [
            *employee_includes.by_type(
                EntityRelationshipRef.RELATIONSHIPS_RESOURCE,
                schema=BackstopApiResource[EntityRelationshipAttributes],
            ),
            *organization_relationships_page.items,
        ]
        relationship_types = [
            *employee_includes.by_type(
                EntityRelationshipRef.TYPES_RESOURCE,
                schema=BackstopApiResource[RelationshipTypeAttributes],
            ),
            *organization_includes.by_type(
                EntityRelationshipRef.TYPES_RESOURCE,
                schema=BackstopApiResource[RelationshipTypeAttributes],
            ),
        ]
        employment_index = self._employment_index_factory.index(
            relationships=relationships,
            relationship_types=relationship_types,
        )
        current_employments = employment_index.current()
        former_employments = employment_index.former()
        if not include_former:
            selected_employments = current_employments
            former_omitted = sum(
                1
                for employment in former_employments
                if employment.organization_id == organization_id
            )
        else:
            selected_employments = (*current_employments, *former_employments)
            former_omitted = 0
        employments_at_organization = tuple(
            employment
            for employment in selected_employments
            if employment.organization_id == organization_id
        )
        listed_employments = employments_at_organization[:MAX_ORG_PEOPLE]
        people_omitted = len(employments_at_organization) - len(listed_employments)
        listed_employment_keys = {
            (employment.person_id, employment.organization_id) for employment in listed_employments
        }
        employment_links = tuple(
            employment
            for employment in employment_index.links()
            if (employment.person_id, employment.organization_id) in listed_employment_keys
        )
        employees_by_id = {employee.id: employee for employee in employees_page.items}
        people = tuple(
            self._person_at_organization(employment, employees_by_id.get(employment.person_id))
            for employment in employment_links
        )
        return PartyOrgPeopleResponse(
            people=people,
            former_omitted=former_omitted,
            people_omitted=people_omitted,
        )

    def _person_at_organization(
        self, employment: EmploymentLinkResponse, employee: EmployeeResource | None
    ) -> PersonAtOrganizationResponse:
        if employee is None:
            return PersonAtOrganizationResponse.from_employment(employment)
        return PersonAtOrganizationResponse.from_resource(employment, employee)
