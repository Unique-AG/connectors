import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from backstop_mcp.features.system_users import SystemUserDto, get_current_caller_system_user
from tests.helpers import BASE_URL, recorded_requests, resource, system_users_service, tool_client


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
    email: str = "margaret.lucas@example.com",
    **attrs: object,
) -> dict[str, object]:
    return resource(
        user_id,
        "system-users",
        name=name,
        userName=user_name,
        email=email,
        phoneNumber="12122321462",
        disabled=False,
        **attrs,
    )


def _filter_params(params: httpx.QueryParams) -> list[str]:
    return [name for name, _value in params.multi_items() if name.startswith("filter[")]


class TestResolveByUserName:
    @respx.mock
    async def test_resolves_id_from_exact_user_name_after_one_catalog_walk(self) -> None:
        base_url = tenant("su-resolve-exact")
        users_route = respx.get(f"{base_url}/system-users").mock(
            return_value=_collection_page(
                _user("u1"),
                _user("u2", name="Departed", user_name="jsmith"),
                resource("u3", "system-users"),
            )
        )

        async with tool_client(base_url) as client:
            users = system_users_service(client)
            result = await users.resolve_by_user_name("mlucas")

        assert users_route.call_count == 1
        assert _filter_params(recorded_requests(users_route.calls)[0].url.params) == []
        assert result.id == "u1"
        assert result.user_name == "mlucas"

    @respx.mock
    async def test_matches_user_name_case_insensitively(self) -> None:
        base_url = tenant("su-resolve-case")
        respx.get(f"{base_url}/system-users").mock(return_value=_collection_page(_user("u1")))

        async with tool_client(base_url) as client:
            result = await system_users_service(client).resolve_by_user_name("MLUCAS")

        assert result.id == "u1"
        assert result.user_name == "mlucas"

    @respx.mock
    async def test_does_not_substring_match_user_name(self) -> None:
        base_url = tenant("su-resolve-substr")
        respx.get(f"{base_url}/system-users").mock(return_value=_collection_page(_user("u1")))

        async with tool_client(base_url) as client:
            with pytest.raises(ToolError, match="mluca"):
                await system_users_service(client).resolve_by_user_name("mluca")

    @respx.mock
    async def test_does_not_match_display_name_or_email(self) -> None:
        base_url = tenant("su-resolve-name-email")
        respx.get(f"{base_url}/system-users").mock(
            return_value=_collection_page(
                _user(
                    "u1",
                    name="mlucas",
                    user_name="jsmith",
                    email="mlucas@example.com",
                )
            )
        )

        async with tool_client(base_url) as client:
            with pytest.raises(ToolError, match="mlucas"):
                await system_users_service(client).resolve_by_user_name("mlucas")

    @respx.mock
    async def test_missing_login_raises_naming_the_username(self) -> None:
        base_url = tenant("su-resolve-missing")
        respx.get(f"{base_url}/system-users").mock(
            return_value=_collection_page(_user("u1", user_name="jsmith"))
        )

        async with tool_client(base_url) as client:
            with pytest.raises(ToolError, match="nobody") as raised:
                await system_users_service(client).resolve_by_user_name("nobody")

        assert "nobody" in str(raised.value)
        assert "token" not in str(raised.value).casefold()

    @respx.mock
    async def test_duplicate_user_name_raises(self) -> None:
        base_url = tenant("su-resolve-dup")
        respx.get(f"{base_url}/system-users").mock(
            return_value=_collection_page(
                _user("u1", user_name="mlucas"),
                _user("u2", name="Other Lucas", user_name="MLUCAS"),
            )
        )

        async with tool_client(base_url) as client:
            with pytest.raises(ToolError, match="mlucas"):
                await system_users_service(client).resolve_by_user_name("mlucas")

    @respx.mock
    async def test_resolve_relationship_returns_a_json_api_relationship(self) -> None:
        """Backstop takes identity pointers only as relationships, never as attributes."""
        base_url = tenant("su-resolve-link")
        respx.get(f"{base_url}/system-users").mock(return_value=_collection_page(_user("u1")))

        async with tool_client(base_url) as client:
            result = await system_users_service(client).resolve_relationship("mlucas")

        assert result == {"data": {"type": "system-users", "id": "u1"}}

    @respx.mock
    async def test_resolve_relationship_returns_none_without_fetching(self) -> None:
        base_url = tenant("su-resolve-link-none")
        route = respx.get(f"{base_url}/system-users").mock(
            return_value=_collection_page(_user("u1"))
        )

        async with tool_client(base_url) as client:
            result = await system_users_service(client).resolve_relationship(None)

        assert result is None
        assert route.call_count == 0

    @respx.mock
    async def test_a_missing_login_does_not_blame_the_credential(self) -> None:
        """This resolves task assignees too, so it must not read as an auth failure."""
        base_url = tenant("su-resolve-neutral")
        respx.get(f"{base_url}/system-users").mock(
            return_value=_collection_page(_user("u1", user_name="jsmith"))
        )

        async with tool_client(base_url) as client:
            with pytest.raises(ToolError) as raised:
                await system_users_service(client).resolve_by_user_name("nobody")

        message = str(raised.value)
        assert "list_system_users" in message
        assert "authenticated" not in message


@respx.mock
async def test_get_current_caller_system_user_frames_a_miss_as_a_credential_problem() -> None:
    """Here the login *is* the credential, so nothing the agent passes can fix it."""
    base_url = tenant("su-caller-miss")
    respx.get(f"{base_url}/system-users").mock(
        return_value=_collection_page(_user("u1", user_name="jsmith"))
    )

    async with tool_client(base_url) as client:
        with pytest.raises(ToolError, match="authenticated") as raised:
            await get_current_caller_system_user("nobody", system_users_service(client))

    message = str(raised.value)
    assert "nobody" in message
    assert "cannot be authored" in message


@respx.mock
async def test_get_current_caller_system_user_returns_the_matching_dto() -> None:
    base_url = tenant("su-resolve-provider")
    respx.get(f"{base_url}/system-users").mock(return_value=_collection_page(_user("u1")))

    async with tool_client(base_url) as client:
        result = await get_current_caller_system_user("mlucas", system_users_service(client))

    assert type(result) is SystemUserDto
    assert result.id == "u1"
    assert result.user_name == "mlucas"
