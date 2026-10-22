import json

from fastmcp import Client
from fastmcp import FastMCP
import httpx2

from tests.offline_server import build_server
from tests.offline_server import fake_upstream_settings


def _token(request: httpx2.Request) -> httpx2.Response | None:
    if request.url.path != "/auth/oauth2/v1/token":
        return None
    return httpx2.Response(
        200, json={"access_token": "access-token", "token_type": "Bearer", "expires_in": 3600}
    )


def _json(status: int, body: object) -> httpx2.Response:
    return httpx2.Response(status, json=json.loads(json.dumps(body)))


def _world_check(request: httpx2.Request) -> httpx2.Response:
    token = _token(request)
    if token is not None:
        return token
    path = request.url.path
    if path.endswith("/groups") and request.url.params.get("showAllChildGroups") == "true":
        return _json(
            200, [{"id": "g1", "name": "KYC", "childGroups": [{"id": "g2", "name": "EU"}]}]
        )
    if path.endswith("/groups/g1/case-template"):
        return _json(
            200,
            {
                "groupId": "g1",
                "groupScreeningType": "CASE",
                "mandatoryProviderTypes": ["WATCHLIST"],
                "secondaryFieldsByProvider": {
                    "WATCHLIST": {
                        "secondaryFieldsByEntity": {
                            "INDIVIDUAL": [
                                {
                                    "typeId": "SFCT_5",
                                    "fieldValueType": "COUNTRY",
                                    "label": "NATIONALITY",
                                    "fieldRequired": True,
                                }
                            ]
                        }
                    }
                },
            },
        )
    if path.endswith("/groups/g1/resolution-toolkits"):
        return _json(
            200,
            {
                "WATCHLIST": {
                    "groupId": "g1",
                    "providerType": "WATCHLIST",
                    "resolutionFields": {
                        "statuses": [{"id": "s1", "label": "Positive", "type": "POSITIVE"}],
                        "risks": [{"id": "r1", "label": "High"}],
                        "reasons": [{"id": "n1", "label": "Full match"}],
                    },
                }
            },
        )
    if path.endswith("/groups/g1"):
        return _json(200, {"id": "g1", "name": "KYC"})
    if "/references/cases/" in path and path.endswith("ext-1"):
        return _json(200, {"caseId": "ext-1", "caseSystemId": "sys-1"})
    if path.endswith("/cases/ext-1"):
        return httpx2.Response(404)
    if path.endswith("/cases/sys-1"):
        return _json(
            200,
            {
                "caseId": "ext-1",
                "caseSystemId": "sys-1",
                "name": "Ada Lovelace",
                "entityType": "INDIVIDUAL",
                "groupId": "g1",
                "providerTypes": ["WATCHLIST"],
                "lifecycleState": "UNARCHIVED",
            },
        )
    if path.endswith("/references/records/e_1"):
        return _json(
            200,
            {
                "entityType": "INDIVIDUAL",
                "referenceId": "e_1",
                "names": {"nameDetails": [{"details": [{"value": "Ada Lovelace"}]}]},
                "sources": [],
                "categories": [{"value": "PEP"}],
            },
        )
    if path.endswith("/references/countries"):
        return _json(200, {"GBR": "United Kingdom"})
    if path.endswith("/references/nationalities"):
        return _json(200, {"GBR": "British"})
    if path.endswith("/references/providers"):
        return _json(200, [{"code": "trwc", "identifier": "wc", "name": "World-Check"}])
    if path.endswith("/references/search-filters"):
        return _json(
            200,
            {
                "freeTextParameters": [
                    {"fields": ["primaryName"], "type": "QUERY", "valueType": "STRING"}
                ]
            },
        )
    if path.endswith("/apiInfo"):
        return _json(200, {"version": "3.9.0", "systemDateTime": "2026-10-22T06:47:00Z"})
    return httpx2.Response(404)


def _server() -> FastMCP:
    return build_server(fake_upstream_settings(), httpx2.MockTransport(_world_check))


async def test_list_groups_returns_descendant_groups() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("list_groups", {})

    groups = result.structured_content
    assert groups is not None
    assert groups["result"][0]["child_groups"][0]["name"] == "EU"


async def test_get_group_settings_joins_the_template_and_toolkit() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_group_settings", {"group_id": "g1"})

    settings = result.structured_content
    assert settings is not None
    assert settings["secondary_fields"][0]["type_id"] == "SFCT_5"
    assert settings["toolkits"][0]["statuses"][0]["status_type"] == "POSITIVE"


async def test_get_case_resolves_an_external_id_after_the_internal_lookup_misses() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_case", {"case": "ext-1"})

    details = result.structured_content
    assert details is not None
    assert details["case_system_id"] == "sys-1"
    assert details["name"] == "Ada Lovelace"


async def test_get_case_reference_returns_the_internal_id() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_case_reference", {"case_id": "ext-1"})

    assert result.structured_content == {"case_id": "ext-1", "case_system_id": "sys-1"}


async def test_get_profile_uses_the_record_reference_id() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_profile", {"reference_id": "e_1"})

    profile = result.structured_content
    assert profile is not None
    assert profile["names"] == ["Ada Lovelace"]
    assert profile["categories"] == ["PEP"]


async def test_get_reference_data_returns_country_codes() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("get_reference_data", {"kind": "countries"})

    assert result.structured_content == {
        "kind": "countries",
        "names_by_code": {"GBR": "United Kingdom"},
        "providers": None,
        "search_filters": None,
        "api_version": None,
        "system_date_time": None,
    }
