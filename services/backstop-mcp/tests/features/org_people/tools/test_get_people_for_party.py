import httpx
import pytest
import respx
from fastmcp.decorators import get_fastmcp_meta
from fastmcp.tools.function_tool import ToolMeta

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.org_people import OrgPeopleResolvedResponse
from backstop_mcp.features.org_people.tools.get_people_for_party import get_people_for_party
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.server.tools import TOOLS
from tests.features.data_hygiene.helpers import (
    EMPLOYEE_TYPE,
    FORMER_MIRROR_TYPE,
    person_org,
    relationship_types,
)
from tests.features.party_resolver.helpers import ctx_never_elicit
from tests.helpers import BASE_URL, build_employment_index_factory
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

_INDEX = build_employment_index_factory()


_ORG = "341764767"
_EMPLOYEES_URL = f"{BASE_URL}/organizations/{_ORG}/employees"
_ER_URL = f"{BASE_URL}/organizations/{_ORG}/entityRelationships"


class TestGetPeopleForParty:
    @pytest.mark.asyncio
    @respx.mock
    async def test_lists_current_people_with_employment_at_the_org(
        self, client: BackstopClient
    ) -> None:
        respx.get(_EMPLOYEES_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "p1",
                            "type": "employees",
                            "attributes": {
                                "name": "Glenn, Phil",
                                "jobTitle": "Tax Director",
                                "email": "phil@example.com",
                            },
                        }
                    ],
                    "included": [
                        person_org(
                            "er1",
                            source_type="people",
                            source_id="p1",
                            dest_type="organizations",
                            dest_id=_ORG,
                            type_id=EMPLOYEE_TYPE,
                        ),
                        *relationship_types(EMPLOYEE_TYPE),
                    ],
                },
            )
        )
        respx.get(_ER_URL).mock(return_value=httpx.Response(200, json={"data": []}))

        result = tool_model(
            await get_people_for_party(
                ctx_never_elicit(),
                party_id=_ORG,
                client=client,
                employment_index_factory=_INDEX,
            ),
            OrgPeopleResolvedResponse,
        )

        assert result.resolved.id == _ORG
        assert len(result.people) == 1
        row = result.people[0]
        assert row.id == "p1"
        assert row.search_type == "people"
        assert row.name == "Glenn, Phil"
        assert row.job_title == "Tax Director"
        assert row.employment.status == "current"
        assert row.employment.organization_id == _ORG
        assert result.former_omitted == 0
        assert result.include_former_hint is None
        dumped = object_dict(object_list(tool_payload(result)["people"])[0])
        assert object_dict(dumped["employment"])["status"] == "current"

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_employees_is_not_former_omitted(self, client: BackstopClient) -> None:
        respx.get(_EMPLOYEES_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        respx.get(_ER_URL).mock(return_value=httpx.Response(200, json={"data": []}))

        result = tool_model(
            await get_people_for_party(
                ctx_never_elicit(),
                party_id=_ORG,
                client=client,
                employment_index_factory=_INDEX,
            ),
            OrgPeopleResolvedResponse,
        )

        assert result.people == ()
        assert result.former_omitted == 0
        assert result.include_former_hint is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_former_only_org_sets_include_former_hint(
        self, client: BackstopClient
    ) -> None:
        respx.get(_EMPLOYEES_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        respx.get(_ER_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        person_org(
                            "er-former",
                            source_type="organizations",
                            source_id=_ORG,
                            dest_type="people",
                            dest_id="p2",
                            type_id=FORMER_MIRROR_TYPE,
                        )
                    ],
                    "included": relationship_types(FORMER_MIRROR_TYPE),
                },
            )
        )

        result = tool_model(
            await get_people_for_party(
                ctx_never_elicit(),
                party_id=_ORG,
                client=client,
                employment_index_factory=_INDEX,
            ),
            OrgPeopleResolvedResponse,
        )

        assert result.people == ()
        assert result.former_omitted == 1
        assert result.include_former_hint is not None
        assert "include_former=true" in result.include_former_hint

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_party_is_not_found(self, client: BackstopClient) -> None:
        respx.get(f"{BASE_URL}/quick-search").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        result = tool_model(
            await get_people_for_party(
                ctx_never_elicit(),
                search="No Such Org",
                client=client,
                employment_index_factory=_INDEX,
            ),
            NotFoundResponse,
        )

        assert result.scope == "organizations"

    def test_is_registered(self) -> None:
        assert get_people_for_party in TOOLS
        meta = get_fastmcp_meta(get_people_for_party)
        assert isinstance(meta, ToolMeta)
        doc = get_people_for_party.__doc__ or ""
        assert "numberOfEmployees" in doc
        assert "employment" in doc

    def test_output_schema_describes_employment_status(self) -> None:
        meta = get_fastmcp_meta(get_people_for_party)
        assert isinstance(meta, ToolMeta)
        schema = meta.output_schema
        assert schema is not None
        dumped = str(schema)
        assert "current" in dumped
        assert "former" in dumped
        assert "include_former" in dumped
