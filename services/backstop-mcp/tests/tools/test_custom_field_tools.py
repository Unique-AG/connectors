from collections.abc import Callable

import httpx
import pytest
import respx

from backstop_mcp.config import CustomFieldOverrideConfig
from backstop_mcp.party_resolver import ResolvedPartyEcho
from backstop_mcp.tools.get_organization_custom_field import (
    OrganizationCustomFieldResolvedResponse,
    get_organization_custom_field,
)
from backstop_mcp.tools.resolve_custom_field import (
    ResolveCustomFieldResolvedResponse,
    resolve_custom_field,
)
from tests.party_resolver.helpers import (
    BASE_URL,
    ctx_accept,
    ctx_decline,
    ctx_never_elicit,
    resource,
)

type ConnectUser = Callable[..., object]

_OVERRIDES: dict[str, CustomFieldOverrideConfig] = {
    "organizations:is1": CustomFieldOverrideConfig(
        display_name="Investor Status",
        aliases=["investor status"],
    )
}


def tenant(name: str) -> str:
    """A distinct Backstop base URL per test.

    Schema snapshots are keyed by base URL and the test Postgres persists for the whole
    session, so sharing one URL would let an earlier test's snapshot satisfy a later test's
    `ensure_fresh` and skip the fetch under test.
    """
    return f"{BASE_URL}/{name}"


def _lov_entries_route(base_url: str) -> respx.Route:
    return respx.get(f"{base_url}/lov-entries").mock(
        return_value=httpx.Response(200, json={"data": [], "links": {"next": None}})
    )


def _definitions_route(base_url: str, *definitions: dict[str, object]) -> respx.Route:
    _lov_entries_route(base_url)
    return respx.get(f"{base_url}/custom-field-definitions").mock(
        return_value=httpx.Response(200, json={"data": list(definitions), "links": {"next": None}})
    )


def _investor_status(**extra: object) -> dict[str, object]:
    return resource(
        "99",
        "custom-field-definitions",
        name="is1",
        entityType="Organization",
        fieldType="picklist",
        isTimeSeries=False,
        **extra,
    )


def _two_status_fields() -> tuple[dict[str, object], dict[str, object]]:
    return (
        resource(
            "1", "custom-field-definitions", name="Investor Status", entityType="Organization"
        ),
        resource("2", "custom-field-definitions", name="Account Status", entityType="Organization"),
    )


class TestResolveCustomFieldTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_resolves_with_refresh(self, connect_user: ConnectUser) -> None:
        base_url = tenant("cf-refresh")
        await connect_user("user-cf-1", "cf-bob", base_url=base_url, overrides=_OVERRIDES)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, _investor_status(selectOptions=[{"label": "Active"}]))

        result = await resolve_custom_field(
            ctx_never_elicit(),
            entity_type="organizations",
            query="Investor Status",
            refresh=True,
        )

        assert isinstance(result, ResolveCustomFieldResolvedResponse)
        assert result.definition.definition_id == "99"
        assert result.definition.display_name == "Investor Status"
        assert result.definition.allowed_values[0].label == "Active"

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_field_elicits_a_choice(self, connect_user: ConnectUser) -> None:
        """Field ambiguity now follows the same policy as party ambiguity (UN-23676 step 2).

        Custom-field resolution previously never elicited, so a user saying "status" got a
        payload to interpret while the identical situation for an organization name got a prompt.
        """
        base_url = tenant("cf-elicit")
        await connect_user("user-cf-3", "cf-carol", base_url=base_url)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, *_two_status_fields())

        result = await resolve_custom_field(
            ctx_accept("Account Status"), entity_type="organizations", query="status"
        )

        assert isinstance(result, ResolveCustomFieldResolvedResponse)
        assert result.definition.definition_id == "2"

    @pytest.mark.asyncio
    @respx.mock
    async def test_declined_field_elicit_degrades_to_candidates(
        self, connect_user: ConnectUser
    ) -> None:
        base_url = tenant("cf-declined")
        await connect_user("user-cf-4", "cf-dan", base_url=base_url)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, *_two_status_fields())

        result = await resolve_custom_field(
            ctx_decline(), entity_type="organizations", query="status"
        )

        assert result.status == "ambiguous"
        assert {c.definition_id for c in result.candidates} == {"1", "2"}
        # Same vocabulary as party ambiguity: `query` / `scope` / `candidates`.
        assert result.query == "status"
        assert result.scope == "organizations"

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_field_reports_not_found(self, connect_user: ConnectUser) -> None:
        base_url = tenant("cf-unknown")
        await connect_user("user-cf-5", "cf-erin", base_url=base_url)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, _investor_status())

        result = await resolve_custom_field(
            ctx_never_elicit(), entity_type="organizations", query="Nonexistent Field"
        )

        assert result.status == "not_found"
        assert result.query == "Nonexistent Field"


class TestGetOrganizationCustomFieldTool:
    @pytest.mark.asyncio
    @respx.mock
    async def test_reads_investor_status_for_capstone(self, connect_user: ConnectUser) -> None:
        base_url = tenant("cf-read")
        await connect_user("user-cf-2", "cf-alice", base_url=base_url, overrides=_OVERRIDES)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, _investor_status())
        respx.get(f"{base_url}/quick-search").mock(
            return_value=httpx.Response(
                200,
                json={"data": [resource("o42", "organizations", name="Capstone")]},
            )
        )
        respx.get(f"{base_url}/organizations/o42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "organizations",
                        "id": "o42",
                        "attributes": {
                            "regularCustomFieldValues": [
                                {"definitionId": "99", "value": "Active LP"}
                            ]
                        },
                    }
                },
            )
        )

        result = await get_organization_custom_field(
            ctx_never_elicit(),
            field="Investor Status",
            search="Capstone",
        )

        assert isinstance(result, OrganizationCustomFieldResolvedResponse)
        assert result.value == "Active LP"
        assert result.definition.definition_id == "99"
        assert result.resolved == ResolvedPartyEcho(id="o42", type="organizations", name="Capstone")

    @pytest.mark.asyncio
    @respx.mock
    async def test_trusted_party_id_still_echoes_the_resolved_name(
        self, connect_user: ConnectUser
    ) -> None:
        """UN-23676: every successful resolution echoes name + Party ID.

        This tool never fetches the whole organization, so on the trusted-`party_id` path the
        echo used to come back with `name=None` — the acceptance criterion silently unmet. It now
        passes `confirm_name=True`, buying the echo for one cheap `fields=name` request.
        """
        base_url = tenant("cf-echo")
        await connect_user("user-cf-6", "cf-fred", base_url=base_url, overrides=_OVERRIDES)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, _investor_status())
        name_lookup = respx.get(
            f"{base_url}/organizations/o77", params={"fields": "name,firstName,lastName"}
        ).mock(
            return_value=httpx.Response(
                200, json={"data": resource("o77", "organizations", name="Capstone LP")}
            )
        )
        respx.get(f"{base_url}/organizations/o77").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "organizations",
                        "id": "o77",
                        "attributes": {
                            "regularCustomFieldValues": [{"definitionId": "99", "value": "Warm"}]
                        },
                    }
                },
            )
        )

        result = await get_organization_custom_field(
            ctx_never_elicit(), field="Investor Status", party_id="o77"
        )

        assert isinstance(result, OrganizationCustomFieldResolvedResponse)
        assert result.resolved == ResolvedPartyEcho(
            id="o77", type="organizations", name="Capstone LP"
        )
        assert name_lookup.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_unresolvable_field_short_circuits_before_reading_a_value(
        self, connect_user: ConnectUser
    ) -> None:
        base_url = tenant("cf-shortcircuit")
        await connect_user("user-cf-7", "cf-gina", base_url=base_url, overrides=_OVERRIDES)  # pyright: ignore[reportGeneralTypeIssues]
        _definitions_route(base_url, _investor_status())
        respx.get(f"{base_url}/quick-search").mock(
            return_value=httpx.Response(
                200, json={"data": [resource("o42", "organizations", name="Capstone")]}
            )
        )
        value_read = respx.get(f"{base_url}/organizations/o42").mock(
            return_value=httpx.Response(200, json={"data": None})
        )

        result = await get_organization_custom_field(
            ctx_never_elicit(), field="Totally Unknown", search="Capstone"
        )

        assert result.status == "not_found"
        assert value_read.call_count == 0
