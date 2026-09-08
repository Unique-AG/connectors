from typing import cast, get_args

import httpx
import pytest
import respx
from fastmcp.server.dependencies import without_injected_parameters
from pydantic import TypeAdapter
from pydantic.fields import FieldInfo

from backstop_mcp.features.system_users import ListSystemUsersResponse
from backstop_mcp.features.system_users.tools.list_system_users import list_system_users
from backstop_mcp.server.tools import TOOLS
from tests.helpers import BASE_URL, recorded_requests, resource, system_users_service, tool_client
from tests.server.tools.helpers import object_dict, object_list, tool_model, tool_payload

_INPUT: TypeAdapter[object] = TypeAdapter(without_injected_parameters(list_system_users))


def tenant(name: str) -> str:
    return f"{BASE_URL}/{name}"


def _collection_page(*items: dict[str, object], next_url: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": list(items), "links": {"next": next_url}},
    )


def _user(
    user_id: str,
    *,
    name: str = "Margaret Lucas",
    user_name: str = "mlucas",
    disabled: bool = False,
    **attrs: object,
) -> dict[str, object]:
    return resource(
        user_id,
        "system-users",
        name=name,
        userName=user_name,
        email="margaret.lucas@example.com",
        phoneNumber="12122321462",
        disabled=disabled,
        **attrs,
    )


class TestListSystemUsers:
    def test_is_registered_and_says_the_filter_takes_a_login(self) -> None:
        assert list_system_users in TOOLS
        doc = list_system_users.__doc__ or ""
        assert "login" in doc
        assert "search_opportunities" in doc
        assert "disabled" in doc

    @pytest.mark.asyncio
    @respx.mock
    async def test_projects_login_and_disabled_from_one_collection_walk(self) -> None:
        base_url = tenant("su-project")
        users_route = respx.get(f"{base_url}/system-users").mock(
            return_value=_collection_page(
                _user("u1"),
                _user("u2", name="Departed", user_name="jsmith", disabled=True),
                resource("u3", "system-users"),
            )
        )

        async with tool_client(base_url) as client:
            result = tool_model(
                await list_system_users(
                    refresh=True,
                    system_users=system_users_service(client),
                ),
                ListSystemUsersResponse,
            )

        assert users_route.call_count == 1
        params = recorded_requests(users_route.calls)[0].url.params
        assert params["page[offset]"] == "0"
        assert params["page[limit]"] == "200"
        assert "filter[name][like]" not in params
        payload = tool_payload(result)
        users = [object_dict(item) for item in object_list(payload["users"])]
        assert [item["id"] for item in users] == ["u1", "u2", "u3"]
        assert users[0]["user_name"] == "mlucas"
        assert users[0]["disabled"] is False
        assert users[1]["user_name"] == "jsmith"
        assert users[1]["disabled"] is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_call_uses_cache_and_refresh_refetches(self) -> None:
        base_url = tenant("su-cache")
        users_route = respx.get(f"{base_url}/system-users").mock(
            return_value=_collection_page(_user("u1"))
        )
        async with tool_client(base_url) as client:
            users = system_users_service(client)
            first = tool_model(
                await list_system_users(system_users=users),
                ListSystemUsersResponse,
            )
            second = tool_model(
                await list_system_users(system_users=users),
                ListSystemUsersResponse,
            )
            refreshed = tool_model(
                await list_system_users(refresh=True, system_users=users),
                ListSystemUsersResponse,
            )

        assert first.cache == "ok"
        assert second.cache == "ok"
        assert refreshed.cache == "ok"
        assert users_route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_failure_serves_stale(self) -> None:
        base_url = tenant("su-stale")
        users_route = respx.get(f"{base_url}/system-users").mock(
            return_value=_collection_page(_user("u1"))
        )
        async with tool_client(base_url) as client:
            users = system_users_service(client)
            first = tool_model(
                await list_system_users(refresh=True, system_users=users),
                ListSystemUsersResponse,
            )
            users_route.mock(side_effect=httpx.ConnectError("backstop down"))
            result = tool_model(
                await list_system_users(refresh=True, system_users=users),
                ListSystemUsersResponse,
            )

        assert first.cache == "ok"
        assert result.cache == "stale"
        assert result.users[0].id == "u1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_filters_the_cached_catalog_without_a_like_request(self) -> None:
        base_url = tenant("su-search")
        users_route = respx.get(f"{base_url}/system-users").mock(
            return_value=_collection_page(
                _user("u1"),
                _user("u2", name="Departed", user_name="jsmith", disabled=True),
            )
        )
        async with tool_client(base_url) as client:
            users = system_users_service(client)
            by_login = tool_model(
                await list_system_users(
                    search="MLUCAS",
                    refresh=True,
                    system_users=users,
                ),
                ListSystemUsersResponse,
            )
            by_name = tool_model(
                await list_system_users(
                    search="departed",
                    system_users=users,
                ),
                ListSystemUsersResponse,
            )

        assert users_route.call_count == 1
        assert "filter[name][like]" not in recorded_requests(users_route.calls)[0].url.params
        assert [user.id for user in by_login.users] == ["u1"]
        assert [user.id for user in by_name.users] == ["u2"]


class TestListSystemUsersInput:
    def test_accepts_search(self) -> None:
        # Asserted over the adapter's schema, not by validating a payload: `_INPUT` wraps the
        # tool callable, so `validate_python` would validate the arguments and then *call* it,
        # leaving an un-awaited coroutine behind.
        properties = object_dict(object_dict(_INPUT.json_schema())["properties"])
        assert sorted(properties) == ["refresh", "search"]

    def test_refresh_is_only_for_a_user_reported_missing_colleague(self) -> None:
        doc = list_system_users.__doc__ or ""
        assert "refresh=true" in doc
        assert "missing colleague" in doc
        annotations = cast("dict[str, object]", list_system_users.__annotations__)
        field_info = next(
            item
            for item in cast("tuple[object, ...]", get_args(annotations["refresh"]))
            if isinstance(item, FieldInfo)
        )
        assert field_info.description is not None
        assert "missing colleague" in field_info.description
        assert "search" in without_injected_parameters(list_system_users).__annotations__
