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
        assert "Applied after the server-side read" in city.description

    def test_keeps_custom_field_matching_on_the_definition_id(self) -> None:
        doc = " ".join((search_organizations.__doc__ or "").split())
        assert "list_custom_fields" in doc
        assert "not an opportunity stage" not in doc
        assert "custom_field_values" in doc
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
    async def test_passes_any_of_values_and_publishes_every_field(self) -> None:
        base_url = f"{BASE_URL}/org-search-tool-columns"
        respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                resource(
                    "7",
                    "organizations",
                    name="Contoso Pension",
                    country="United Arab Emirates",
                    city="Abu Dhabi",
                    regularCustomFieldValues=[
                        {"definitionId": "900011", "name": "Tier", "value": "Tier 1"},
                        {"definitionId": "900013", "name": "Relationship", "value": "Tier 1"},
                    ],
                ),
                resource(
                    "8",
                    "organizations",
                    name="Northwind Client",
                    country="United Arab Emirates",
                    regularCustomFieldValues=[
                        {
                            "definitionId": "900011",
                            "name": "Tier",
                            "value": "Tier 2",
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
                            definition_id="900011", values=["Tier 1", "Tier 3"]
                        )
                    ],
                    search_organizations_query=make_search_organizations_query(client),
                ),
                SearchOrganizationsResolvedResponse,
            )

        rows = object_list(tool_payload(result)["rows"])
        assert len(rows) == 1
        row = object_dict(rows[0])
        assert row["id"] == "7"
        assert row["custom_field_values"] == [
            {"definition_id": "900011", "name": "Tier", "value": "Tier 1"},
            {"definition_id": "900013", "name": "Relationship", "value": "Tier 1"},
        ]

    @pytest.mark.asyncio
    async def test_exclude_custom_fields_is_refused_with_a_custom_field_filter(self) -> None:
        async with tool_client(f"{BASE_URL}/org-search-refused") as client:
            with pytest.raises(ValueError, match="exclude_custom_fields"):
                await search_organizations(
                    custom_fields=[
                        OrganizationCustomFieldFilter(definition_id="1", values=["Yes"])
                    ],
                    exclude_custom_fields=True,
                    search_organizations_query=make_search_organizations_query(client),
                )

    @pytest.mark.asyncio
    @respx.mock
    async def test_url_is_opt_in(self) -> None:
        base_url = f"{BASE_URL}/org-search-url"
        respx.get(f"{base_url}/organizations").mock(
            return_value=_page(
                resource("42", "organizations", name="Contoso", city="Wichita"),
                total=1,
            )
        )

        async with tool_client(base_url) as client:
            query = make_search_organizations_query(client, ui_base_url="https://crm.example")
            plain = tool_model(
                await search_organizations(name="Contoso", search_organizations_query=query),
                SearchOrganizationsResolvedResponse,
            )
            linked = tool_model(
                await search_organizations(
                    name="Contoso",
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
