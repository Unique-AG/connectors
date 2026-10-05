from typing import cast, get_args

import httpx
import pytest
import respx
from pydantic.fields import FieldInfo

from backstop_mcp.features.org_people import LocationFilter, SearchPeopleResolvedResponse
from backstop_mcp.features.org_people.tools.search_people import (
    PersonCustomFieldFilter,
    search_people,
)
from backstop_mcp.server.tools import TOOLS
from tests.features.org_people.conftest import make_search_people_query
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


class TestSearchPeople:
    def test_is_registered_and_says_which_filters_are_server_side(self) -> None:
        assert search_people in TOOLS
        doc = search_people.__doc__ or ""
        assert "sent to Backstop" in doc
        assert "after that walk" in doc
        assert "list_custom_fields" in doc
        assert "get_person" in doc
        assert "Call like:" in doc
        assert "definition_id" in doc
        annotations = cast("dict[str, object]", search_people.__annotations__)
        location_filter = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["location_filter"]))
            if isinstance(item, FieldInfo)
        )
        assert location_filter.description is not None
        assert "sent to Backstop" in location_filter.description
        name = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["name"]))
            if isinstance(item, FieldInfo)
        )
        assert name.description is not None
        assert "Not a substring" in name.description

    def test_keeps_custom_field_matching_on_the_definition_id(self) -> None:
        doc = " ".join((search_people.__doc__ or "").split())
        assert "list_custom_fields for people and party" not in doc
        assert "not an opportunity stage" not in doc
        assert "custom_field_values" in doc
        annotations = cast("dict[str, object]", search_people.__annotations__)
        location_filter = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["location_filter"]))
            if isinstance(item, FieldInfo)
        )
        assert location_filter.description is not None
        assert "same location" in location_filter.description
        country = LocationFilter.model_fields["country"].description
        assert country is not None
        assert "United Arab Emirates" in country

    @pytest.mark.asyncio
    @respx.mock
    async def test_passes_any_of_values_and_publishes_every_field(self) -> None:
        base_url = f"{BASE_URL}/people-search-tool-columns"
        respx.get(f"{base_url}/people").mock(
            return_value=_page(
                resource(
                    "7",
                    "people",
                    name="West, Ann",
                    country="United Arab Emirates",
                    city="Abu Dhabi",
                    regularCustomFieldValues=[
                        {"definitionId": "900011", "name": "Tier", "value": "Tier 1"},
                        {"definitionId": "900013", "name": "Relationship", "value": "Tier 1"},
                    ],
                ),
                resource(
                    "8",
                    "people",
                    name="North, Bea",
                    country="United Arab Emirates",
                    regularCustomFieldValues=[
                        {"definitionId": "900011", "name": "Tier", "value": "Tier 2"},
                    ],
                ),
                total=2,
            )
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await search_people(
                    location_filter=LocationFilter(country="united arab"),
                    custom_fields=[
                        PersonCustomFieldFilter(definition_id="900011", values=["Tier 1", "Tier 3"])
                    ],
                    search_people_query=make_search_people_query(client),
                ),
                SearchPeopleResolvedResponse,
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
        async with tool_client(f"{BASE_URL}/people-search-refused") as client:
            with pytest.raises(ValueError, match="exclude_custom_fields"):
                await search_people(
                    custom_fields=[PersonCustomFieldFilter(definition_id="1", values=["Yes"])],
                    exclude_custom_fields=True,
                    search_people_query=make_search_people_query(client),
                )

    @pytest.mark.asyncio
    @respx.mock
    async def test_url_is_opt_in(self) -> None:
        base_url = f"{BASE_URL}/people-search-url"
        respx.get(f"{base_url}/people").mock(
            return_value=_page(
                resource("42", "people", name="West, Ann", city="Wichita"),
                total=1,
            )
        )

        async with tool_client(base_url) as client:
            query = make_search_people_query(client, ui_base_url="https://crm.example")
            plain = tool_model(
                await search_people(last_name="West", search_people_query=query),
                SearchPeopleResolvedResponse,
            )
            linked = tool_model(
                await search_people(
                    last_name="West",
                    fields=["name", "url"],
                    search_people_query=query,
                ),
                SearchPeopleResolvedResponse,
            )

        plain_row = object_dict(object_list(tool_payload(plain)["rows"])[0])
        linked_row = object_dict(object_list(tool_payload(linked)["rows"])[0])
        assert "url" not in plain_row
        assert plain_row["id"] == "42"
        assert "party_id=42" in str(linked_row["url"])
        assert "ManagePerson.action" in str(linked_row["url"])
