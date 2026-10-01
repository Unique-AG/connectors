from typing import cast, get_args

import httpx
import pytest
import respx
from pydantic.fields import FieldInfo

from backstop_mcp.features.org_people import SearchOrganizationsResolvedResponse
from backstop_mcp.features.org_people.tools.search_organizations import (
    OrganizationCustomFieldFilter,
    search_organizations,
)
from backstop_mcp.server.tools import TOOLS
from tests.features.org_people.conftest import make_search_organizations_query
from tests.helpers import BASE_URL, resource, tool_client
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload


def _page(*items: dict[str, object], total: int) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": list(items),
            "links": {"next": None},
            "meta": {"totalResourceCount": total},
        },
    )


class TestSearchOrganizations:
    def test_is_registered_and_says_which_filters_are_server_side(self) -> None:
        assert search_organizations in TOOLS
        doc = search_organizations.__doc__ or ""
        assert "sent to Backstop" in doc
        assert "after that walk" in doc
        assert "list_custom_fields" in doc
        assert "get_organization" in doc
        assert "Call like:" in doc
        assert "definition_id" in doc
        annotations = cast("dict[str, object]", search_organizations.__annotations__)
        city = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["city"]))
            if isinstance(item, FieldInfo)
        )
        assert city.description is not None
        assert "400" in city.description

    def test_says_prospects_are_organizations_not_opportunity_stages(self) -> None:
        doc = " ".join((search_organizations.__doc__ or "").split())
        assert "Prospects" in doc
        assert "not by opportunity stage" in doc
        assert "custom_field_columns" in doc
        annotations = cast("dict[str, object]", search_organizations.__annotations__)
        country = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["country"]))
            if isinstance(item, FieldInfo)
        )
        assert country.description is not None
        assert "United Arab Emirates" in country.description

    @pytest.mark.asyncio
    @respx.mock
    async def test_passes_any_of_values_and_columns_to_the_walk(self) -> None:
        base_url = f"{BASE_URL}/org-search-tool-columns"
        respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                resource(
                    "7",
                    "organizations",
                    name="Abu Dhabi Pension",
                    country="United Arab Emirates",
                    city="Abu Dhabi",
                    regularCustomFieldValues=[
                        {"definitionId": "261621", "name": "Investor Status", "value": "Prospect"},
                        {"definitionId": "8646227", "name": "Grade", "value": "Focus"},
                    ],
                ),
                resource(
                    "8",
                    "organizations",
                    name="Dubai Client",
                    country="United Arab Emirates",
                    regularCustomFieldValues=[
                        {
                            "definitionId": "261621",
                            "name": "Investor Status",
                            "value": "Current Investor",
                        },
                    ],
                ),
                total=2,
            )
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_organizations(
                    country="united arab",
                    custom_fields=[
                        OrganizationCustomFieldFilter(
                            definition_id="261621", values=["Prospect", "Former Investor"]
                        )
                    ],
                    custom_field_columns=["8646227"],
                    search_organizations_query=make_search_organizations_query(client),
                ),
                SearchOrganizationsResolvedResponse,
            )

        rows = object_list(tool_payload(result)["rows"])
        assert len(rows) == 1
        row = object_dict(rows[0])
        assert row["id"] == "7"
        assert row["custom_field_columns"] == [
            {"definition_id": "8646227", "name": "Grade", "value": "Focus"}
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_url_is_opt_in(self) -> None:
        base_url = f"{BASE_URL}/org-search-url"
        respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                resource("42", "organizations", name="Koch", city="Wichita"),
                total=1,
            )
        )

        async with tool_client(base_url) as client:
            query = make_search_organizations_query(client, ui_base_url="https://crm.example")
            plain = tool_model(
                await search_organizations(name="Koch", search_organizations_query=query),
                SearchOrganizationsResolvedResponse,
            )
            linked = tool_model(
                await search_organizations(
                    name="Koch",
                    fields=["name", "url"],
                    search_organizations_query=query,
                ),
                SearchOrganizationsResolvedResponse,
            )

        plain_row = object_dict(object_list(tool_payload(plain)["rows"])[0])
        linked_row = object_dict(object_list(tool_payload(linked)["rows"])[0])
        assert "url" not in plain_row
        assert plain_row["id"] == "42"
        assert "party_id=42" in str(linked_row["url"])
        assert "ManageOrganization.action" in str(linked_row["url"])
